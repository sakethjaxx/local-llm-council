# LLM Council — Claude Project Context

## What This Is

Local-first multi-model AI council. User submits a topic + optional file attachments. A roster of LLM personas (via Ollama or cloud providers) runs independent analysis → chairman synthesis by default; optional Deep Debate adds peer cross-review. Output streams live to a web UI. Zero recurring cost in the default path.

## Stack

| Layer | Tech |
|---|---|
| API server | FastAPI + uvicorn |
| LLM calls | LiteLLM (Ollama-first, cloud opt-in) |
| Local models | Ollama |
| Embeddings | `sentence-transformers` `all-MiniLM-L6-v2` |
| Persistence | SQLite (`data/council_runs.db`) |
| Streaming | Server-Sent Events (SSE) |
| Frontend | `static/index.html` + `static/app.js` + `static/style.css` (vanilla JS) |
| Python | 3.13 tested, 3.12+ intended |

## Key Files

| File | Role |
|---|---|
| `orchestrator.py` | Council pipeline, streaming, retry logic |
| `main.py` | FastAPI app, all HTTP endpoints |
| `router_agent.py` | Dynamic Swarm — LLM generates roster personas |
| `smart_phase.py` | MiniLM cosine similarity → skip Phase 2 if unanimous (Deep Debate only) |
| `memory_store.py` | SQLite-backed triple store with vector retrieval |
| `provider_caps.py` | Model capability registry — vision, context window, cost, response_format |
| `run_store.py` | SQLite persistence for runs, phase outputs, feedback |
| `metrics_store.py` | JSONL metrics (latency, status) — thin wrapper over run_store eventually |
| `hardware_detect.py` | RAM-tier-based default roster builder |
| `io_parser.py` | File upload parsing: md/json/text/pdf/code/images |
| `summarizer.py` | Chunk + map-reduce for inputs > context window |
| `search_engine.py` | DuckDuckGo search for dispute resolution |
| `blast_radius.py` | Reverse-dep analysis for changed files |
| `project_graph.py` | AST-based project dependency graph |
| `demo_catalog.py` | Preset council configurations for demos |
| `demo_samples/` | Sample input files for demo presets |
| `static/index.html` / `static/app.js` / `static/style.css` | Frontend markup, behaviour, and styles |

## Architecture: Default Two-Phase Pipeline

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
        ▼
[Phase 3] Chairman Synthesis
  All analyses → single chairman model → ChairmanDecision JSON
  (verdict, risk_score, action_items, consensus, disputes)
        │
        ▼
SSE stream to UI + RunStore write + Memory extract (async)
```

Deep Debate is off by default. When enabled, the optional Phase 2 cross-review runs between
analysis and chairman synthesis; `smart_phase.py` can then skip it for sufficiently unanimous
analyses. It does not execute in a default run.

## Database Schema (data/council_runs.db)

```sql
runs(run_id PK, started_at, finished_at, status, topic, roster_json, fingerprint_hash, deep_debate, error)
phase_outputs(run_id, phase, member_id, output, tokens_in, tokens_out, latency_ms)
run_feedback(run_id, action_index, rating, note, rated_at)
```

## Free-of-Cost Mandate

Every default flow runs on Ollama + local Python libraries. Cloud LLMs are opt-in (user provides key). No paid APIs in the required path. This is the project's identity — do not violate it.

## Current MVP Phase

Building Phase 1 + 1.5 + 2 (see `docs/SPEC.md`). See `agent_prompts/` for per-phase implementation briefs.

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
| `COUNCIL_DB_PATH` | `data/council_runs.db` | SQLite run, skill, and memory database path |
| `COUNCIL_HOST` | `127.0.0.1` | Server bind host |
| `COUNCIL_PORT` | `8765` | Server port |
| `COUNCIL_API_KEY` | empty | Required on non-localhost binds; protects endpoints when set |
| `COUNCIL_CORS_ORIGINS` | localhost allowlist | Comma-separated allowed origins; `*` is opt-in |
| `COUNCIL_PROJECT_ROOT` | unset | Confines local project paths to this directory tree |
| `COUNCIL_ALLOW_URL_FETCH` | `false` | Permit remote URL extraction from submitted text |
| `COUNCIL_ENABLE_WEB_SEARCH` | `false` | Permit DuckDuckGo dispute-resolution search |
| `COUNCIL_MAX_UPLOAD_MB` | `20` | Maximum uploaded-file size in MiB |
| `COUNCIL_MAX_FILES` | `10` | Maximum uploaded attachments |
| `COUNCIL_ENABLE_PYTHON_TOOL` | `false` | Enable Python REPL tool for cloud models |
| `COUNCIL_LLM_TIMEOUT` | `180` | Per-call LLM timeout in seconds |
| `COUNCIL_MAX_PARALLEL_MEMBERS` | `4` | Maximum concurrent member LLM calls |
| `COUNCIL_SMART_PHASE_THRESHOLD` | `0.88` | Similarity threshold used to skip Deep Debate Phase 2 |
| `COUNCIL_MEMORY_MODEL` | chairman extraction model | Override the model used for memory extraction |
| `COUNCIL_MEMORY_RELEVANCE_FLOOR` | `0.25` | Minimum score required to inject a memory triple |
| `COUNCIL_METRICS_FILE` | `data/council_metrics.jsonl` | JSONL metrics output path |
| `COUNCIL_MAX_RECENT_RUNS` | `200` | Max runs returned by metrics endpoint |
| `COUNCIL_BOOTSTRAP_LOCAL_MODELS` | `false` | Auto-pull Ollama models on startup |
| `COUNCIL_RELOAD` | `false` | Enable Uvicorn development reload |
| `COUNCIL_LOG_LEVEL` | `INFO` | Application log level |
| `COUNCIL_LOG_FORMAT` | `json` | Log format (`json` or plain text) |

## Test Suite

Run: `./venv/bin/pytest tests/ -q` (or `python3 -m pytest tests/ -q`)
Current: run `./venv/bin/pytest tests/ -q` for the authoritative count. Tests use unittest stubs for litellm and httpx.

## What NOT To Do

- Do not add cloud LLM calls to any default flow
- Do not load the SentenceTransformer model more than once — use the shared singleton
- Do not write keys or tokens to disk or logs — `redact_config()` must cover all serialization boundaries
- Do not use `os.walk` + AST parsing in `blast_radius.py` — import from `project_graph.py`
- Do not add new columns to SQLite tables without a migration path
- Do not add new frontend dependencies without a build/load-order plan
