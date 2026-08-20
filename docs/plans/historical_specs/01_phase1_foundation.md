# Agent Task: Phase 1 — Foundation Completion

## Context

Working directory: `/Users/sakethjaggaiahgari/Desktop/local-llm-council`
Stack: FastAPI, LiteLLM, SQLite, Python 3.13 tested, 3.12+ intended
Tests: `./venv/bin/pytest tests/ -q` — must stay green (currently 30 passing)

Read these files before starting:
- `orchestrator.py` — find `_stream_llm_to_queue`, `record_phase_output` calls
- `run_store.py` — understand schema, `begin_run`, `record_phase_output`, `finish_run`
- `main.py` — find existing /runs endpoints (lines ~345-365) and `FeedbackRequest`
- `provider_caps.py` — find `caps_for` fallback behavior and `redact_config`
- `tests/test_run_store.py`, `tests/test_redaction.py`, `tests/test_provider_caps.py` — see what's already tested

## Tasks

### Task A: Fix Phase 3 Chairman Output Not Recorded

In `orchestrator.py`, trace the `run()` method. Phase 1 and Phase 2 outputs are recorded via `run_store.record_phase_output(...)`. Phase 3 (chairman) is NOT recorded.

Add a `run_store.record_phase_output(run_id, phase=3, member_id="chairman", output=chairman_text, tokens_in=..., tokens_out=..., latency_ms=...)` call after the chairman LLM call completes.

Extract token counts and latency from the litellm response object. If token metadata is unavailable (local Ollama), pass `None`.

### Task B: Move RunStore Write Outside Retry Loop

In `orchestrator.py`, find `_stream_llm_to_queue`. The `run_store.record_phase_output(...)` call is inside a retry loop. On retry, this INSERT hits a PRIMARY KEY violation.

Move the `record_phase_output` call to execute only in the success branch after the loop exits. The retry loop should only attempt the LLM call; storage happens once on success.

### Task C: Config Redaction at All Boundaries

`provider_caps.redact_config(d)` exists. Apply it:
1. In `run_store.begin_run()` — wrap `roster` dict with `redact_config` before `json.dumps`
2. In `metrics_store.py` — any place a config/roster dict is serialized to JSONL

Then write adversarial tests in `tests/test_redaction.py`:
- Nested dicts: `{"db": {"api_key": "secret"}}` → inner key redacted
- Lists of dicts: `{"seats": [{"token": "abc"}]}` → list item key redacted
- Mixed key names: `*api_key*`, `*token*`, `*secret*` (case-insensitive) all redacted
- Non-sensitive keys preserved
- Values of type int, None, list handled without crash

### Task D: Safe Unknown-Model Fallback

In `provider_caps.py`, find `caps_for(model)`. When model is not in `MODELS` registry, it falls back to a default `ModelCaps`. That default currently has `response_format=True`.

Change the unknown-model default to: `response_format=False`, `vision=False`, `context_window=4096`.

Update `tests/test_provider_caps.py` to assert:
- `caps_for("made-up-model/unknown-v99")[0].vision == False`
- `caps_for("made-up-model/unknown-v99")[1].response_format == False`
- Known models still return their correct values

### Task E: LLM Call Observability — finish_reason + attempt_number

Add two columns to `phase_outputs`:
```sql
ALTER TABLE phase_outputs ADD COLUMN finish_reason TEXT;
ALTER TABLE phase_outputs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1;
```

Apply via a migration check in `run_store.py` on first connection:
```python
cursor.execute("PRAGMA table_info(phase_outputs)")
cols = {row[1] for row in cursor.fetchall()}
if "finish_reason" not in cols:
    cursor.execute("ALTER TABLE phase_outputs ADD COLUMN finish_reason TEXT")
if "attempt_number" not in cols:
    cursor.execute("ALTER TABLE phase_outputs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1")
```

In `_stream_llm_to_queue`:
- Capture `response.choices[0].finish_reason` from the LiteLLM response. Store as `None` when absent (Ollama streaming).
- Pass `attempt_number=current_attempt` (1-indexed retry counter) to `record_phase_output`.

`record_phase_output` signature gains two optional kwargs: `finish_reason: str | None = None`, `attempt_number: int = 1`.

