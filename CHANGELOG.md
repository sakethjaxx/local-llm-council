# Changelog

All notable changes to this project will be documented here.

## Unreleased

### Reliability & audit hardening
- Added a per-call `timeout` (`COUNCIL_LLM_TIMEOUT`, default 180s) to every LLM request so a hung provider can no longer stall a run.
- Bounded council concurrency with a semaphore (`COUNCIL_MAX_PARALLEL_MEMBERS`, default 4) and a hard roster cap (`COUNCIL_MAX_MEMBERS`, default 8) to prevent unbounded fan-out.
- Failed members are now surfaced as `errored` in the stream and persisted; runs with any member failure finish as `partial` instead of silently `completed`.
- Runs interrupted by client disconnect now cancel in-flight member tasks and finalize as `cancelled` (no more stuck `running` rows or leaked provider calls).
- Guarded the shared embedder singleton against a startup init race.
- Sandbox REPL now uses a unique per-invocation temp file (no cross-run collision) plus memory/CPU/PID/no-new-privileges limits; fixed the misleading timeout message.
- Chairman JSON parsing gained a tolerant repair tier (prose-wrapped / trailing-comma output); specificity scoring now distinguishes unparseable output from a merely vague one.
- Malformed `council_config` now emits a warning to the client instead of failing silently.

- Hardened local-first defaults for OSS sharing.
- Added API-key dependency support, upload limits, URL-fetch controls, and safer markdown rendering.
- Added run persistence, export, replay, metrics, memory, and skill-registry improvements.
- Added packaging and contributor documentation groundwork.
