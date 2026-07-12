# Changelog

All notable changes to this project will be documented here.

## Unreleased

### Exposed-deployment hardening
- The Docker image now starts via `main.py` (default bind `127.0.0.1`), so the startup guard that requires `COUNCIL_API_KEY` before binding a non-localhost interface can no longer be bypassed. Exposing the container now requires both `COUNCIL_HOST=0.0.0.0` and an API key.
- Confined `review-project` / `code-graph` to `COUNCIL_PROJECT_ROOT` (default cwd) — arbitrary-filesystem reads are rejected with 403.
- Added a concurrent-council-run cap (429 when exceeded) on the streaming endpoints to bound resource/cost exhaustion.

### Grounding & summarization (NLP)
- The chairman now reports a `confidence` (0–10) and is instructed to ground claims in what members actually wrote and to treat web-search context as low-trust.
- Summarizer now overlaps chunks (cross-chunk references survive), hard-splits oversized single lines, and runs a reduce/consolidation pass so many-segment inputs collapse into one coherent brief.

### Answer quality (NLP)
- Fixed token counting for the local model fleet: non-OpenAI models (Ollama/Anthropic/Gemini) now apply a safety margin so budgets no longer silently overflow the real context window.
- Rebuilt the consensus gate: whole-document embedding (chunk + mean-pool, beating MiniLM's 256-token cap), gating on the **minimum** pairwise similarity so a single dissenter blocks the Phase 2 skip, plus a high-precision explicit-disagreement veto and richer calibration logging.
- Fair-share truncation in Phase 2 and Phase 3 so every member's analysis/review survives under context pressure instead of the last ones being dropped wholesale.
- The chairman is now told honestly when Phase 2 was skipped (and why, with the similarity score) instead of being fed fabricated "unanimous agreement" review stubs.

### Security (local-first)
- Value-level secret scrubbing: keys pasted into a topic/note/attachment or echoed by a model are now masked before they touch `council_runs.db`, `council_metrics.jsonl`, or exports.
- Capped `execute_python` tool-call recursion to stop an injected model looping the sandbox for DoS / cost amplification.

### Event-loop hygiene
- Moved blocking SQLite/file work off the event loop in the run/metrics endpoints, cached `index.html`, and offloaded Ollama model checks from the streaming path.
- Shutdown now drains active streams on any exit (Ctrl-C/SIGINT, SIGTERM, or normal), and dev auto-reload is opt-in (`COUNCIL_RELOAD`) instead of always on.

### Reliability & audit hardening
- Added a per-call `timeout` (`COUNCIL_LLM_TIMEOUT`, default 180s) to every LLM request so a hung provider can no longer stall a run.
- Bounded council concurrency with a semaphore (`COUNCIL_MAX_PARALLEL_MEMBERS`, default 4) and a hard roster cap (8) to prevent unbounded fan-out.
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
