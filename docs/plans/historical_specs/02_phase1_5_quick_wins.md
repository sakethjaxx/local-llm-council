# Agent Task: Phase 1.5 — Quick Wins

## Context

Working directory: `/Users/sakethjaggaiahgari/Desktop/local-llm-council`
Stack: FastAPI, LiteLLM, SQLite, Python 3.13 tested, 3.12+ intended
Tests: `./venv/bin/pytest tests/ -q` — must stay green (currently 30 passing)

Read before starting:
- `smart_phase.py` — see how embedder is currently loaded
- `demo_catalog.py` — current preset structure
- `blast_radius.py` — see duplicate walk/AST code
- `project_graph.py` — find `build_project_graph()` function signature and return type
- `static/index.html` — search for hardcoded preset data in JS (around line 1000+)
- `main.py` — find `/demo/catalog` endpoint

## Tasks

### Task A: Shared Embedder Singleton (`embeddings.py`)

Create `/Users/sakethjaggaiahgari/Desktop/local-llm-council/embeddings.py`:

```python
_embedder = None

def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        print("\n[embeddings] Loading SentenceTransformer all-MiniLM-L6-v2...")
        _embedder = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedder
```

Refactor `smart_phase.py`:
- Remove the inline `embedder` global and `_get_embedder()` function
- Import `from embeddings import get_embedder`
- Replace all `_get_embedder()` calls with `get_embedder()`

Write a test in `tests/test_embeddings.py`:
- Two calls to `get_embedder()` return the exact same object (`is` identity check)
- `get_embedder()` returns an object that has an `encode` method

### Task B: Extract Presets to `presets.json`

1. Create `presets.json` in the project root. Populate it by extracting all preset definitions from `demo_catalog.py`. Structure:

```json
{
  "version": "1",
  "presets": [
    {
      "id": "fast_triage",
      "label": "Fast Triage",
      "description": "Fastest stable council path",
      "seats": [
        {"model": "ollama/qwen2.5:3b", "persona": "..."},
        {"model": "ollama/gemma2:2b", "persona": "..."}
      ],
      "chairman_model": "ollama/qwen2.5:7b",
      "topic_placeholder": "Review this architecture brief...",
      "sample_files": ["architecture_brief.md"],
      "toggles": {"deep_debate": false, "dynamic_swarm": false}
    }
  ]
}
```

Extract ALL presets from `demo_catalog.py`. Do not invent new presets — preserve exact model names, personas, and topic placeholders.

2. Rewrite `demo_catalog.py` to be a thin loader:
```python
import json, os

def load_presets():
    path = os.path.join(os.path.dirname(__file__), "presets.json")
    with open(path) as f:
        return json.load(f)

def get_demo_catalog():
    return load_presets()["presets"]
```

3. Add `GET /config/presets` endpoint in `main.py` that returns `load_presets()`.

4. In `static/index.html`: add a fetch to `/config/presets` on page load. Replace any hardcoded preset JS arrays with data from the API response. The rendered output in the UI must be identical to before.

5. Test: `test_main.py` — assert `GET /config/presets` returns 200, body has `"presets"` key, list is non-empty.

### Task C: Blast Radius Uses Project Graph

Read `blast_radius.py` fully. It walks the project tree and parses AST to build a dependency graph, then finds reverse dependencies of changed files.

Read `project_graph.py` fully. It already does the same walk+parse and returns a NetworkX DiGraph.

Refactor `blast_radius.py`:
- Call `project_graph.build_project_graph(root)` to get the dependency graph
- Compute reverse dependencies by traversing the graph (predecessors in DiGraph)
- Remove all duplicated `os.walk`, `ast.parse`, import-extraction code

Preserve exactly:
- The function signature(s) called by `main.py`
- The JSON output shape returned by those functions
- Edge type distinction (import vs string-ref) — if `project_graph` doesn't track this, add it there and use it in `blast_radius`

Write a test: same input path produces same output shape from old and new implementation.

### Task D: Phase Prompts Externalized

Phase 1 / 2 / 3 system prompts are hardcoded string literals in `orchestrator.py`. Extract them.

1. Create directory `agent_prompts/phase_prompts/`.
2. Create three files:
   - `phase1_analyze.txt` — the Phase 1 analysis system prompt
   - `phase2_review.txt` — the Phase 2 cross-review system prompt
   - `phase3_chairman.txt` — the Phase 3 chairman synthesis system prompt
3. Copy the exact current prompt strings from `orchestrator.py` into those files (no edits to prompt content).
4. In `orchestrator.py`, add a loader at module level:
```python
from pathlib import Path
def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "agent_prompts" / "phase_prompts" / name
    return path.read_text()

PHASE1_PROMPT = _load_prompt("phase1_analyze.txt")
PHASE2_PROMPT = _load_prompt("phase2_review.txt")
PHASE3_PROMPT = _load_prompt("phase3_chairman.txt")
```
5. Replace all inline prompt string literals in `orchestrator.py` with `PHASE1_PROMPT`, `PHASE2_PROMPT`, `PHASE3_PROMPT`.

If a prompt file is missing, `read_text()` raises `FileNotFoundError` at import time — this is correct (fail fast).

### Task E: Smart Phase Similarity Score Logged

`smart_phase.should_skip()` currently returns `bool`. Change to return `tuple[bool, float]` where the float is the mean pairwise cosine similarity score.

In `run_store.py`, add column to `runs` table:
```python
# Migration check on first connection:
cursor.execute("PRAGMA table_info(runs)")
cols = {row[1] for row in cursor.fetchall()}
if "smart_phase_score" not in cols:
    cursor.execute("ALTER TABLE runs ADD COLUMN smart_phase_score REAL")
```

In `orchestrator.py`, after calling `smart_phase.should_skip(...)`:
```python
skip, score = smart_phase.should_skip(analyses)
run_store.update_smart_phase_score(run_id, score)
```

Add `update_smart_phase_score(run_id, score)` to `run_store.py`.

`GET /runs/{run_id}` response includes `smart_phase_score` (float or null).

Test in `tests/test_smart_phase.py`: assert return type is `tuple[bool, float]`.

## Acceptance Criteria

- `./venv/bin/pytest tests/ -q` passes all tests
- `smart_phase.py` has no inline `SentenceTransformer` instantiation
- `smart_phase.should_skip()` returns `(bool, float)`
- Phase prompts load from `agent_prompts/phase_prompts/*.txt` at import time
- Adding a new preset to `presets.json` requires no Python or JS changes
- `GET /config/presets` returns 200 with non-empty preset list
- `GET /runs/{run_id}` includes `smart_phase_score`
- `blast_radius.py` has no `ast.parse` or `os.walk` calls
- UI renders existing presets identically before and after

## Do Not

- Change any existing API endpoint response shapes (other than adding new fields)
- Add cloud LLM calls
- Modify the prompt content when externalizing (copy exact strings)
- Modify orchestrator.py beyond prompt externalization and smart_phase score wiring
