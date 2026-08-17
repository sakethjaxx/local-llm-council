# Testing Guide — LLM Council

## Commands

```bash
./venv/bin/pytest tests/ -q
node --check static/app.js
./venv/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8799
```

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
