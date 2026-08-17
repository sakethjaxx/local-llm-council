# AI-Assisted Development Guardrails — LLM Council

Adapted for this repository from the project-supplied AI-assisted development guardrails. These rules apply to every AI-assisted change.

## Human ownership

AI accelerates implementation; it does not own architecture, security, business policy, data integrity, production readiness, or final approval. Never merge code that a human reviewer cannot explain: what changed, why, data flow, assumptions, failure modes, tests, and rollback.

## Scope and architecture

Before editing, define the exact problem, expected files, acceptance criteria, edge cases, and non-goals. Make the smallest reasonable change. Do not rewrite modules, change public APIs, add frameworks, or mix cleanup with feature work unless explicitly requested.

New layers, services, packages, caches, queues, models, or infrastructure require a documented current need, reason the existing design is insufficient, operational cost, failure modes, and simpler alternatives considered. Avoid speculative abstractions, duplicate layers, circular dependencies, hidden global state, and business logic in routes/UI/database callbacks.

## Security and privacy

Security-sensitive work—including auth, files, external URLs, database writes, LLM tools, secrets, and user-controlled content—requires explicit review. Use server-side authorization, parameterized queries, validation, allowlists, size/type/content restrictions, least privilege, deny-by-default behavior, and safe failures. Never hard-code or log secrets.

For this application specifically, preserve local-only defaults, API-key protection for non-local binds, project-root confinement, secret-file exclusion, HTML escaping, and disabled-by-default URL fetch, web search, and Python execution.

## Data, LLMs, and performance

Writes must account for validation, uniqueness, referential integrity, transactions, partial failure, retries, concurrent access, migration safety, and rollback. Retried operations should be idempotent; destructive migrations need backup, validation, staged deployment, and rollback plans.

Treat LLM output as untrusted. Validate structured output, set timeout/token/cost limits, define retries, prevent loops, bound tool permissions, separate system and user content, resist prompt injection, and keep sensitive data out of prompts unless explicitly approved. Never let an LLM execute privileged/destructive operations without authorization.

Avoid unbounded queries, whole-table/file loads, N+1 patterns, duplicated model/external calls, blocking request work, and oversized prompts. Any externally billed or off-machine call must be intentional, measured, and opt-in when it changes the local-first default.

## Dependencies, freshness, errors, and observability

Do not add a package merely because generated code imports it. Verify maintenance, runtime compatibility, license, duplication, transitive footprint, and security posture; explain each production dependency in the PR. Verify APIs against official documentation and installed versions; avoid deprecated or undocumented patterns.

Do not silently swallow errors. Preserve safe diagnostic context, distinguish retryable/final errors, avoid corrupting state, and give users a safe message. Production-facing work needs proportionate structured logs, metrics/health checks, and identifiers that aid diagnosis without exposing payloads or secrets.

## Tests and review

AI-generated code is incomplete without behavior-focused tests. Cover expected and invalid input, permissions, boundaries, empty states, retries/duplicates, dependency and timeout failures, partial failures, and concurrency where relevant. Run all applicable repository checks; never suppress a failing test or security finding just to pass CI.

Prefer small, single-purpose PRs. Split large changes into interface/schema, implementation, integration, tests, and cleanup when feasible.
