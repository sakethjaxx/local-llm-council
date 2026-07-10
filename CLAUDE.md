# LLM Council — Claude Project Context

## What This Is

Local-first multi-model AI council. User submits a topic + optional file attachments. A roster of LLM personas (via Ollama or cloud providers) runs a 3-phase pipeline: independent analysis → peer cross-review → chairman synthesis. Output streams live to a web UI. Zero recurring cost in the default path.

## Stack

| Layer | Tech |
|---|---|
| API server | FastAPI + uvicorn |
| LLM calls | LiteLLM (Ollama-first, cloud opt-in) |
| Local models | Ollama |
| Embeddings | `sentence-transformers` `all-MiniLM-L6-v2` |
| Persistence | SQLite (`council_runs.db`) |
| Streaming | Server-Sent Events (SSE) |
| Frontend | `src/llm_council/web/static/index.html` shell + buildless ES modules in `src/llm_council/web/static/js/` + `src/llm_council/web/static/css/main.css` |
| Python | 3.13 tested, 3.12+ intended |

## Key Files

| File | Role |
|---|---|
| `src/llm_council/orchestrator.py` | 3-phase pipeline, streaming, retry logic |
| `src/llm_council/main.py` | FastAPI app, all HTTP endpoints |
| `router_agent.py` | Dynamic Swarm — LLM generates roster personas |
| `smart_phase.py` | Stance-based consensus gate (STANCE line, synonym-tolerant, zero-temp fallback classify on miss) → skip Phase 2 if unanimous; cosine sim kept as divergence telemetry |
| `confidence.py` | Pure trust functions: grounding enforcement (strip unattributed chairman points below 0.5 ratio) + Council Confidence 0-100 (single-model council capped at 45) |
| `memory_store.py` | SQLite triple store with vector retrieval (replaced `memory_graph.py`) |
| `provider_caps.py` | Model capability registry — vision, context window, cost, response_format |
| `run_store.py` | SQLite persistence for runs, phase outputs, feedback |
| `metrics_store.py` | JSONL metrics (latency, status) — thin wrapper over run_store eventually |
| `hardware_detect.py` | RAM-tier-based default roster builder |
| `io_parser.py` | File upload parsing: md/json/text/pdf/code/images |
| `summarizer.py` | Chunk + map-reduce for inputs > context window |
| `search_engine.py` | DuckDuckGo search for dispute resolution |
| `blast_radius.py` | Reverse-dep analysis for changed files |
| `project_graph.py` | AST-based project dependency graph |
| `src/llm_council/demo_catalog.py` | Preset council configurations for demos (source of truth: `src/llm_council/resources/presets.json`) |
| `src/llm_council/resources/demo_samples/` | Sample input files for demo presets |
| `src/llm_council/web/static/index.html` | Frontend markup shell only |
| `src/llm_council/web/static/js/` | ES modules: `app.js` (boot+delegation), `state.js`, `events.js` (SSE dispatch), `render.js` (stances/gate/verdict/confidence), `config-panel.js`, `run.js`, `chat.js`, `replay.js`, `graphs.js`, `api.js`, `utils.js` |
| `src/llm_council/web/static/css/main.css` | All styles |
| `tests/eval/live_validation.py` | Live 3-scenario validation against real Ollama (STANCE emission, gate, rebuttal, grounding) |

## Architecture: 3-Phase Pipeline

```
User Input (topic + attachments)
        │
        ▼
[Phase 0 — optional] Memory context injection (historical triples)
        │
        ▼
[Phase 1] Parallel Analysis
  Seat A ──┐
  Seat B ──┼──► asyncio.gather() → N independent analyses
  Seat C ──┘
        │
        ▼ smart_phase: all STANCE lines agree? skip Phase 2 (explainable decision)
        │
[Phase 2] Cross-Review (each seat critiques others)
  Seat A reviews B, C
  Seat B reviews A, C     ◄── parallel
  Seat C reviews A, B
        │
        ▼ stances split? one bounded rebuttal round (concede or defend)
        │
        ▼
[Phase 3] Chairman Synthesis
  All analyses + reviews (+rebuttals) → single chairman model → ChairmanDecision JSON
  (verdict, risk_score, action_items, consensus, disputes)
  grounding enforced (unattributed points stripped) → chairman_verdict event
  council_confidence 0-100 event (diversity/agreement/grounding/parse; clones capped 45)
        │
        ▼
SSE stream to UI + RunStore write (incl. confidence metrics) + Memory extract (async)
```

