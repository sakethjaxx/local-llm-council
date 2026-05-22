# LLM Council — Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (static/index.html)                                    │
│  ┌──────────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │ Seat Builder │  │ File Upload │  │ SSE Stream Consumer  │   │
│  └──────┬───────┘  └──────┬──────┘  └──────────┬───────────┘   │
│         └─────────────────┴──────────────────────┘             │
│                        POST /council/stream                     │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP + SSE
┌────────────────────────────▼────────────────────────────────────┐
│  FastAPI App (main.py)                                          │
│                                                                 │
│  /council/stream ──► CouncilOrchestrator.run()                  │
│  /council/chat   ──► CouncilOrchestrator.chat_with_member()     │
│  /runs/*         ──► RunStore                                   │
│  /metrics/*      ──► MetricsStore                               │
│  /config/presets ──► presets.json                               │
│  /skills         ──► SkillRegistry                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  CouncilOrchestrator (orchestrator.py)                          │
│                                                                 │
│  1. Input prep                                                  │
│     io_parser ──► parse attachments                             │
│     summarizer ──► chunk if > context_window/2                  │
│     memory_store ──► inject historical context                  │
│     skill_registry ──► inject relevant skills                   │
│                                                                 │
│  2. Roster resolution                                           │
│     router_agent (Dynamic Swarm) OR static preset               │
│     hardware_detect ──► default tier if no roster given         │
│     provider_caps ──► capability check per seat                 │
│                                                                 │
│  3. Phase execution                                             │
│     Phase 1: asyncio.gather(seat_A, seat_B, seat_C)             │
│     smart_phase: cosine_sim > 0.88 → skip Phase 2              │
│     Phase 2: asyncio.gather(review_A, review_B, review_C)       │
│     Phase 3: chairman_model → ChairmanDecision JSON             │
│                                                                 │
│  4. Post-run                                                    │
│     run_store.finish_run()                                      │
│     memory_store.extract_memory() [async, non-blocking]         │
│     skill_registry.extract_skills() [async, quality-gated]      │
└────────────────────────────┬────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────────┐
          │                  │                       │
          ▼                  ▼                       ▼
  ┌───────────────┐  ┌───────────────┐   ┌─────────────────────┐
  │  LiteLLM      │  │  SQLite       │   │  sentence-           │
  │  (LLM calls)  │  │  council_     │   │  transformers        │
  │               │  │  runs.db      │   │  (embeddings.py      │
  │  Ollama local │  │               │   │   singleton)         │
  │  Cloud opt-in │  │  runs         │   └─────────────────────┘
  └───────────────┘  │  phase_outputs│
                     │  run_feedback │
                     │  memory_triples│
                     │  skills       │
                     └───────────────┘
```

## Data Flow: Single Council Run

```
User submits topic + files
        │
        ├─► io_parser.parse_input()        → structured content dict
        ├─► summarizer (if oversized)       → compressed text
        ├─► memory_store.get_context()      → historical triple context
        ├─► skill_registry.get_skills()     → relevant skill injections
        │
        ├─► run_store.begin_run()           → run_id, status=running
        │
        ├─► [Phase 1] N parallel LLM calls
        │     each seat: system_prompt(persona) + context + topic + attachments
        │     streams chunks → SSE queue
        │
        ├─► smart_phase.check_unanimous_consensus()
        │     cosine pairwise similarity of Phase 1 outputs
        │     if avg > 0.88: skip Phase 2
        │
        ├─► [Phase 2] N parallel cross-reviews (if not skipped)
        │     each seat reads all OTHER Phase 1 analyses
        │     streams chunks → SSE queue
        │
        ├─► [Phase 3] Chairman call
        │     all Phase 1 + Phase 2 outputs as context
        │     response_format=ChairmanDecision JSON
        │     streams chunks → SSE queue
        │
        ├─► run_store.finish_run()          → status=completed
        │
        └─► (async background)
              memory_store.extract_memory() if quality gate
              skill_registry.extract_skills() if quality gate
              metrics_store.record()
```

## Component Responsibilities (Current vs Planned)

> **Current** = ships in main branch today. **Planned** = Phase 1.5 or Phase 2 work.

### `orchestrator.py` — Current
Single entry point for all council runs. Owns the phase lifecycle, retry logic, and SSE queue. Does not own storage — delegates to run_store.

### `main.py` — Current
HTTP boundary only. Routes requests, validates input shapes, returns responses. No business logic.

### `provider_caps.py` — Current
Single source of truth for model capabilities. Before any LLM call: check `caps_for(model)` to decide whether to use `response_format`, whether to pass images, what context window to expect.

### `run_store.py` — Current
All durable state about runs. SQLite with WAL mode. Owns the schema. No business logic.

### `memory_graph.py` — Current (being replaced in Phase 2)
NetworkX triple store, JSON-backed, keyword retrieval. Works but retrieval is lexical only.

### `smart_phase.py` — Current
MiniLM consensus check. Loads SentenceTransformer inline — will be refactored to use `embeddings.py` singleton in Phase 1.5.

### `embeddings.py` — Planned (Phase 1.5)
Singleton SentenceTransformer. Loaded once per process. Used by smart_phase, memory_store, skill_registry. Never instantiated inline in any other module.

### `memory_store.py` — Planned (Phase 2, replaces memory_graph.py)
SQLite-backed triple store with vector retrieval. Async-safe. Non-blocking writes (background task after run).

### `skill_registry.py` — Planned (Phase 2)
Extract → sanity-check → store → inject flow for analysis skills. Quality-gated. Confidence-scored.

### `project_fingerprint.py` — Planned (Phase 2)
Pure heuristic. No LLM. Detects tech stack + domain. Returns dict + stable SHA-256 hash. Used as `fingerprint_hash` on runs to group related sessions.

## SQLite Schema (Full, Post-Phase-2)

```sql
-- Core run tracking
runs(run_id PK, started_at, finished_at, status, topic,
     roster_json, fingerprint_hash, deep_debate, error)

-- Per-phase, per-seat outputs
phase_outputs(run_id FK, phase INT, member_id TEXT,
              output TEXT, tokens_in, tokens_out, latency_ms)

-- User ratings on action items
run_feedback(run_id FK, action_index INT, rating TEXT,
             note TEXT, rated_at REAL)

-- Memory triples with vector retrieval
memory_triples(id PK, subject, predicate, object,
               confidence REAL, reinforced INT, contradicted INT,
               last_seen REAL, created_at REAL, embedding BLOB)

-- Reusable analysis skills
skills(id PK, name, body, domain, source_run FK,
       confidence REAL, used_count INT, created_at REAL, embedding BLOB)
```

All tables: WAL mode. FK cascade on run delete.

## SSE Streaming Protocol

Server sends newline-delimited JSON events. Events from `main.py` arrive before the orchestrator yields; orchestrator events stream during the run.

```
# Pre-run (main.py)
data: {"type": "model_status", "ready": true, "missing": [], ...}
data: {"type": "warning", "message": "..."}   # Dynamic Swarm fallback, attachment warnings
data: {"type": "error", "message": "..."}     # missing models, hard failures

# Per-phase (orchestrator.py)
data: {"type": "phase_start", "phase": 1, "label": "Independent Analysis"}
data: {"type": "member_thinking", "member": "seat_0", "phase": 1, "meta": {model, label, ...}}
data: {"type": "member_token", "member": "seat_0", "chunk": "..."}
data: {"type": "member_done", "member": "seat_0", "full_text": "..."}

data: {"type": "phase_start", "phase": 2, "label": "Cross-Review"}
# ... same member_thinking / member_token / member_done pattern

data: {"type": "phase_start", "phase": 3, "label": "Chairman's Verdict"}
data: {"type": "member_thinking", "member": "chairman", "phase": 3, "meta": {...}}
data: {"type": "member_token", "member": "chairman", "chunk": "..."}
data: {"type": "member_done", "member": "chairman", "full_text": "..."}

data: {"type": "done"}
```

## Dependency Graph (Module Imports)

```
main.py
  └── orchestrator.py
        ├── embeddings.py          ← singleton (Phase 1.5)
        ├── smart_phase.py         ← uses embeddings.get_embedder()
        ├── memory_store.py        ← uses embeddings.get_embedder() (Phase 2)
        ├── skill_registry.py      ← uses embeddings.get_embedder() (Phase 2)
        ├── provider_caps.py
        ├── run_store.py
        ├── io_parser.py
        ├── summarizer.py
        ├── router_agent.py
        ├── hardware_detect.py
        ├── search_engine.py
        └── metrics_store.py

blast_radius.py
  └── project_graph.py             ← no more duplicate walk/AST (Phase 1.5)

project_fingerprint.py             ← no dependencies beyond stdlib (Phase 2)
```
