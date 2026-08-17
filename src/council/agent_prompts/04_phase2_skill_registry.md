# Agent Task: Phase 2b — Skill Registry

## Context

Working directory: `/Users/sakethjaggaiahgari/Desktop/local-llm-council`
Stack: FastAPI, LiteLLM, SQLite (WAL mode), Python 3.13 tested, 3.12+ intended
Tests: `./venv/bin/pytest tests/ -q` — must stay green

**Prerequisites completed before this task:**
- `embeddings.py` with `get_embedder()` singleton (Phase 1.5)
- `run_store.py` with `run_feedback` table (Phase 1)
- `memory_store.py` with SQLite + vector retrieval (Phase 2a)
- `project_fingerprint.py` with `fingerprint(path) -> dict` (see Phase 2 spec)

Read before starting:
- `orchestrator.py` — find `_build_messages`, `SYSTEM_COUNCIL_BASE`, and the Phase 1 prompt construction
- `run_store.py` — understand `phase_outputs` table and how to query chairman output
- `main.py` — find existing endpoints, where to add `GET /skills`
- `embeddings.py` — `get_embedder()` singleton
- `docs/SPEC.md` section P2-4 — full spec

## Goal

Build `skill_registry.py` that:
1. Extracts reusable analysis skills from past runs (quality-gated)
2. Stores skills in SQLite with vector embeddings
3. Injects top-matching skills into Phase 1 council prompts
4. Exposes `GET /skills` API endpoint

## Schema Addition

Add to `run_store.py` SCHEMA:

```sql
CREATE TABLE IF NOT EXISTS skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    body        TEXT NOT NULL,
    domain      TEXT,
    source_run  TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    confidence  REAL NOT NULL DEFAULT 0.5,
    used_count  INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    embedding   BLOB
);
CREATE INDEX IF NOT EXISTS idx_skills_confidence ON skills(confidence DESC);
```

## Implementation: `skill_registry.py`

```python
class SkillRegistry:
    async def extract_skills(self, run_id: str, topic: str,
                              chairman_model: str) -> None: ...

    async def get_skills_for_topic(self, topic: str, top_k: int = 3) -> list[dict]: ...

    def format_skills_block(self, skills: list[dict]) -> str: ...

skill_registry = SkillRegistry()
```

### `extract_skills` implementation

**Quality gate** (same logic as memory_store):
1. Query `run_feedback` for `run_id` — skip if no `thumbs_up` feedback
2. Query `phase_outputs` for `phase=3, member_id="chairman"` for this run — parse JSON, get `risk_score`
3. Skip extraction if: no thumbs_up AND risk_score > 3
4. If gate passes: proceed

**Extraction prompt** (send to `chairman_model`):
```
You are a skill extractor for an AI council system.
Given the topic and chairman verdict below, extract ONE reusable analysis skill that future councils could apply.
A skill is a concrete analytical approach, heuristic, or reasoning pattern — not a conclusion.
Respond with JSON: {"name": "short skill name (max 6 words)", "body": "one paragraph describing the skill and when to apply it", "domain": "optional domain tag (e.g. backend, security, architecture, or null)"}

Topic: {topic[:400]}
Chairman Verdict: {verdict[:1200]}
```

Cap: extract at most 3 skills per run. Run the prompt up to 3 times with slightly varied temperatures (0.3, 0.5, 0.7).

**Sanity check** (per extracted skill):
Send a second prompt to `chairman_model`:
```
Does the following analysis skill logically follow from this council verdict?
Skill: {skill_body}
Verdict: {verdict[:800]}
Answer with only "yes" or "no".
```
Discard the skill if response does not start with "yes" (case-insensitive).

**Storage**:
- Embed `skill["name"] + " " + skill["body"]` using `get_embedder()`
- Check for near-duplicate (cosine > 0.90 with existing skill embeddings):
  - If duplicate found: increment confidence by 0.05 (cap at 1.0), skip insert
  - If new: INSERT with embedding BLOB, `confidence=0.5`, `used_count=0`

### `get_skills_for_topic` implementation

1. Embed topic using `get_embedder()`
2. Load all skills from `skills` table (SELECT id, name, body, domain, confidence, used_count, embedding)
3. Deserialize embeddings: `numpy.frombuffer(blob, dtype=numpy.float32)`
4. Rank by `cosine_similarity * confidence`
5. Return top_k as list of dicts: `{id, name, body, domain, confidence, used_count}`
6. After returning: UPDATE `used_count = used_count + 1` for returned skill IDs (async, non-blocking)

### `format_skills_block` implementation

```python
def format_skills_block(self, skills: list[dict]) -> str:
    if not skills:
        return ""
    lines = ["COUNCIL SKILLS (apply these analytical approaches if relevant to the topic):"]
    for s in skills:
        lines.append(f"- [{s['name']}]: {s['body']}")
    return "\n".join(lines) + "\n\n"
```

## Orchestrator Integration

In `orchestrator.py`, Phase 1 prompt construction:

1. Import: `from skill_registry import skill_registry`
2. Before building Phase 1 messages, fetch skills:
   ```python
   skills = await skill_registry.get_skills_for_topic(topic, top_k=3)
   skills_block = skill_registry.format_skills_block(skills)
   ```
3. Prepend `skills_block` to the user content in Phase 1 messages (after memory context, before topic)
4. After `run_store.finish_run()`, trigger extraction in background:
   ```python
   asyncio.create_task(
       skill_registry.extract_skills(run_id, topic, chairman_model)
   )
   ```

## API Endpoint

In `main.py`:

```python
@app.get("/skills")
async def list_skills(limit: int = 50, domain: str = None):
    # Query skills table, optional domain filter, order by confidence DESC
    ...
```

Response shape:
```json
{
  "skills": [
    {"id": 1, "name": "...", "body": "...", "domain": "...",
     "confidence": 0.75, "used_count": 3, "created_at": 1234567890.0}
  ],
  "total": 5
}
```

## Tests: `tests/test_skill_registry.py`

- `test_extraction_quality_gate_blocks_bad_run`: run with no thumbs_up and risk_score=8 → no skills inserted
- `test_extraction_quality_gate_passes_thumbs_up`: run with thumbs_up → extraction proceeds (mock LLM calls)
- `test_sanity_check_discards_no_answer`: when sanity check returns "no", skill is not stored
- `test_dedup_increments_confidence`: extracting near-duplicate skill increments existing skill's confidence
- `test_get_skills_returns_relevant`: insert a skill about "security review", query with "authentication vulnerability" topic → that skill appears in results
- `test_used_count_increments`: call `get_skills_for_topic` → used_count of returned skills increases
- `test_format_skills_block_empty`: empty skills list → returns empty string
- `test_format_skills_block_populated`: 2 skills → block starts with "COUNCIL SKILLS"
- Use in-memory SQLite for all tests

## Acceptance Criteria

- `./venv/bin/pytest tests/ -q` green
- Phase 1 prompts include COUNCIL SKILLS block when relevant skills exist in DB
- Skills only extracted when quality gate passes
- `GET /skills` returns 200 with skills list
- Near-duplicate skills increment confidence instead of creating new rows
- `used_count` increments on retrieval
- No LLM call made during `get_skills_for_topic` (only during extraction)

## Do Not

- Block the event loop during embedding operations (use `asyncio.to_thread`)
- Load SentenceTransformer outside `embeddings.get_embedder()`
- Add paid API calls
- Store API keys or secrets in the skills table
- Run extraction synchronously inside the council run (always background task)
