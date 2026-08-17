# Architecture — LLM Council

## Purpose and boundaries

LLM Council is a local-first decision/review application. A FastAPI server receives a topic and optional attachments, runs a roster of LLM personas, streams progress over SSE, and stores runs locally. Ollama is the default provider; cloud providers are optional and require request-scoped keys.

## Main flow

```text
Browser → POST /council/stream → main.py → CouncilOrchestrator
       → Phase 0: memory and skill context (optional)
       → Phase 1: parallel member analyses
       → Phase 3: chairman synthesis
       → SSE events + SQLite run persistence
       → background memory/skill extraction
```

Deep Debate is opt-in. When enabled, Phase 2 cross-review sits between Phase 1 and chairman synthesis; `smart_phase.py` may skip it when analyses are sufficiently unanimous.

## Ownership

| Area | Primary modules | Rule |
|---|---|---|
| HTTP/SSE boundary | `main.py` | Validate requests, enforce boundaries, route work; avoid business logic. |
| Council lifecycle | `orchestrator.py` | Streaming, retries, phases, token budgets, persistence coordination. |
| Model capabilities | `provider_caps.py`, `cloud_keys.py` | One source of truth for model/provider behavior and scoped keys. |
| Local model setup | `hardware_detect.py`, `ollama_manager.py` | Hardware-aware roster selection, model catalog/status, and pulls. |
| Input processing | `io_parser.py`, `summarizer.py` | Parse safe files, cap inputs, opt-in remote fetch only. |
| Durable state | `run_store.py`, `memory_store.py`, `skill_registry.py`, `metrics_store.py` | SQLite/JSONL persistence, no raw secret serialization. |
| Embeddings | `embeddings.py` | Shared singleton only. |
| Project analysis | `project_graph.py`, `blast_radius.py`, `project_fingerprint.py` | `blast_radius` consumes `project_graph`; do not duplicate AST walking. |
| Browser UI | `static/` | Vanilla DOM/SSE; escape LLM-controlled text before `innerHTML`. |

## State and concurrency

- Store singletons are constructed at import time from `COUNCIL_DB_PATH`.
- `tests/conftest.py` must set test database environment variables before test-module imports.
- SQLite connections are created through `db.db_connect()` to enforce WAL, foreign keys, and a busy timeout.
- `RunStore` applies idempotent, versioned migrations and records them in `schema_migrations`; add a migration before depending on a new schema column.
- LLM calls are async. Bounded member concurrency uses `COUNCIL_MAX_PARALLEL_MEMBERS`.
- Roster selection offers `auto`, `shared`, `diverse`, and `mixed` strategies. `mixed` runs small Phase-1 analysts concurrently, then reloads the strongest single chairman that fits the RAM budget for Phase 3. The browser exposes the same RAM estimate for a user-selected analyst combination; it is guidance, not a GPU/throughput benchmark.
- `runtime_defaults.py` configures LiteLLM to use its bundled pricing map before any LiteLLM import, so normal server boot does not fetch GitHub metadata.
- Background memory/skill maintenance must not prevent clean shutdown.

## Important contracts

- Empty search, memory, and skill contexts return `""`, not `None`.
- SSE events include `phase_start`, `member_thinking`, `member_token`, `member_done`, `warning`, `error`, `shutdown`, and `done`.
- Route paths supplied by users must pass `_confine_to_project_root()` when `COUNCIL_PROJECT_ROOT` is configured.
- `run_store`, `memory_store`, and `skill_registry` share the same database path.
