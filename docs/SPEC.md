# LLM Council — MVP Specification (Phase 1 + 1.5 + 2)

> Constraint: every feature runs at zero recurring cost. Ollama-first. Cloud is opt-in.

---

## Status

| Symbol | Meaning |
|---|---|
| ✅ | Done, wired, tested |
| 🟡 | Code exists, incomplete |
| 🔨 | To build in this MVP |

---

## Phase 1 — Foundation Completion

### P1-1: Run Store Endpoints ✅ (wired, needs validation)

`main.py` exposes:

- `GET /runs` — list runs, optional `?fingerprint_hash=` filter, `?limit=` cap
- `GET /runs/{run_id}` — full run with all phase outputs
- `DELETE /runs/{run_id}` — hard delete, cascade to phase_outputs + run_feedback
- `POST /runs/{run_id}/feedback` — record `{action_index, rating, note}` per action item

Acceptance:
- All 4 endpoints return 404 with `{"detail": "run not found"}` for unknown IDs
- DELETE cascades via SQLite FK
- Feedback `rating` must be one of `thumbs_up`, `thumbs_down`, `ignored` — validate in `FeedbackRequest` with a Pydantic `Literal` or `Enum`; return 422 on invalid value
- Feedback endpoint idempotent: second POST on same `(run_id, action_index)` overwrites via `INSERT OR REPLACE`

### P1-2: Phase 3 Chairman Output Recorded ✅ (verify)

`_chairman_decide` calls `_stream_llm_to_queue` with `run_id=run_id, phase=3, member_id="chairman"`. Phase 3 is already recorded via the same path as Phase 1 and Phase 2.

Action: verify by running a council and confirming `GET /runs/{run_id}` includes a `phase=3` entry. Add assertion to `test_run_store.py` if not already covered.

Acceptance:
- After a completed run, `GET /runs/{run_id}` includes a phase 3 entry with `member_id="chairman"`
- `tokens_in`, `tokens_out`, `latency_ms` populated (or `null` for Ollama which omits usage)

### P1-3: RunStore Double-Write on Python Tool Recursive Call 🔨

`_stream_llm_to_queue` calls `record_phase_output` in the success path (before `break`). Retry-only calls do NOT double-write. However, when the Python REPL tool fires, `_stream_llm_to_queue` is called recursively (line ~233) with the same `run_id, phase, member_id` — this second call also triggers `record_phase_output`, violating the PK constraint.

Fix: pass `run_id=None` on the recursive tool-followup call (the full text is already captured by the parent call, which aggregates both texts at line 243 before returning).

Acceptance:
- A council run that triggers the Python tool produces exactly one `phase_outputs` row per seat
- Normal (no-tool) runs unaffected

### P1-4: Config Redaction at All Boundaries 🔨

`provider_caps.redact_config(d)` strips keys matching `*api_key*`, `*token*`, `*secret*` (case-insensitive, nested).

Apply at:
- `run_store.begin_run` — `roster_json` before INSERT
- `metrics_store` — any config dict logged to JSONL
- Any future export endpoint

Acceptance:
- `test_redaction.py` covers: nested dicts, lists of dicts, mixed key names, value types (str/int/None)
- Grep confirms no `json.dump` of a raw roster config without `redact_config` in the call chain

### P1-5: Safe Unknown-Model Fallback 🔨

`provider_caps.caps_for(model)` currently returns `response_format=True` for unknown cloud models. Must default to `response_format=False`, `vision=False`.

Acceptance:
- `test_provider_caps.py` asserts unknown model fallback is all-False
- Existing known-model tests still pass

### P1-6: LLM Call Observability — finish_reason + attempt_number 🔨

`phase_outputs` schema is missing two fields critical for diagnosing silent quality degradation:

- `finish_reason TEXT` — LiteLLM surfaces `stop`, `length`, `tool_calls`, `content_filter`. `length` = model was truncated mid-response = silent quality loss.
- `attempt_number INTEGER` — which retry succeeded. If a seat routinely succeeds on attempt 2+, the model or prompt needs attention.

