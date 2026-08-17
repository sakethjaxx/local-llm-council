# Codex Implementation Plan — Audit Remediation

Handoff spec for an agent with **no prior context**. Every task is self-contained: it states the
defect, the exact location, the current code, the target code, and a verification command that can
fail. Do not mark a task done until its verification command has actually been run and passed.

## Project facts you need up front

| Thing | Value |
|---|---|
| Repo root | `local-llm-council` |
| Language | Python 3.13 (venv at `./venv`), vanilla JS frontend |
| Run tests | `./venv/bin/pytest tests/ -q` |
| Baseline | **127 tests passing** before any change |
| Server | `PYTHONPATH=src ./venv/bin/python3 -m uvicorn council.main:app --host 127.0.0.1 --port 8765` |
| Stores | `run_store`, `memory_store`, `skill_registry` are **module-level singletons** built at import time |
| Frontend | `static/index.html` + `static/app.js` + `static/style.css` (no build step, no bundler) |

**Non-negotiable project rules** (from `CLAUDE.md`, do not violate):
- No cloud LLM calls in any default flow. Ollama-first. Cloud is opt-in via user-supplied key.
- Do not load the SentenceTransformer model more than once — use the shared singleton in `embeddings.py`.
- Do not add columns to SQLite tables without a migration path.
- Tests live in `tests/`, pytest, no DB mocking — use real SQLite against a temp/in-memory path.

**Execution order matters.** Task 1 must land first: until test isolation is fixed, every later
verification writes junk into the user's real database, and you cannot trust before/after counts.

---

## Task 1 — Stop the test suite writing to the production database

**Severity: Medium. Do this first — it makes all later verification honest.**

### Defect
Running `pytest tests/` inserts real rows into the production `council_runs.db`. Verified: run
count went 38 → 39 across a single test run. `tests/test_demo_scenarios.py` patches
`orchestrator.litellm.acompletion` but leaves `run_store` / `memory_store` / `skill_registry`
pointed at the real database, so `CouncilOrchestrator.run()` persists genuine rows. This
contaminates the user's run history, metrics, and memory graph, and violates the project's own
stated testing convention.

### Root cause
`run_store.py:13` hardcodes the path as a module constant evaluated at import time:

```python
DB_PATH = "council_runs.db"
```

This single constant is the source for all three stores:
- `memory_store.py:17` → `from run_store import DB_PATH`
- `skill_registry.py:16` → `from run_store import DB_PATH, SCHEMA`
- `main.py:39` → `from run_store import DB_PATH as RUN_DB_PATH`

### Change 1a — make the DB path environment-overridable

`run_store.py:13`

```python
# current
DB_PATH = "council_runs.db"

# target
DB_PATH = os.getenv("COUNCIL_DB_PATH", "council_runs.db")
```

**`run_store.py` does not currently import `os`** — verified, its imports are `json`, `sqlite3`,
`time`. You must add `import os` at the top or this change raises `NameError` on import and takes
the whole app down.

This mirrors the existing, working precedent in `metrics_store.py:36-38`, where
`COUNCIL_METRICS_FILE` is already read from the environment for exactly this reason.

### Change 1b — point tests at a temp database

`tests/conftest.py` currently contains only a `sys.path` insert. Add an environment override
**above** the path insert so it is set before any test module imports a store singleton:

```python
import os
import sys
import tempfile

# Store singletons (run_store / memory_store / skill_registry) are constructed at
# import time from run_store.DB_PATH. Redirect them to a throwaway file before any
# test module imports them, so tests never touch the real council_runs.db.
os.environ.setdefault("COUNCIL_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="council-test-"), "test_runs.db"))
os.environ.setdefault("COUNCIL_METRICS_FILE", "")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
```

`conftest.py` is imported by pytest before it collects test modules, so this runs early enough.

### Verification (must pass)

```bash
cd <repo-root>
BEFORE=$(./venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('council_runs.db').execute('SELECT COUNT(*) FROM runs').fetchone()[0])")
./venv/bin/pytest tests/ -q
AFTER=$(./venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('council_runs.db').execute('SELECT COUNT(*) FROM runs').fetchone()[0])")
echo "before=$BEFORE after=$AFTER"
```

