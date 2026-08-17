# AI Agent Instructions — LLM Council

Read `.ai/ARCHITECTURE.md`, `.ai/SECURITY.md`, `.ai/TESTING.md`, and
`.ai/VIBE_CODING_GUARDRAILS.md` before changing runtime code. AI-generated code
is an untrusted draft until a human can explain, review, and validate it.

## Non-negotiables

- Preserve the local-first default: Ollama and local libraries only. Cloud models require a user-supplied scoped key.
- Keep outbound capabilities opt-in: URL fetch and web search default to `false`.
- Never log, persist, export, or render credentials. Use `redact_config()` at serialization boundaries.
- Use the shared `embeddings.get_embedder()` singleton. Never instantiate `SentenceTransformer` elsewhere.
- Preserve SQLite compatibility. Any schema change requires an idempotent migration path.
- Do not weaken path confinement, upload limits, CORS, API-key checks, or HTML escaping.
- Keep changes scoped. Do not refactor `orchestrator.py`, split the vanilla frontend, or alter product defaults without an explicit request.
- Do not add a framework, dependency, service layer, cache, queue, or abstraction without documenting the current problem, simpler alternative, failure modes, and operational cost.

## Workflow

1. Define the problem, expected files, acceptance criteria, edge cases, and rollback path before editing.
2. Inspect affected call sites and tests before editing.
3. Add a focused regression test for every behavior/security fix.
4. Run `./venv/bin/pytest tests/ -q` and `node --check static/app.js` when frontend code changes.
5. Update `.ai/` and `env.example` for new endpoints, defaults, dependencies, or security-relevant environment variables.
6. Report changed files, verification commands/results, assumptions, failure modes, and known limitations.

## Repository conventions

- Python 3.12+; use the project `./venv`.
- Backend uses FastAPI, Pydantic, `asyncio`, and LiteLLM.
- Frontend has no bundler: `static/index.html`, `static/app.js`, and `static/style.css` load directly.
- Tests use pytest/unittest and real temporary or in-memory SQLite databases; never mock the database layer.
