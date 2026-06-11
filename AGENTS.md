# LLM Council — Codex Project Context

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
| Frontend | Single `static/index.html` (vanilla JS, cyberpunk UI) |
| Python | 3.13 tested, 3.12+ intended |

## Key Files

| File | Role |
|---|---|
| `orchestrator.py` | 3-phase pipeline, streaming, retry logic |
| `main.py` | FastAPI app, all HTTP endpoints |
| `router_agent.py` | Dynamic Swarm — LLM generates roster personas |
| `smart_phase.py` | MiniLM cosine similarity → skip Phase 2 if unanimous |
| `memory_store.py` | SQLite+vector memory store (replaced memory_graph.py) |
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
| `static/index.html` | Full frontend (~1920 lines, HTML/CSS/JS co-located) |

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
        ▼ smart_phase: cosine sim > 0.88? skip Phase 2
        │
[Phase 2] Cross-Review (each seat critiques others)
  Seat A reviews B, C
  Seat B reviews A, C     ◄── parallel
  Seat C reviews A, B
        │
        ▼
[Phase 3] Chairman Synthesis
  All analyses + reviews → single chairman model → ChairmanDecision JSON
  (verdict, risk_score, action_items, consensus, disputes)
        │
        ▼
SSE stream to UI + RunStore write + Memory extract (async)
```

## Database Schema (council_runs.db)

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
| `COUNCIL_CORS_ORIGINS` | `localhost:8765` | Allowed CORS origins — empty = localhost only, `*` = wildcard |
| `COUNCIL_ENABLE_PYTHON_TOOL` | `true` | Enable Python REPL tool for cloud models |
| `COUNCIL_METRICS_FILE` | `council_metrics.jsonl` | JSONL metrics output path |
| `COUNCIL_MAX_RECENT_RUNS` | `20` | Max runs returned by metrics endpoint |
| `COUNCIL_BOOTSTRAP_LOCAL_MODELS` | `false` | Auto-pull Ollama models on startup |

## Test Suite

Run: `./venv/bin/pytest tests/ -q`
Current: 30 tests passing. Tests use unittest stubs for litellm and httpx.

## What NOT To Do

- Do not add cloud LLM calls to any default flow
- Do not load the SentenceTransformer model more than once — use the shared singleton
- Do not write keys or tokens to disk or logs — `redact_config()` must cover all serialization boundaries
- Do not use `os.walk` + AST parsing in `blast_radius.py` — import from `project_graph.py`
- Do not add new columns to SQLite tables without a migration path
- Do not grow `index.html` further before extracting config to `presets.json`
- `memory_graph.py` has been deleted — use `memory_store.py` exclusively
