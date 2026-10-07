# Testing Guide — LLM Council

## Commands

```bash
# Backend (hermetic: temp DB, empty COUNCIL_ENV_FILE, pinned GPU size; no Ollama/Docker needed)
python -m pytest tests/ -q --ignore=tests/eval

# Frontend logic and syntax
node --test tests/frontend.test.cjs
for f in src/council/static/js/*.js src/council/static/app.js; do node --check "$f"; done

# Vendored browser libraries match their pinned packages; dependency audits
npm ci --prefix tools/frontend && node tools/vendor_frontend.cjs --check && npm audit --prefix tools/frontend
pip-audit -r requirements.txt

# Live sandbox container (needs Docker and `docker pull python:3.11-slim`)
COUNCIL_TEST_DOCKER=1 python -m pytest tests/test_tool_repl.py -k Live
```

### Browser checks (synthetic inference)

Start an isolated server, then run the Playwright suite (needs `npx playwright install chromium`):

```bash
COUNCIL_PORT=8799 COUNCIL_DB_PATH=/tmp/council-ui.db council-serve   # or: python run.py
COUNCIL_PREVIEW_URL=http://127.0.0.1:8799 NODE_PATH=tools/frontend/node_modules node tools/verify_ui.cjs
```

It checks 1440, 768, 390 and 320 px layouts for overflow, every dialog, keyboard operation and focus
return, axe-core accessibility (serious/critical findings fail), remote-resource blocking in Markdown,
streaming and action items. Any page exception or console error, including CSP violations, fails it.

### User-acceptance suite (real models, installed wheel)

```bash
python -m build && python -m venv .audit-tmp/u && .audit-tmp/u/Scripts/pip install dist/*.whl   # bin/ on Linux/macOS
.audit-tmp/u/Scripts/python tests/uat/run_uat.py --model ollama/qwen2.5:3b --browser
```

Needs a running Ollama with the model pulled. It boots the installed `council-serve` from a temp
directory and drives the CLI, HTTP API and browser end to end; see `tests/uat/run_uat.py`.

The evaluation harness in `tests/eval/` is separate and requires Ollama.

## Test principles

- Run the full test suite for every behavior change.
- Add narrow tests next to the affected subsystem (`test_io_parser.py`, `test_main.py`, etc.).
- Exercise real SQLite via `SQLiteMemory(":memory:")` or a temporary database; do not mock store internals.
- Test module-level singleton users only after `tests/conftest.py` has redirected `COUNCIL_DB_PATH`.
- Mock network/LLM boundaries, not the business logic around them.
- Assert negative security invariants: no LLM call while web search is disabled, no secret reaches a formatted prompt, and confined paths reject escapes.
- Cover relevant invalid input, empty/boundary states, duplicate/repeated requests, dependency failures, timeouts, partial failures, and concurrent writes.
- Test behavior and contracts, not implementation lines or coverage totals.
- Do not weaken/skip failing checks or add broad suppressions merely to make CI pass.

## Minimum verification by change type

| Change | Required verification |
|---|---|
| Backend behavior | focused test + full `pytest` |
| Database/schema | migration test + full `pytest` |
| Frontend JavaScript | `node --check` + relevant browser/manual check |
| Security boundary | regression test proving rejection/no-op |
| Environment variable | default and enabled/override behavior tests |
| New dependency/API | installed-version and supported-usage verification |
