# LLM Council — Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (src/llm_council/web/static/index.html + JS modules)      │
│  app.js (boot + delegation) · state.js · events.js (SSE→render) │
│  render.js (stances/gate/verdict/confidence) · config-panel.js  │
│  run.js · chat.js · replay.js · graphs.js · api.js · utils.js   │
│  Styles: src/llm_council/web/static/css/main.css                                     │
│                        POST /council/stream                     │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP + SSE
┌────────────────────────────▼────────────────────────────────────┐
│  FastAPI App (src/llm_council/main.py)                                          │
│                                                                 │
│  /council/stream ──► CouncilOrchestrator.run()                  │
│  /council/chat   ──► CouncilOrchestrator.chat_with_member()     │
│  /runs/*         ──► RunStore                                   │
│  /metrics/*      ──► MetricsStore                               │
│  /config/presets -> resources/presets.json                               │
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
│       each analysis ends with a STANCE line                     │
│     smart_phase gate: compare STANCE verdicts (not text)        │
│       missing stance → one zero-temp fallback classify          │
│       unanimous → skip Phase 2 · split → debate + rebuttal      │
│     Phase 2: asyncio.gather(review_A, review_B, review_C)       │
│       + one bounded rebuttal round when stances split           │
│     Phase 3: chairman_model → ChairmanDecision JSON             │
│       grounding enforced: unattributed points stripped          │
│       council_confidence (0-100) computed and streamed          │
│                                                                 │
│  4. Post-run                                                    │
│     run_store.finish_run() + confidence/grounding/stances       │
│     memory_store.extract_memory() [async, non-blocking]         │
│     skill_registry.extract_skills() [async, quality-gated]      │
│     run feedback later adjusts skill confidence (rank loop)     │
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
        ├─► smart_phase.should_skip(analyses, member_models)
        │     extract STANCE line per member (regex, synonym-tolerant)
        │     missing stance → classify_stance_fallback (one zero-temp call)
        │     unanimous verdicts → skip Phase 2 (explained decision)
        │     any stance unrecoverable or MIXED → debate (fail-safe)
        │     cosine similarity kept only as divergence telemetry
        │
        ├─► [Phase 2] N parallel cross-reviews (if not skipped)
        │     each seat reads all OTHER Phase 1 analyses
        │     streams chunks → SSE queue
        │     if stances split: one bounded rebuttal round
        │       each seat concedes or defends (2-3 sentences + updated STANCE)
        │       rebuttal_result event reports convergence
        │
        ├─► [Phase 3] Chairman call
        │     all Phase 1 + Phase 2 (+rebuttals) as context
        │     response_format=ChairmanDecision JSON
        │     GROUNDING RULE: every consensus/dispute names its members
        │     enforce_grounding(): ratio < 0.5 → strip unattributed points
        │     council_confidence(): diversity+agreement+grounding+parse → 0-100
        │       (single-model council capped at 45)
        │
        ├─► run_store.finish_run()          → status=completed
        │     + update_confidence_metrics(grounding, confidence, stances)
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

### `smart_phase.py` — Current
Stance-based consensus gate. Compares explicit STANCE verdicts (PROCEED/HOLD/MIXED,
synonym-tolerant); a member that omits the line gets one cheap zero-temperature
fallback classification before the gate gives up. Unknown verdicts fail safe into
debate. Cosine similarity (shared embedder) survives only as divergence telemetry.

### `confidence.py` — Current
Pure trust functions: `enforce_grounding()` strips chairman consensus/dispute points
that name no real member (below a 0.5 ratio), and `council_confidence()` folds
diversity, agreement path, grounding, and parse tier into one 0-100 signal with a
hard cap of 45 for single-model councils.

### `embeddings.py` — Current
Singleton SentenceTransformer. Loaded once per process. Used by smart_phase, memory_store, skill_registry. Never instantiated inline in any other module.

### `memory_store.py` — Current (replaced memory_graph.py)
SQLite-backed triple store with vector retrieval. Async-safe. Non-blocking writes (background task after run).

### `skill_registry.py` — Current
Extract → sanity-check → store → inject flow for analysis skills. Quality-gated,
confidence-scored, and feedback-driven: run ratings adjust the source run's skill
confidence, which directly moves retrieval rank (similarity × confidence).

### `project_fingerprint.py` — Current
Pure heuristic. No LLM. Detects tech stack + domain. Returns dict + stable SHA-256 hash. Used as `fingerprint_hash` on runs to group related sessions.

## SQLite Schema (Full, Post-Phase-2)

```sql
-- Core run tracking (+ quality/trust columns via migrations 001-004)
runs(run_id PK, started_at, finished_at, status, topic,
     roster_json, fingerprint_hash, deep_debate,
     smart_phase_score, parse_tier, phase1_divergence, specificity_score,
     grounding_ratio, council_confidence, stance_summary, error)

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

Server sends newline-delimited JSON events. Events from `src/llm_council/main.py` arrive before the orchestrator yields; orchestrator events stream during the run.

```
# Pre-run (src/llm_council/main.py)
data: {"type": "model_status", "ready": true, "missing": [], ...}
data: {"type": "warning", "message": "..."}   # Dynamic Swarm fallback, attachment warnings
data: {"type": "error", "message": "..."}     # missing models, hard failures

# Per-phase (orchestrator.py)
data: {"type": "phase_start", "phase": 1, "label": "Independent Analysis"}
data: {"type": "member_thinking", "member": "seat_0", "phase": 1, "meta": {model, label, ...}}
data: {"type": "member_token", "member": "seat_0", "chunk": "..."}
data: {"type": "member_done", "member": "seat_0", "full_text": "..."}

data: {"type": "smart_phase_decision", "skip": false, "split": true,
       "reason": "Stances split (a=PROCEED, b=HOLD) — running cross-review and rebuttal.",
       "stances": {...}, "stance_sources": {"a": "native", "b": "fallback"}, "score": 0.83}

data: {"type": "phase_start", "phase": 2, "label": "Cross-Review"}
# ... same member_thinking / member_token / member_done pattern
data: {"type": "rebuttal_start", "label": "Rebuttal Round — members concede or defend"}
# ... rebuttal streams into each member's phase-2 card
data: {"type": "rebuttal_result", "converged": false, "stances": {...}}

data: {"type": "phase_start", "phase": 3, "label": "Chairman's Verdict"}
data: {"type": "member_thinking", "member": "chairman", "phase": 3, "meta": {...}}
data: {"type": "member_token", "member": "chairman", "chunk": "..."}
data: {"type": "member_done", "member": "chairman", "full_text": "..."}
data: {"type": "chairman_grounding", "ratio": 0.75, "removed": 0, "kept": 4, "enforced": false}
data: {"type": "chairman_verdict", "verdict": "...", "risk_score": 3,
       "action_items": [...], "consensus": [...], "disputes": [...],
       "parse_tier": "json", "removed_points": 0}
data: {"type": "council_confidence", "score": 84, "components": {...},
       "agreement_state": "split_unresolved", "clone_capped": false,
       "explanation": "seats split and did not converge"}

data: {"type": "done"}
```

UI contract: the verdict card renders from `chairman_verdict` (grounding-enforced),
never by re-parsing `member_done` text.

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
