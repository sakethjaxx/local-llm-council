# SCOPE — Final Target

## Decision: (A) Local single-user tool

The final target is a **local, single-user council** running on the user's own machine
against their own Ollama instance. Free of cost in the default path, per `CLAUDE.md`.

**(B) self-hostable multi-user** is a documented *advanced deployment*, not a core
requirement. The pieces that already exist for it stay as-is and are not expanded:

- `COUNCIL_API_KEY` — optional header auth for non-localhost binds (kept, not extended)
- CORS allowlist via `COUNCIL_CORS_ORIGINS` (kept)
- Per-request cloud keys via headers, never persisted server-side (kept)

## What this rules out (anti-scope)

- No auth systems, sessions, or user accounts
- No multi-tenancy or per-user data isolation
- No horizontal scaling, queues, or worker pools
- No heavy frontend framework — buildless ES modules only
- No unbounded debate loops — rebuttal stays one round
- No cloud calls in any default flow

## Priorities (ranked for scope A)

1. Deliberation quality is provable, not vibes — stance reliability, grounding enforcement,
   honest confidence signal.
2. A first-time user with zero models reaches a working council entirely in-app.
3. The run view tells the deliberation story: stances → gate → debate → grounded verdict.
4. Feedback visibly changes future runs (skill confidence responds to ratings).

See `REALITY_REPORT.md` for what live validation has and has not covered.
