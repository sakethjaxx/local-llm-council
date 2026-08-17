# Pull Request Checklist

## Summary

- Problem:
- User-facing outcome:
- Scope intentionally excluded:
- Assumptions, edge cases, and rollback plan:

## Safety and architecture

- [ ] Local-first default is preserved.
- [ ] No cloud/network behavior was added to a default path.
- [ ] Keys, tokens, and secrets are not persisted, logged, exported, or injected into HTML.
- [ ] Paths, uploads, and auth retain their existing security boundaries.
- [ ] No SQLite schema change was made without an idempotent migration.
- [ ] No duplicate embedding model or dependency-graph implementation was introduced.
- [ ] New dependencies (if any) are justified, maintained, compatible, and license-reviewed.
- [ ] New persistence writes are validated, idempotent where retries are possible, and preserve data integrity.
- [ ] LLM output is treated as untrusted; timeouts, limits, retries, and tool permissions are bounded.

## Verification

- [ ] Focused regression tests added/updated.
- [ ] `./venv/bin/pytest tests/ -q`
- [ ] `node --check static/app.js` (if JavaScript changed)
- [ ] Manual endpoint/UI verification recorded where relevant.
- [ ] Docs and `env.example` updated for public configuration changes.
- [ ] Errors have a safe user-facing outcome and structured, non-sensitive diagnostic logging.