**Done when:** `before == after`, AND the suite still reports 127+ passing.

**Also confirm you did not break production defaults:**
```bash
./venv/bin/python3 -c "import run_store; print(run_store.DB_PATH)"   # must print: council_runs.db
```

---

## Task 2 — `.env` files leak into prompts and the database

**Severity: High.**

### Defect
`ingest_folder()` reads `.env` files and injects their contents into the LLM prompt and into
`council_runs.db`. The author clearly intended to exclude them — `.env` is already listed in
`SKIP_INGEST_DIRS` — but the set is applied only to **directory** names, never to filenames.

Reproduced:
```
files ingested: ['.env', 'app.py']
DB_PASSWORD in prompt: True
hunter2 in prompt: True
```

Secondary aggravator: `scrub_secret_values()` in `provider_caps.py` only matches *patterned*
secrets (`sk-`, `AKIA`, `AIza`, `gh*`, JWT, bearer). A plain `DB_PASSWORD=hunter2` is not caught,
so `run_store.py:214` persists it verbatim.

This is the happy path of the "Review Local Project → Bulk Ingest Files" feature: users point it
at their own repo, which is exactly where a `.env` lives.

### Change

`io_parser.py:200` — rename the constant to reflect that it now covers both, and add explicit
file-level patterns:

```python
# current
SKIP_INGEST_DIRS = {".git", "venv", "node_modules", "__pycache__", "dist", "build", ".env", "env"}

# target
SKIP_INGEST_DIRS = {".git", "venv", "node_modules", "__pycache__", "dist", "build", "env"}

# Secret-bearing files must never reach a prompt or the run DB. scrub_secret_values()
# only catches *patterned* secrets (sk-, AKIA, AIza...), so an unpatterned value like
# DB_PASSWORD=hunter2 would otherwise persist verbatim. Exclude by filename instead.
SKIP_INGEST_FILES = {".env", ".env.local", ".env.production", ".env.development",
                     ".npmrc", ".netrc", "id_rsa", "id_ed25519", "credentials"}
SKIP_INGEST_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")


def _is_secret_file(fname: str) -> bool:
    low = fname.lower()
    return (
        low in SKIP_INGEST_FILES
        or low.startswith(".env.")
        or low.endswith(SKIP_INGEST_SUFFIXES)
    )
```

`io_parser.py:215` — filter filenames inside the walk loop:

```python
# current
        for fname in sorted(files):
            if len(attachments) >= max_files:
                break

# target
        for fname in sorted(files):
            if len(attachments) >= max_files:
                break
            if _is_secret_file(fname):
                logger.info("ingest_folder_skipped_secret_file", extra={"file": fname})
                continue
```

Note `.env` is removed from `SKIP_INGEST_DIRS` because a *directory* named `.env` is not a thing
worth excluding; the plain `env` entry (virtualenv dir) stays.

### Verification (must pass)

```bash
cd <repo-root>
TMP=$(mktemp -d)
printf 'DB_PASSWORD=hunter2\nSTRIPE_SECRET=rk_live_zzzz\n' > "$TMP/.env"
printf 'API_TOKEN=abc123\n' > "$TMP/.env.local"
printf 'print("hi")\n' > "$TMP/app.py"
./venv/bin/python3 -c "
from io_parser import ingest_folder, format_attachments_for_prompt
a = ingest_folder('$TMP', 50)
names = [x['filename'] for x in a]
blob = format_attachments_for_prompt(a)
print('ingested:', names)
assert '.env' not in names, 'FAIL: .env still ingested'
assert '.env.local' not in names, 'FAIL: .env.local still ingested'
assert 'app.py' in names, 'FAIL: normal file wrongly skipped'
assert 'hunter2' not in blob, 'FAIL: secret reached prompt'
print('PASS')
"
rm -rf "$TMP"
```

**Also add a regression test** in `tests/test_io_parser.py` asserting the same thing, so this
cannot silently regress. Follow the existing `tempfile.TemporaryDirectory()` pattern already used
in that file.

**Done when:** the script prints `PASS`, the new test passes, and the full suite still passes.

