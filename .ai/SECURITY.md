# Security Requirements — LLM Council

## Default trust model

The app is a trusted single-user, localhost-first tool. Public or LAN deployment is an advanced configuration and requires `COUNCIL_API_KEY`.

## Required controls

- Default host: `127.0.0.1`; default CORS: localhost allowlist.
- Cloud API keys are request-scoped via `cloud_keys.scoped_cloud_keys()`; never persist or log them.
- Apply `redact_config()` before storing/exporting roster or configuration data.
- Do not ingest secret-bearing files (`.env*`, private keys, credential files) into prompts or databases.
- Keep remote URL fetch disabled unless `COUNCIL_ALLOW_URL_FETCH=true`.
- Keep dispute-resolution web search disabled unless `COUNCIL_ENABLE_WEB_SEARCH=true`.
- Keep Python tool execution disabled unless `COUNCIL_ENABLE_PYTHON_TOOL=true`; it is privileged functionality.
- Enforce upload size/count limits and folder-ingest cap.
- When `COUNCIL_PROJECT_ROOT` is set, every local path route must confine paths to it.
- Escape any LLM- or attachment-controlled text rendered in the browser.

## Change checklist

For any route, ingestion, serialization, or UI change, answer:

1. Could it read outside the intended project/filesystem boundary?
2. Could it send data off-machine by default?
3. Could it persist, log, export, or render a secret?
4. Does it accept LLM-controlled content in HTML, a command, SQL, or a path?
5. Does it preserve API-key protection and safe defaults?

If any answer is yes, add a regression test covering the protective behavior.