`GET /runs/{run_id}` response includes both fields per phase output entry.

### Task F: Token Budget Enforcement Before Phase 2

In `orchestrator.py`, before constructing the Phase 2 prompt for each seat:
1. Look up `provider_caps.caps_for(seat.model).context_window` (default 4096 if unknown).
2. Estimate token count of the Phase 1 output being injected (approx: `len(text) // 4`).
3. Reserve 600 tokens for instructions. If `estimated_tokens > context_window - 600`:
   - Truncate the Phase 1 text to fit (`max_chars = (context_window - 600) * 4`).
   - Log a warning: `f"[phase2] Truncated {seat.model} Phase 1 input: {original_len} → {truncated_len} chars"`.

Do NOT call summarizer here — truncation only (keep Phase 2 fast).

### Task G: Chairman JSON Fallback Parser

In `orchestrator.py`, find `_chairman_decide` (or equivalent). After `json.loads` fails:

Stage 1 — strip markdown fences and retry:
```python
import re
stripped = re.sub(r"^```(?:json)?\n?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
result = json.loads(stripped)
```

Stage 2 — regex extraction if Stage 1 fails:
```python
verdict_match = re.search(r'"verdict"\s*:\s*"([^"]+)"', raw)
risk_match = re.search(r'"risk_score"\s*:\s*(\d+(?:\.\d+)?)', raw)
result = {
    "verdict": verdict_match.group(1) if verdict_match else "parse_failed",
    "risk_score": float(risk_match.group(1)) if risk_match else -1,
    "action_items": [],
    "consensus": "",
    "disputes": [],
    "_parse_tier": "regex_extracted"
}
```

Stage 3 — total failure returns degraded dict with `"_parse_tier": "parse_failed"`.

Log `_parse_tier` to `phase_outputs.finish_reason` for the chairman seat.

Test in `tests/test_orchestrator.py`: clean JSON, fenced JSON, partial JSON (verdict+risk only), total garbage — none raise; all return a dict with all required keys.

### Task H: WAL Mode Coverage in metrics_store.py

`run_store.py` applies WAL mode. `metrics_store.py` opens a separate SQLite connection without it.

Add a shared helper in `run_store.py`:
```python
def _db_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

Replace `sqlite3.connect(...)` in `metrics_store.py` with `from run_store import _db_connect; _db_connect(path)`.

### Task I: Health Check Endpoint

Add to `main.py`:
```python
@app.get("/health")
async def health():
    import httpx, sqlite3
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:
        pass
    db_ok = False
    try:
        conn = sqlite3.connect(RUN_DB_PATH, timeout=1)
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception:
        pass
    return {"status": "ok", "ollama": ollama_ok, "db": db_ok}
```

### Task J: Auth Boundary Startup Warning

In `main.py`, in the startup event (or top-level after `app = FastAPI()`):
```python
import os, warnings
_host = os.environ.get("COUNCIL_HOST", "127.0.0.1")
_api_key = os.environ.get("COUNCIL_API_KEY", "")
if _host not in ("127.0.0.1", "localhost") and not _api_key:
    warnings.warn(
        "WARNING: Council server binding to a non-localhost address with no COUNCIL_API_KEY set. "
        "All endpoints are unauthenticated. Do not expose this server on a public network.",
        stacklevel=2
    )
```

## Acceptance Criteria

- `./venv/bin/pytest tests/ -q` passes all tests (add new ones, don't break existing)
- `GET /runs/{run_id}` response includes a `phase=3` entry for completed runs
- `GET /runs/{run_id}` response includes `finish_reason` and `attempt_number` per phase output
- No `record_phase_output` call inside a retry/loop body
- `redact_config` applied before every `json.dumps` of a roster or config dict
- Unknown model fallback returns all-False capability flags
- Chairman JSON parse never raises — always returns dict with all required keys
- Phase 2 prompts never exceed target model context window
- `GET /health` returns 200 with `ollama` and `db` bool fields
- `metrics_store.py` uses shared `_db_connect` helper (WAL mode)

## Do Not

- Break existing API response shapes
- Add cloud LLM calls
- Refactor anything outside these specific fixes
- Use summarizer in the Phase 2 token budget truncation (truncate only)