---

## Task 3 — `/ingest/folder` bypasses path confinement

**Severity: High.**

### Defect
`_confine_to_project_root()` enforces the `COUNCIL_PROJECT_ROOT` sandbox and is correctly applied
by two of the three path-taking routes:
- `/council/review-project` → `main.py:564` ✅
- `/project/code-graph` → `main.py:628` ✅
- `/ingest/folder` → `main.py:249-256` ❌ **missing**

Reproduced with `COUNCIL_PROJECT_ROOT` set to the repo root:
```
code-graph/review-project confinement: ENFORCED -> Path is outside the allowed COUNCIL_PROJECT_ROOT
ingest/folder on /etc -> file_count: 3  ['afpovertcp.cfg', 'aliases', 'asl.conf']
```

A partially-applied security boundary is worse than none, because the operator believes it holds.

### Change

`main.py:249-262`

```python
# current
@app.post("/ingest/folder")
async def ingest_local_folder(payload: FolderIngestRequest):
    """
    Bulk ingest a local folder path, returning parsed attachments and formatted prompt text.
    """
    if not payload.folder_path:
        raise HTTPException(status_code=400, detail="folder_path is required")
    attachments = await asyncio.to_thread(ingest_folder, payload.folder_path, payload.max_files or 50)

# target
@app.post("/ingest/folder")
async def ingest_local_folder(payload: FolderIngestRequest):
    """
    Bulk ingest a local folder path, returning parsed attachments and formatted prompt text.
    """
    if not payload.folder_path:
        raise HTTPException(status_code=400, detail="folder_path is required")
    # Same confinement the other two path-taking routes enforce (/council/review-project,
    # /project/code-graph). Without it COUNCIL_PROJECT_ROOT is trivially bypassable here.
    root = _confine_to_project_root(payload.folder_path)
    max_files = max(1, min(payload.max_files or 50, 200))
    attachments = await asyncio.to_thread(ingest_folder, root, max_files)
```

The `max_files` clamp closes a second, smaller hole: the current `payload.max_files or 50` accepts
an arbitrary integer, and `ingest_folder` reads each file fully into memory (`io_parser.py:221`).
The upload path already enforces limits via `COUNCIL_MAX_FILES` / `COUNCIL_MAX_UPLOAD_MB`
(`main.py:285-300`); this brings the folder path in line.

### Verification (must pass)

```bash
cd <repo-root>
COUNCIL_PROJECT_ROOT="$PWD" ./venv/bin/python3 -c "
import asyncio, main
req = main.FolderIngestRequest(folder_path='/etc', max_files=3)
try:
    asyncio.run(main.ingest_local_folder(req))
    raise SystemExit('FAIL: /etc was ingested despite COUNCIL_PROJECT_ROOT')
except main.HTTPException as e:
    assert e.status_code == 403, e
    print('PASS: blocked with 403 ->', e.detail)
" 2>&1 | grep -v '^{'
```

**Also verify the normal case still works** (no `COUNCIL_PROJECT_ROOT` set → unrestricted, which is
the documented default):
```bash
./venv/bin/python3 -c "
import asyncio, main
r = asyncio.run(main.ingest_local_folder(main.FolderIngestRequest(folder_path='.', max_files=3)))
assert r['file_count'] > 0
print('PASS: default path still ingests', r['file_count'], 'files')
" 2>&1 | grep -v '^{'
```

**Add a test** in `tests/test_main.py` mirroring the existing pattern at line ~572, which already
uses `patch.dict(os.environ, {"COUNCIL_PROJECT_ROOT": ...})`.

---

## Task 4 — Unescaped LLM-controlled values injected into the DOM

**Severity: Medium.**

### Defect
`static/app.js:796-811` (`buildCard`) is the only place in the frontend that interpolates values
into `innerHTML` without escaping. Every other site escapes (`escapeHtml` on action items at line
783, `sanitizeHtml` on chairman HTML at 787).

```js
const color = meta.color || 'var(--accent)';
card.innerHTML = `
  <div class="card-header">
    <div class="card-icon" style="color:${color}">${meta.icon}</div>
    <div class="card-name" style="color:${color}">${meta.label.toUpperCase()}</div>
  </div>
  ...