Migration:
```sql
ALTER TABLE phase_outputs ADD COLUMN finish_reason TEXT;
ALTER TABLE phase_outputs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1;
```

Add migration script `migrations/001_add_observability_columns.sql`. Apply on first connection if columns absent.

Acceptance:
- `finish_reason` populated from `response.choices[0].finish_reason` (or `null` for Ollama streaming where it is absent)
- `attempt_number` = 1 for first-try successes, 2+ for retries
- `GET /runs/{run_id}` response includes both fields per phase output
- `test_run_store.py` asserts fields present on a stubbed run

### P1-7: Token Budget Enforcement Before Phase 2 Input 🔨

Phase 1 outputs fed into Phase 2 prompts can silently overflow local model context windows (4K–8K for most 7B models). Model truncates without warning. The reviewer never saw the analysis it's critiquing.

Fix in `orchestrator.py` before constructing Phase 2 prompt:
1. Look up `provider_caps.caps_for(seat.model).context_window`
2. Estimate tokens used by system prompt + instructions (~500 tokens reserved)
3. If Phase 1 output for a member exceeds `context_window - 500`, call `summarizer.summarize(text, max_chars=...)` to reduce it
4. Log a warning with `finish_reason="length_truncated_by_orchestrator"` in phase_outputs for that seat

Acceptance:
- A Phase 2 prompt never exceeds the target seat's registered context window
- Truncation is logged (not silent)
- `test_orchestrator.py` asserts truncation fires when a synthetic 10K-char Phase 1 output is fed to a 4K-window model

### P1-8: Chairman JSON Fallback Parser 🔨

`_chairman_decide` relies on the model returning a valid JSON object. Small local models (3B–7B) frequently produce JSON with trailing prose, partial escapes, or wrapped in markdown fences. On parse failure the verdict is silently lost.

Add a two-stage fallback after `json.loads` fails:

1. Strip markdown fences, retry `json.loads`
2. Regex-extract `verdict`, `risk_score`, `action_items` individually and reconstruct a minimal valid dict
3. If stage 2 also fails, return a degraded dict: `{"verdict": "parse_failed", "risk_score": -1, "action_items": [], "consensus": "", "disputes": []}`

Log the fallback tier used (`parse_ok` / `fence_stripped` / `regex_extracted` / `parse_failed`) in `phase_outputs.finish_reason`.

Acceptance:
- `test_orchestrator.py` covers: clean JSON, fenced JSON, partial JSON with only verdict+risk_score, total garbage
- `parse_failed` path never raises; always returns a dict with all required keys

---

## Phase 1.5 — Quick Wins

### P1.5-1: Shared Embedder Singleton 🔨

`smart_phase.py` loads `SentenceTransformer('all-MiniLM-L6-v2')` inline. This will conflict with Phase 2 (memory + skill registry also need embeddings).

Create `embeddings.py`:
```python
_embedder = None

def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedder
```

Refactor `smart_phase.py` to call `from embeddings import get_embedder`.

Acceptance:
- `import embeddings; e1 = embeddings.get_embedder(); e2 = embeddings.get_embedder(); assert e1 is e2`
- `smart_phase.py` has no inline SentenceTransformer import

### P1.5-2: Presets Extracted to `presets.json` 🔨

Demo presets, seat templates, and persona defaults currently live in `demo_catalog.py` (Python) and partially in `static/index.html` (inline JS). Extract to `presets.json` served via `GET /config/presets`.

`presets.json` structure:
```json
{
  "version": "1",
  "presets": [
    {
      "id": "fast_triage",
      "label": "Fast Triage",
      "description": "...",
      "seats": [...],
      "topic_placeholder": "...",
      "sample_files": [...]
    }
  ],
  "default_personas": {...}
}
```

`demo_catalog.py` becomes a thin loader that reads `presets.json`.
`GET /config/presets` returns the parsed JSON.
`index.html` fetches `/config/presets` on load instead of hardcoding.

Acceptance:
- Adding a new preset requires only editing `presets.json`, not Python or JS
- Existing demo presets render identically in the UI
- `test_main.py` asserts `/config/presets` returns 200 with a non-empty `presets` list

### P1.5-3: Blast Radius Uses Project Graph 🔨

