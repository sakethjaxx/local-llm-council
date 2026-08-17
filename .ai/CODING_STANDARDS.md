# Coding Standards — LLM Council

## Python

- Prefer small, typed functions and explicit names over new abstraction layers.
- Keep I/O at module boundaries; use `asyncio.to_thread()` for blocking filesystem/CPU work from async routes.
- All LiteLLM calls must set the standard timeout and expand `litellm_kwargs_for_model(model)`.
- Use `caps_for(model)` rather than hard-coding provider behavior.
- Use `get_logger(__name__)`; do not use `print()` in runtime code.
- Keep exception handling narrow and logged with non-sensitive context.
- Do not silently swallow failures. Distinguish retryable from final failures and return a safe, useful user-facing outcome.
- Use `pathlib` or validated absolute paths for new filesystem code; never rely on user input remaining inside a project root.

## Persistence

- Use `db_connect()` and parameterized SQLite queries.
- Add idempotent migrations before relying on new database columns.
- Store redacted configs only. Treat prompts, attachments, and model output as potentially secret-bearing.
- Preserve existing `""` no-op return contracts for optional context providers.
- For writes, define validation, uniqueness, referential integrity, transaction/partial-failure behavior, retries, and idempotency. Prefer database constraints where they fit.

## Dependencies and APIs

- Add a dependency only after confirming it is maintained, compatible, licensed acceptably, non-duplicative, and justified over the standard library/current stack.
- Record the reason, transitive-cost tradeoff, and any security review in the PR.
- Verify generated SDK/library usage against official documentation and installed versions; do not introduce deprecated or undocumented APIs.

## LLM behavior

- Treat all model output as untrusted input and validate structured output with schemas.
- Set timeouts, token limits, bounded retries, and bounded tool permissions.
- Separate system instructions from user-controlled content and defend against prompt injection.
- Never let an LLM trigger privileged or destructive operations without explicit authorization and bounded controls.

## Frontend

- Keep browser code dependency-free and compatible with direct script loading.
- Use `escapeHtml()` for untrusted text and restrict values interpolated into style attributes.
- Prefer DOM APIs when practical; if using `innerHTML`, escape/sanitize every untrusted value.
- Keep the existing event protocol in sync with `handleEvent()`.

## Documentation

- Add environment variables to `env.example`, `CLAUDE.md`, and `.ai/` when they alter deployment or security behavior.
- Describe defaults accurately. A capability that sends data off-machine must state whether it is opt-in.