```

`meta` is the seat config. With **Dynamic Swarm** enabled, `label` / `icon` / `color` are generated
by an LLM in `router_agent.py` from attachment content — so prompt-injected text inside a reviewed
file can reach the DOM. `color` additionally lands inside a `style="..."` attribute.

### Change

`escapeHtml` is already defined in `app.js` above `buildCard`, so no import is needed.

```js
// target
function buildCard(member, meta, content, phase) {
  const isChairman = member === 'chairman';
  const card = document.createElement('div');
  card.className = isChairman ? 'council-card chairman-card' : 'council-card';

  // meta.label/icon/color can be LLM-generated (Dynamic Swarm builds personas via
  // router_agent), so treat them as untrusted: escape text and allow only a safe
  // colour literal in the style attribute.
  const rawColor = String(meta.color || '');
  const color = /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)$/.test(rawColor) ? rawColor : 'var(--accent)';
  const label = escapeHtml(String(meta.label || member).toUpperCase());
  const icon = escapeHtml(meta.icon || '');

  card.innerHTML = `
    <div class="card-header">
      <div class="card-icon" style="color:${color}">${icon}</div>
      <div class="card-name" style="color:${color}">${label}</div>
    </div>
    <div class="typing"><span></span><span></span><span></span></div>
    <div class="card-body" style="display:none"></div>
  `;
  return card;
}
```

Note the original used `meta.label.toUpperCase()` with no fallback — that throws if `label` is
missing. The target adds a `member` fallback, which also fixes that latent crash.

### Verification (must pass)

```bash
cd <repo-root>
node --check static/app.js && echo "SYNTAX OK"
```

Then a runtime check. Start the server, and in a browser console on `http://127.0.0.1:8765`:
```js
const c = buildCard('x', {label: '<img src=x onerror=alert(1)>', icon: '<b>i</b>', color: 'red"><script>'}, null, 1);
console.log(c.querySelectorAll('img, script').length);  // must be 0
console.log(c.querySelector('.card-name').textContent); // must show the literal tag text
```

**Done when:** zero `img`/`script` nodes are produced and the injected markup appears as inert text.

---

## Task 5 — Memory retrieval has no relevance floor

**Severity: Medium.**

### Defect
`memory_store.py:313-315` returns the top-K scored triples unconditionally, with no minimum score:

```python
scored.sort(key=lambda item: item[0], reverse=True)
top = [text for _, text in scored[: max(1, top_k)]]
return "COUNCIL HISTORICAL MEMORY (Past decisions you must consider):\n" + "\n".join(top) + "\n\n"
```

A triple scoring 0.02 similarity is still injected under a header instructing the council it
"must consider" it. This measurably contaminates verdicts: in a live run on the topic *"Should a
local-first app store API keys in browser localStorage?"*, the chairman emitted a dispute about
**"Hardware Constraints"** — matching the stored triple `hardware_constraints ->
were_not_considered -> initially` from an unrelated earlier run, attributed to a persona that was
not even in the roster.

### Change

`memory_store.py` — add a module-level threshold near the other constants:

```python
# Minimum blended score (cosine similarity x time-decayed confidence) for a triple to
# be worth injecting. Without a floor, an unrelated topic still pulls top_k rows and
# the header tells the council it "must consider" them, which demonstrably leaks
# stale context into verdicts.
MEMORY_RELEVANCE_FLOOR = float(os.getenv("COUNCIL_MEMORY_RELEVANCE_FLOOR", "0.25"))
```

Then in `get_context`, replace lines 313-315:

```python
# target
scored.sort(key=lambda item: item[0], reverse=True)
relevant = [(score, text) for score, text in scored if score >= MEMORY_RELEVANCE_FLOOR]
if not relevant:
    logger.info("memory_context_empty", extra={"best_score": round(scored[0][0], 4) if scored else None})
    return ""
top = [text for _, text in relevant[: max(1, top_k)]]
return "COUNCIL HISTORICAL MEMORY (Past decisions you must consider):\n" + "\n".join(top) + "\n\n"
```