`blast_radius.py` duplicates `os.walk` + AST parsing from `project_graph.py`.

Refactor: `blast_radius.py` calls `project_graph.build_project_graph(root)` and computes reverse deps from the returned graph object. Remove duplicate walk/parse code.

Acceptance:
- Existing `blast_radius` JSON output shape preserved
- No `ast.parse` or `os.walk` in `blast_radius.py` after refactor

### P1.5-4: Phase Prompts Externalized to Versioned Files 🔨

Phase 1 / 2 / 3 system prompts are hardcoded strings in `orchestrator.py`. A single bad edit silently degrades every run with no diff history.

Extract to `agent_prompts/phase_prompts/`:
```
phase1_analyze.txt
phase2_review.txt
phase3_chairman.txt
```

Load at module import time:
```python
def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "agent_prompts" / "phase_prompts" / name
    return path.read_text()
```

Acceptance:
- Adding/editing a prompt requires only editing the `.txt` file
- `orchestrator.py` has no multi-line prompt string literals
- Prompt load failures raise `FileNotFoundError` at startup (fail fast, not at request time)

### P1.5-5: Smart Phase Similarity Score Logged 🔨

`smart_phase.py` computes pairwise cosine similarity between Phase 1 outputs to decide whether to skip Phase 2. The 0.88 threshold is empirical but unverifiable — no audit trail exists.

Log the similarity score for each run:
- Add `smart_phase_score REAL` column to `runs` table (nullable)
- `smart_phase.should_skip()` returns `(bool, float)` — the bool is the skip decision, the float is the mean pairwise similarity
- `orchestrator.py` writes the score to `runs.smart_phase_score`

Acceptance:
- `GET /runs/{run_id}` includes `smart_phase_score` in the response
- `test_smart_phase.py` asserts the return type is `(bool, float)`
- `test_run_store.py` asserts column present after migration

---

## Phase 2 — Memory Becomes Knowledge

### P2-1: Memory Store Migrated to SQLite + Vectors 🔨

Replace `memory_graph.py` (NetworkX + JSON) with a SQLite-backed store.

New schema (add to `council_runs.db`):
```sql
CREATE TABLE IF NOT EXISTS memory_triples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject     TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object      TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,
    reinforced  INTEGER NOT NULL DEFAULT 1,
    contradicted INTEGER NOT NULL DEFAULT 0,
    last_seen   REAL NOT NULL,
    created_at  REAL NOT NULL,
    embedding   BLOB  -- numpy float32 array, serialized
);
CREATE INDEX IF NOT EXISTS idx_memory_subject ON memory_triples(subject);
CREATE INDEX IF NOT EXISTS idx_memory_last_seen ON memory_triples(last_seen DESC);
```

Retrieval query: embed the **synthesized topic string** (not keyword match) via `get_embedder()`, then cosine top-K against stored embeddings. This ensures "microservices design" and "service mesh architecture" share memory.

Confidence decay on retrieval: `confidence *= 0.99 ** days_since_last_seen`.

Acceptance:
- `council_memory.json` no longer written (or ignored if exists)
- `GET /council/memory` still works, returns triples from SQLite
- Retrieval returns semantically related triples even when keywords differ
- Cold start (empty DB) returns empty context without error
- Background embedding rebuild on startup if `embedding IS NULL` rows exist

### P2-2: Memory Extraction Uses Separate Small Model 🔨

Currently extraction uses the same chairman model (circular). Use a configurable `COUNCIL_MEMORY_MODEL` env var (default: smallest installed Ollama model). Add quality gate: only extract when `run_feedback` has at least one `thumbs_up` OR chairman `risk_score <= 3`.

Acceptance:
- `COUNCIL_MEMORY_MODEL` env var controls extraction model
- No extraction triggered for runs with all-unrated feedback and `risk_score > 3`

### P2-3: Project Fingerprint 🔨

`project_fingerprint.py` — pure heuristic, no LLM.

