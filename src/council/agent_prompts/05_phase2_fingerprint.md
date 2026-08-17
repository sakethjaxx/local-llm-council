# Agent Task: Phase 2c — Project Fingerprint

## Context

Working directory: `/Users/sakethjaggaiahgari/Desktop/local-llm-council`
Stack: Python 3.13 tested, 3.12+ intended, stdlib only (no LLM, no ML libraries)
Tests: `./venv/bin/pytest tests/ -q` — must stay green

This is a standalone module with no dependencies on other Phase 2 work. Build it independently.

Read before starting:
- `run_store.py` — find `fingerprint_hash` column in `runs` table, `begin_run` signature
- `orchestrator.py` — find where `begin_run` is called to see how fingerprint_hash gets passed

## Goal

Create `project_fingerprint.py` — pure heuristic detection of a project's tech stack and domain. No LLM, no ML. Returns a short dict and a stable SHA-256 hash.

## Implementation

```python
import hashlib, json, os
from pathlib import Path
from collections import Counter

def fingerprint(root: str = ".") -> dict:
    """
    Returns:
    {
      "languages": ["python", "javascript"],   # ordered by file count desc
      "frameworks": ["fastapi", "react"],       # detected from config files
      "domain": ["api", "ml"],                  # keywords from README + top-level files
      "hash": "abc123..."                       # stable SHA-256 of the above (sorted)
    }
    """
```

### Language Detection

Walk the project root (skip `.git`, `venv`, `node_modules`, `__pycache__`, `dist`, `build`).
Count files by extension:

| Extension(s) | Language |
|---|---|
| `.py` | python |
| `.js`, `.mjs`, `.cjs` | javascript |
| `.ts`, `.tsx` | typescript |
| `.go` | go |
| `.rs` | rust |
| `.java`, `.kt` | java |
| `.rb` | ruby |
| `.cs` | csharp |
| `.cpp`, `.cc`, `.h` | cpp |

Return languages with count > 0, sorted by count descending. Max 5 languages.

### Framework Detection

Check for these files in the project root (not recursive):

| File | Framework |
|---|---|
| `requirements.txt` or `pyproject.toml` | Check contents for: `fastapi`→fastapi, `django`→django, `flask`→flask, `torch`→pytorch, `tensorflow`→tensorflow, `transformers`→huggingface |
| `package.json` | Parse JSON, check `dependencies` + `devDependencies` for: `react`→react, `vue`→vue, `next`→nextjs, `express`→express, `svelte`→svelte |
| `go.mod` | framework=go_modules |
| `Cargo.toml` | framework=cargo |
| `pom.xml` | framework=maven |
| `build.gradle` | framework=gradle |

### Domain Detection

Read `README.md` (first 2000 chars) and any `.md` files in project root (first 500 chars each).
Scan for keyword sets:

| Keyword(s) | Domain tag |
|---|---|
| `api`, `endpoint`, `rest`, `graphql` | api |
| `machine learning`, `ml`, `model`, `train`, `inference` | ml |
| `security`, `auth`, `vulnerability`, `pentest` | security |
| `frontend`, `ui`, `component`, `css` | frontend |
| `database`, `sql`, `migration`, `schema` | database |
| `infra`, `deploy`, `kubernetes`, `docker`, `ci/cd` | infra |
| `council`, `llm`, `agent`, `orchestrat` | ai_agents |

Match case-insensitive. Return all matching domain tags.

### Hash Computation

```python
payload = json.dumps({
    "languages": sorted(result["languages"]),
    "frameworks": sorted(result["frameworks"]),
    "domain": sorted(result["domain"])
}, sort_keys=True)
result["hash"] = hashlib.sha256(payload.encode()).hexdigest()[:16]
```

Hash is derived from sorted, deterministic content — same project always produces same hash.

## Orchestrator Integration

In `orchestrator.py`, when `begin_run` is called:
```python
from project_fingerprint import fingerprint
fp = fingerprint(root=".")
run_store.begin_run(..., fingerprint_hash=fp["hash"])
```

## Tests: `tests/test_fingerprint.py`

- `test_empty_dir`: fingerprint on empty temp dir returns empty languages, empty frameworks, empty domain, valid 16-char hash
- `test_python_project`: dir with `.py` files → `"python"` in languages
- `test_mixed_project`: dir with `.py` + `.ts` files → both in languages, ordered by count
- `test_fastapi_framework`: dir with `requirements.txt` containing `fastapi` → `"fastapi"` in frameworks
- `test_package_json_react`: dir with `package.json` with `react` dependency → `"react"` in frameworks
- `test_domain_api`: README with word "endpoint" → `"api"` in domain
- `test_hash_determinism`: same dir called twice → same hash
- `test_hash_changes_on_language_add`: add a `.py` file to dir → hash changes
- `test_skips_venv`: `.py` files inside `venv/` not counted in language detection

## Acceptance Criteria

- `./venv/bin/pytest tests/test_fingerprint.py -q` all pass
- `fingerprint(".")` on this project returns `languages=["python"]`, `frameworks` includes `fastapi`, `domain` includes `ai_agents`
- Hash is 16 hex chars, deterministic
- No LLM calls, no ML library imports
- `run_store.begin_run` receives `fingerprint_hash` from orchestrator

## Do Not

- Import litellm, sentence_transformers, or any ML library
- Read files outside the project root
- Take longer than 2 seconds on the local-llm-council project itself