Returning `""` is already a supported contract — `get_context` returns `""` on the no-rows path at
line 288, and `orchestrator.py:783` concatenates the result directly, so an empty string is safe.

### Verification (must pass)

Add a test to `tests/test_memory_store.py` (which already uses `SQLiteMemory(":memory:")` at
line 37, so follow that pattern):

```python
async def test_get_context_returns_empty_when_nothing_is_relevant(self):
    # store a triple about one domain, query about a completely unrelated one
    ...
    context = await store.get_context("quantum chromodynamics lattice gauge theory", "ollama/x")
    self.assertEqual(context, "")

async def test_get_context_returns_relevant_triples(self):
    # a closely-matching query must still return its triple
    ...
    self.assertIn("<expected subject>", context)
```

Both directions matter — a floor that returns nothing for *relevant* queries is a worse bug than
the one being fixed. Tune the default down if the second test fails.

---

## Task 6 — `extract_memory` is the only LLM call site missing scoped keys and a timeout

**Severity: Medium.**

### Defect
Seven live `litellm.acompletion` call sites exist. Six pass `**litellm_kwargs_for_model(model)`,
which injects the per-request cloud API key from the `ContextVar` in `cloud_keys.py`. One does not:

`memory_store.py:201` — `resp = await litellm.acompletion(**completion_kwargs)`

It also omits `timeout=`, which `orchestrator.py:411`, `summarizer.py:42`, and
`search_engine.py:23` all set.