Detects:
- Language(s): Python / JS / TS / Go / Rust / Java (by file extension counts)
- Framework hints: `package.json`, `requirements.txt`, `Cargo.toml`, `go.mod`, `pom.xml`
- Domain hints: keywords in README / top-level files (`api`, `ml`, `infra`, `frontend`)
- Returns a short dict + a stable SHA-256 hash of the detected fingerprint

Used by `run_store` as `fingerprint_hash` to group related runs.

Acceptance:
- Given `demo_samples/` dir, fingerprint returns non-empty language + domain
- Hash is deterministic: same dir → same hash
- `tests/test_fingerprint.py` covers empty dir, Python-only dir, mixed dir

### P2-4: Skill Registry 🔨

`skill_registry.py` — extract reusable analysis patterns from past runs, inject into Phase 1 prompts.

**Store schema:**
```sql
CREATE TABLE IF NOT EXISTS skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    body        TEXT NOT NULL,
    domain      TEXT,
    source_run  TEXT REFERENCES runs(run_id),
    confidence  REAL NOT NULL DEFAULT 0.5,
    used_count  INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    embedding   BLOB
);
```

**Extraction flow:**
1. After run completes with quality gate (thumbs_up OR risk_score ≤ 3)
2. Prompt chairman model: "What reusable analysis skill does this verdict demonstrate? One short paragraph."
3. Sanity check: re-prompt with skill + verdict, ask "does this skill follow from this verdict? yes/no" — discard on "no"
4. Embed skill body, store in `skills` table
5. Cap: max 3 skills extracted per run

**Injection flow:**
1. On council start, retrieve top-3 skills by cosine similarity to topic embedding
2. Inject into Phase 1 system prompt as "COUNCIL SKILLS (apply if relevant): ..."

Acceptance:
- Skills only extracted when quality gate passes
- Sanity check discards hallucinated skills
- Phase 1 prompts include skill block when relevant skills exist
- `GET /skills` endpoint returns stored skills with confidence + used_count
- `tests/test_skill_registry.py` covers extraction, sanity gate, injection, retrieval

### P2-5: Eval Harness — 5 Golden Topics 🔨

No tests currently verify output quality — only plumbing. Without a quality baseline, regression is invisible.

Create `tests/eval/`:
```
golden_topics.json        # 5 fixed topics + reference verdicts
run_eval.py               # drives orchestrator, scores output
```

Scoring: cosine similarity (MiniLM) between chairman verdict and reference verdict. Score ≥ 0.70 = pass. Log per-topic score and mean to `eval_results.jsonl`.

Golden topics must cover: code review, architecture decision, ethics/tradeoff, factual dispute, data pipeline design.

Acceptance:
- `python tests/eval/run_eval.py` runs all 5 topics end-to-end (requires Ollama running)
- Mean score logged; below 0.60 prints a warning
- Eval is NOT in the default pytest suite (slow); run separately with `--eval` flag or standalone script
- Smart Phase skip rate across golden runs logged — if >40% skip Phase 2, threshold needs review

### P2-6: Model Routing by Capability Strengths 🔨

`provider_caps.ModelCaps` has no `strengths` field. `router_agent.py` generates personas but assigns models without knowing what tasks each model excels at. A code-review persona assigned to a weak-reasoning model silently underperforms.

Add to `ModelCaps`:
```python
strengths: list[str] = []  # e.g. ["code", "reasoning", "math", "multilingual"]
tool_use: bool = False      # model supports function/tool calling
```

Populate for known models in the registry.

In `router_agent.py`: when assigning a model to a persona, prefer models where `task_type in model.strengths`. `task_type` inferred from persona description keywords.

Acceptance:
- `test_provider_caps.py` asserts `strengths` and `tool_use` present on all known model entries
- `router_agent.py` passes a `strengths`-aware filter when selecting model for each persona
- Fallback: if no model matches task strengths, assign best available (no crash)

---

## Non-Goals for This MVP

- Multi-user authentication
- Cloud-hosted vector DB
- Mobile/responsive UI
- Paid LLM in any default path
- Fine-tune dataset export
- Cron-driven scheduled runs
- Counterfactual replay
- Benchmark mode
- Per-member stance memory (after Phase 2 ships)
- Auth/RBAC (known gap — document in README for any non-localhost deployment)
