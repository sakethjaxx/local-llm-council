# Agent Task: Phase 2a — Memory Store Upgrade

## Context

Working directory: `/Users/sakethjaggaiahgari/Desktop/local-llm-council`
Stack: FastAPI, LiteLLM, SQLite (WAL mode), Python 3.13 tested, 3.12+ intended
Tests: `./venv/bin/pytest tests/ -q` — must stay green

**Prerequisites completed before this task:**
- `embeddings.py` exists with `get_embedder()` singleton (Phase 1.5)
- `run_store.py` has `run_feedback` table with `thumbs_up` ratings (Phase 1)

Read before starting:
- `memory_graph.py` — full current implementation (NetworkX + JSON file + LLM calls)
- `run_store.py` — how SQLite connection is opened, WAL mode setup
- `orchestrator.py` — where `memory_engine.get_context()` and `memory_engine.extract_memory()` are called
- `embeddings.py` — the `get_embedder()` function
- `main.py` — find `GET /council/memory` endpoint

## Goal

Replace `memory_graph.py` with a new `memory_store.py` that:
1. Stores triples in SQLite (`council_runs.db`) instead of NetworkX + JSON file
2. Retrieves by cosine similarity (vector search) instead of keyword substring match
3. Tracks `confidence`, `last_seen`, `reinforced`, `contradicted`
4. Applies confidence decay on retrieval
5. Quality-gates extraction: only run when quality threshold is met

## Schema Addition

Add to `council_runs.db` (in `run_store.py` SCHEMA constant):

```sql
CREATE TABLE IF NOT EXISTS memory_triples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject      TEXT NOT NULL,
    predicate    TEXT NOT NULL,
    object       TEXT NOT NULL,
    confidence   REAL NOT NULL DEFAULT 1.0,
    reinforced   INTEGER NOT NULL DEFAULT 1,
    contradicted INTEGER NOT NULL DEFAULT 0,
    last_seen    REAL NOT NULL,
    created_at   REAL NOT NULL,
    embedding    BLOB
);
CREATE INDEX IF NOT EXISTS idx_memory_subject ON memory_triples(subject);
CREATE INDEX IF NOT EXISTS idx_memory_last_seen ON memory_triples(last_seen DESC);
```

Add this to the existing `SCHEMA` string in `run_store.py` so it's applied on startup alongside existing tables.

## Implementation: `memory_store.py`

Create this file. It must expose the same interface as `memory_graph.py` so `orchestrator.py` can swap `memory_engine` with minimal changes:

```python
class SQLiteMemory:
    async def extract_memory(self, topic: str, verdict: str, extraction_model: str,
                              run_id: str = None) -> None: ...

    async def get_context(self, topic: str, extraction_model: str, top_k: int = 10) -> str: ...

    def get_graph_data(self) -> dict: ...  # returns {"nodes": [...], "edges": [...]}
    
    def rebuild_embeddings(self) -> None: ...  # background startup task

memory_store = SQLiteMemory()
```

### `extract_memory` implementation

Quality gate check (before any LLM call):
1. If `run_id` is provided, query `run_feedback` for that run
2. Skip extraction if: no `thumbs_up` feedback AND extraction_model produces `risk_score > 3`
   - Note: `risk_score` is in the Phase 3 output JSON. Parse it from `phase_outputs` where `phase=3, member_id="chairman"`.
3. If run_id is None, skip quality gate and extract always (for backward compat)

Extraction (same LLM prompt as current `memory_graph.py`):
- Use `COUNCIL_MEMORY_MODEL` env var if set, else fall back to `extraction_model` param
- Parse triples from JSON response
- For each triple: embed `"{subject} {predicate} {object}"` using `get_embedder()`
- Check for existing similar triple (cosine > 0.92 with existing embeddings):
  - If found: increment `reinforced`, update `last_seen`, update `confidence = min(1.0, confidence + 0.1)`
  - If not found: INSERT new triple with embedding as `numpy.float32.tobytes()`
- Save embedding as `numpy.ndarray.astype(numpy.float32).tobytes()` BLOB

### `get_context` implementation

1. Embed the query topic using `get_embedder()`
2. Load all triples from `memory_triples` (SELECT id, subject, predicate, object, confidence, last_seen, embedding)
3. For each triple with a non-null embedding: deserialize BLOB → `numpy.frombuffer(blob, dtype=numpy.float32)`
4. Compute cosine similarity between query embedding and each triple embedding
5. Apply confidence decay: `effective_confidence = confidence * (0.99 ** days_since_last_seen)`
6. Rank by `cosine_similarity * effective_confidence`, return top_k
7. Format as: `"COUNCIL HISTORICAL MEMORY (Past decisions you must consider):\n" + "\n".join(triple_strings)`
8. Return empty string if no triples or DB is empty

### `get_graph_data` implementation

Return `{"nodes": [...], "edges": [...]}` compatible with current `/council/memory` response shape. Nodes are unique subjects/objects. Edges are triples with `label=predicate`.

### `rebuild_embeddings` implementation

On startup (called once in `main.py` lifespan or background task):
- Query `SELECT id, subject, predicate, object FROM memory_triples WHERE embedding IS NULL`
- For each row: compute embedding, UPDATE that row
- Log count rebuilt

## Orchestrator Integration

In `orchestrator.py`:
- Change `from memory_graph import memory_engine` → `from memory_store import memory_store as memory_engine`
- Pass `run_id` to `extract_memory` if available
- Everything else stays the same (interface is compatible)

## Startup Task

In `main.py`, in the FastAPI lifespan or startup event:
```python
import asyncio
from memory_store import memory_store
asyncio.create_task(asyncio.to_thread(memory_store.rebuild_embeddings))
```

## Tests

Create `tests/test_memory_store.py`:
- `test_empty_db_returns_empty_context`: cold start, `get_context(...)` returns `""`
- `test_extract_and_retrieve`: insert a triple via `extract_memory`, then `get_context` with semantically similar topic returns that triple in results
- `test_confidence_decay`: set `last_seen` to 365 days ago, verify decayed triple ranks below a fresh triple with same cosine similarity
- `test_reinforcement`: extracting same-meaning triple twice increments `reinforced`, doesn't duplicate row
- `test_graph_data_shape`: `get_graph_data()` returns dict with `"nodes"` and `"edges"` lists
- Use in-memory SQLite (`:memory:`) by patching `DB_PATH` or passing db path to constructor

## Deprecation

After `memory_store.py` is working:
- Keep `memory_graph.py` in place but add a deprecation comment at top
- Delete `council_memory.json` if it exists (add to `.gitignore`)

## Acceptance Criteria

- `./venv/bin/pytest tests/ -q` green
- `GET /council/memory` returns nodes+edges from SQLite (not JSON file)
- Quality gate prevents extraction on unrated runs
- Cold start (empty DB) never errors
- Retrieving context on a topic returns semantically related triples, not just keyword matches
- `memory_triples` table exists in `council_runs.db` after first startup
- `council_memory.json` is no longer written

## Do Not

- Add paid API calls
- Block the FastAPI event loop during embedding rebuild (use `asyncio.to_thread`)
- Load SentenceTransformer outside `embeddings.get_embedder()`
- Change existing table schemas in `run_store.py`