Consequences:
1. Cloud keys supplied through the UI (the documented "stored in this browser only, sent as
   headers" flow) never reach memory extraction. If `COUNCIL_MEMORY_MODEL` names a cloud model,
   extraction fails auth and the error is swallowed at `memory_store.py:270`.
2. No timeout means the fire-and-forget background task can hang indefinitely holding a connection.

### Change

`memory_store.py` — add the import alongside the existing ones:

```python
from cloud_keys import litellm_kwargs_for_model
```

Then at the `completion_kwargs` construction (around line 193-201):

```python
# target
completion_kwargs = {
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 500,
    "timeout": float(os.getenv("COUNCIL_LLM_TIMEOUT", "180")),
    **litellm_kwargs_for_model(model),
}
```

No import cycle: verified `cloud_keys` imports only `contextlib`, `contextvars`, and
`provider_caps` — and `memory_store` already imports `provider_caps`. `memory_store` also already
imports `os` (line 2), so no new stdlib import is needed here.

### Verification (must pass)

```bash
cd <repo-root>
./venv/bin/python3 -c "import memory_store; print('no import cycle')"
./venv/bin/pytest tests/test_memory_store.py -q
```

Add a test asserting the kwargs are forwarded — patch `litellm.acompletion`, set a scoped key via
`scoped_cloud_keys({"openai": "sk-test"})`, call `extract_memory` with an OpenAI model, and assert
`api_key` and `timeout` appear in the recorded call kwargs.

---

## Task 7 — Make the web search opt-in

**Severity: Medium. Confirm intent with the repo owner before changing the default.**

### Defect
`orchestrator.py:653` calls `get_search_context(...)` unconditionally on every run. There is no env
flag and no UI toggle. Confirmed live: `search_dispute_check_started` fires on every council run,
costing an extra LLM call and sending derived content to DuckDuckGo.

Every comparable capability in this project is flag-gated and default-off — `COUNCIL_ALLOW_URL_FETCH`
(`io_parser.py:165`) and `COUNCIL_ENABLE_PYTHON_TOOL` (`orchestrator.py:306`). This one is not, and
it is the only one that transmits off-machine on the default path, which sits awkwardly with the
project's local-first identity. All 11 orchestrator tests patch it out, so the egress is never
exercised.

### Change

`search_engine.py` — add a guard at the top of `get_search_context`:

```python
# target, first lines of get_search_context
def _search_enabled() -> bool:
    return os.getenv("COUNCIL_ENABLE_WEB_SEARCH", "false").strip().lower() == "true"


async def get_search_context(reviews: dict, extraction_model: str) -> str:
    # Off by default: this is the only default-path feature that sends derived council
    # content off-machine, which conflicts with the local-first mandate. Matches the
    # gating style of COUNCIL_ALLOW_URL_FETCH and COUNCIL_ENABLE_PYTHON_TOOL.
    if not _search_enabled():
        return ""
    ...
```

Returning `""` is already the established no-op contract — the function returns `""` on the
no-dispute path (line 28) and the no-results path (line 39), and `orchestrator.py:661` handles an
empty string.

Then document it in `env.example` next to the other feature flags:
```
COUNCIL_ENABLE_WEB_SEARCH=false
# Chairman dispute-resolution web search (DuckDuckGo). Off by default: it sends derived
# council content to a third party and costs one extra LLM call per run.
```

### Verification (must pass)

```bash
cd <repo-root>
./venv/bin/python3 -c "
import asyncio, search_engine
out = asyncio.run(search_engine.get_search_context({'a':'is X stable?'}, 'ollama/llama3.2:3b'))
assert out == '', 'FAIL: search ran while disabled'
print('PASS: search disabled by default, no network call')
"
./venv/bin/pytest tests/ -q
```

Add a test asserting that with the flag unset, `litellm.acompletion` is **never called** by
`get_search_context` — that is the real invariant (no LLM call, no network).

---

## Task 8 — Surface `warning` and `shutdown` events in the UI

**Severity: Low-Medium.**

### Defect
The backend emits seven SSE event types; `handleEvent` in `static/app.js` (ends line 794) handles
five. Dropped on the floor:

| Event | Emitted at | User impact of dropping |
|---|---|---|
| `warning` | `orchestrator.py:786` | Roster silently truncated at the 8-member cap, user never told |
| `shutdown` | `orchestrator.py:420`, `main.py:141` | Server shutting down mid-run — stream just stops with no explanation |

### Change

`static/app.js` — add two branches inside `handleEvent`, before its closing brace at line 794.
`showToast` is already defined in this file.

```js
  if (ev.type === 'warning') {
    showToast(ev.message || 'Council warning.');
    panel.appendChild(Object.assign(document.createElement('div'), {
      className: 'status-card',
      innerHTML: `<div class="status-line status-warn">${escapeHtml(ev.message || '')}</div>`
    }));
    return;
  }

  if (ev.type === 'shutdown') {
    showToast(ev.message || 'Server is shutting down.');
    panel.appendChild(Object.assign(document.createElement('div'), {
      className: 'status-card',
      innerHTML: `<div class="status-line status-bad">${escapeHtml(ev.message || 'Server shutdown requested.')}</div>`
    }));
    return;
  }
```

**No CSS change is needed.** Both classes already exist — verified at `static/style.css:462-463`:
```css
.status-bad { color: var(--danger); }
.status-warn { color: var(--warm); }
```
Do not re-add them; a duplicate rule is the kind of thing the ponytail audit flags later.

### Verification (must pass)

```bash
cd <repo-root>
node --check static/app.js && echo "SYNTAX OK"
grep -n "status-warn" static/style.css   # must exist after the change
```

Runtime check in the browser console with the server running:
```js
const p = document.getElementById('councilPanel');
handleEvent({type:'warning', message:'test warning'}, p);
handleEvent({type:'shutdown', message:'test shutdown'}, p);
// both must render a visible status card; neither may throw
```

---

## Task 9 — Reconcile documentation with the code

**Severity: Low. Pure documentation, no behaviour change. Do this last** so it records the
post-fix state.

`CLAUDE.md` contains stale claims that will actively mislead future work:

| Claim in CLAUDE.md | Actual code | Source of truth |
|---|---|---|
| `COUNCIL_ENABLE_PYTHON_TOOL` default `true` | `false` | `orchestrator.py:306`, `main.py:116` |
| `COUNCIL_CORS_ORIGINS` default `*` | localhost allowlist | `main.py:105-111` |
| `COUNCIL_MAX_RECENT_RUNS` default `20` | `200` | `metrics_store.py:35` |
| Env var table lists 5 | 22 are read in code | grep `getenv(` |
| "102 tests passing" | 127 (more after this plan) | `pytest tests/ -q` |
| "`index.html` ~1300 lines, HTML/CSS/JS co-located" | split into 3 files | `static/` |
| "`memory_graph.py` — NetworkX triple store" listed as a key file | **zero importers** | `grep -rn memory_graph --include=*.py` |

### Actions

1. Correct all defaults in the env var table, and add the currently-undocumented ones — at minimum
   `COUNCIL_PROJECT_ROOT` (it is a security control and is invisible today), `COUNCIL_API_KEY`,
   `COUNCIL_HOST`, `COUNCIL_LLM_TIMEOUT`, `COUNCIL_MAX_PARALLEL_MEMBERS`, `COUNCIL_ALLOW_URL_FETCH`,
   `COUNCIL_SMART_PHASE_THRESHOLD`, plus the new `COUNCIL_DB_PATH` (Task 1),
   `COUNCIL_MEMORY_RELEVANCE_FLOOR` (Task 5) and `COUNCIL_ENABLE_WEB_SEARCH` (Task 7).
2. Update the Key Files table: `static/index.html` is now three files; drop or explicitly mark
   `memory_graph.py`.
3. **Delete `memory_graph.py`** — it has no importers, and CLAUDE.md's own note says Phase 2
   intentionally replaced it with `memory_store.py`. That migration is complete. Verify first:
   ```bash
   grep -rn "memory_graph" --include="*.py" . | grep -v "/venv/"   # must return nothing
   ```
   If that is empty, delete the file and re-run the suite.
4. Correct the "3-phase pipeline" description. `deep_debate` defaults to **False**
   (`orchestrator.py:814`), so the default path is **two phases**: Phase 2 cross-review is bypassed
   unless the user ticks Deep Debate. State this plainly — the current text describes the
   non-default path as if it were the default. Note the consequence: `smart_phase.py` never
   executes on a default run.

### Verification
```bash
cd <repo-root>
./venv/bin/pytest tests/ -q         # unchanged pass count after the memory_graph.py deletion
./venv/bin/python3 tools/ponytail_audit.py | tail -3
```

---

## Explicitly out of scope

Do **not** attempt these without asking the repo owner first:

- **Refactoring `orchestrator.py`** (1036 lines, `_stream_llm_to_queue` complexity 36). It is the
  correct target eventually, but it is the highest-risk file in the repo, it carries the retry,
  streaming, tool-recursion, metrics and persistence paths simultaneously, and 11 tests depend on
  its exact structure. Not a drive-by change.
- **Flipping `deep_debate` to default True.** That changes the product's core behaviour and
  latency profile. It is a product decision, not a bug fix.
- **Splitting `static/app.js` (1139 lines) or `style.css` (810).** There is no bundler; a split
  means new `<script>` tags and load-order risk for no functional gain right now.
- **Widening `scrub_secret_values` patterns.** Tempting after Task 2, but false positives there
  corrupt legitimate run history. Task 2 fixes the actual leak at the source.

---

## Final acceptance

```bash
cd <repo-root>

# 1. Full suite green, no production DB writes
BEFORE=$(./venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('council_runs.db').execute('SELECT COUNT(*) FROM runs').fetchone()[0])")
./venv/bin/pytest tests/ -q
AFTER=$(./venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('council_runs.db').execute('SELECT COUNT(*) FROM runs').fetchone()[0])")
[ "$BEFORE" = "$AFTER" ] && echo "DB isolation OK" || echo "FAIL: tests still write to production DB"

# 2. Frontend parses
node --check static/app.js

# 3. Server boots and serves
PYTHONPATH=src ./venv/bin/python3 -m uvicorn council.main:app --host 127.0.0.1 --port 8799 &
sleep 4
curl -s -o /dev/null -w "root %{http_code}\n"    http://127.0.0.1:8799/
curl -s -o /dev/null -w "catalog %{http_code}\n" http://127.0.0.1:8799/models/catalog
curl -s -o /dev/null -w "memory %{http_code}\n"  http://127.0.0.1:8799/council/memory
kill %1
```

**Report back per task:** what changed, the verification command you ran, and its actual output.
A task whose verification command was never executed is not done — say so plainly rather than
assuming it passes.