## Database Schema (council_runs.db)

```sql
runs(run_id PK, started_at, finished_at, status, topic, roster_json, fingerprint_hash,
     deep_debate, smart_phase_score, parse_tier, phase1_divergence, specificity_score,
     grounding_ratio, council_confidence, stance_summary, error)
phase_outputs(run_id, phase, member_id, output, tokens_in, tokens_out, latency_ms, finish_reason, attempt_number)
run_feedback(run_id, action_index, rating, note, rated_at)
skills(id PK, name, body, domain, source_run, confidence, used_count, created_at, embedding)
```

## Free-of-Cost Mandate

Every default flow runs on Ollama + local Python libraries. Cloud LLMs are opt-in (user provides key). No paid APIs in the required path. This is the project's identity — do not violate it.

## Current MVP Phase

Building Phase 1 + 1.5 + 2 (see `docs/SPEC.md`). See `src/llm_council/resources/agent_prompts/` for per-phase implementation briefs.

## Coding Conventions

- Async everywhere for LLM calls — `await litellm.acompletion(...)`
- SQLite: always use WAL mode (`PRAGMA journal_mode=WAL`) on first connection
- No duplicate dependency-graph code — `blast_radius.py` must consume `project_graph.py`
- Embedder is a shared singleton — import from `embeddings.py` (not inline in each module)
- `redact_config()` from `provider_caps.py` must be applied before any JSON serialization of rosters or configs
- Tests go in `tests/` — pytest, no mocking of the DB (use in-memory SQLite `:memory:`)
- `conftest.py` adds project root to `sys.path` (already present)

## Environment Variables

| Var | Default | Purpose |
|---|---|---|
| `COUNCIL_CORS_ORIGINS` | `*` | Allowed CORS origins |
| `COUNCIL_ENABLE_PYTHON_TOOL` | `true` | Enable Python REPL tool for cloud models |
| `COUNCIL_METRICS_FILE` | `council_metrics.jsonl` | JSONL metrics output path |
| `COUNCIL_MAX_RECENT_RUNS` | `20` | Max runs returned by metrics endpoint |
| `COUNCIL_BOOTSTRAP_LOCAL_MODELS` | `false` | Auto-pull Ollama models on startup |

## Test Suite

Run: `./venv/bin/pytest tests/ -q --ignore=tests/eval` (Windows: `./venv/Scripts/python.exe -m pytest ...`)
Current: 128 tests passing. Tests use unittest stubs for litellm and httpx.
Live validation (needs Ollama): `python tests/eval/live_validation.py` — see `docs/REALITY_REPORT.md`.

## What NOT To Do

- Do not add cloud LLM calls to any default flow
- Do not load the SentenceTransformer model more than once — use the shared singleton
- Do not write keys or tokens to disk or logs — `redact_config()` must cover all serialization boundaries
- Do not use `os.walk` + AST parsing in `blast_radius.py` — import from `project_graph.py`
- Do not add new columns to SQLite tables without a migration path (`migrations/` + `run_store._apply_migration`)
- Do not render the chairman verdict in the UI by parsing `member_done` text — use the grounding-enforced `chairman_verdict` event
- Do not add more rebuttal rounds — the debate is bounded to one by design
- Do not mutate event dicts after yielding them from the orchestrator — yield copies
- Do not weaken the stance fail-safe: an unmappable verdict must resolve to None → debate
