# Security Policy

## Supported Versions

Security fixes target the current `main` branch until versioned releases are published.

## Reporting a Vulnerability

Please report vulnerabilities privately by opening a GitHub security advisory when the repository is public. If advisories are not enabled yet, contact the maintainer privately before filing a public issue.

Include:

- affected version or commit
- reproduction steps
- expected impact
- whether the issue requires non-default configuration

## Security Model

LLM Council is local-first software for trusted single-user environments by default. Treat public exposure as advanced self-hosting.

### Request boundary (before any body is parsed)

- `COUNCIL_HOST` defaults to `127.0.0.1`. Without `COUNCIL_API_KEY`, only loopback clients with a `localhost`/`127.0.0.1` Host header are served (DNS-rebinding protection).
- With `COUNCIL_API_KEY` set, every request except the UI shell (`GET /`, `/static/*`, `/demo-samples/*`) and CORS preflights must send `X-API-Key`; it is compared in constant time **before** the request body is read, so unauthenticated clients cannot make the server parse uploads.
- Request bodies are capped at 52 MiB, by `Content-Length` and by bytes actually received (chunked uploads included): larger requests get `413`. Per-file (`COUNCIL_MAX_UPLOAD_MB`) and file-count limits still apply.
- Runs (`/council/stream`, `/council/review-project`, `/council/chat`) reserve one of `COUNCIL_MAX_CONCURRENT_RUNS` slots atomically before the body is read and hold it until the stream ends; a full server answers `429`.
- Cross-site browser requests are rejected unless their origin is the server itself or listed in `COUNCIL_CORS_ORIGINS`.
- Responses carry a Content-Security-Policy that only allows this origin (no third-party scripts, images, fonts or connections), plus `nosniff`, `no-referrer` and `frame-ancestors 'none'`. Rendered model Markdown cannot load remote images or other resources.

### Data handling

- Secret-looking values (API keys, tokens, JWTs, bearer headers) are redacted from streamed output (also when split across chunks), chat, error messages, logs, stored runs and feedback, metrics, memory, skills, replays and exports. Credential-named config fields are dropped; numeric usage counters are kept.
- `.env`, `*.env`, key/certificate files and credential directories are excluded from uploads, folder ingestion, project review and the code graph; paths are resolved and confined to `COUNCIL_PROJECT_ROOT` without following symlinks out of it.
- Configuration is loaded only from the process environment, `COUNCIL_ENV_FILE`, or this checkout's own `.env` — never from the directory the server or CLI is started in.

### Untrusted content and tools

- Remote URL fetching is disabled unless `COUNCIL_ALLOW_URL_FETCH=true`; fetches are pinned to validated public addresses.
- PDFs are parsed in a disposable child process with a 10-second deadline, a 100-page cap and a 768 MiB memory ceiling (Linux `RLIMIT_AS`, Windows Job Object). Where the ceiling cannot be enforced (macOS), PDF extraction is refused unless `COUNCIL_PDF_ALLOW_UNLIMITED_MEMORY=true`.
- Code-graph processing is bounded (1 MiB per file, 16 MiB total, 4,000 files, 20,000 edges) and reports truncation.
- The Python tool is off by default (`COUNCIL_ENABLE_PYTHON_TOOL`). When on, every tool call is re-authorized at execution time (opt-in, model capability, phase, depth, arguments) and runs in a fresh, uniquely named Docker container with no network, a read-only filesystem, no capabilities, 256 MiB of memory, a 10-second deadline, 64 KiB of output, and guaranteed removal. Pull the image once with `docker pull python:3.11-slim`.

### Authenticated LAN deployment

Binding to anything other than localhost requires all of:

1. `COUNCIL_API_KEY` set to a long random value (the server refuses to start on a non-localhost host without it). Enter the same key in the UI's **Connection** dialog.
2. `COUNCIL_HOST` set to the interface to listen on, and `COUNCIL_CORS_ORIGINS` listing the exact origin users open (for example `http://council.lan:8765`).
3. `COUNCIL_PROJECT_ROOT` set to the only directory tree the server may read for project review and folder ingestion.
4. TLS in front of the server (a reverse proxy) if the network is not fully trusted: the API key travels in a header.
5. Python tool and URL fetching left off unless every user on the network is trusted with them.

Browser-entered cloud keys stay in that tab's memory only; use them on trusted machines.

### Known residual risks

- The UI wires controls with inline event handlers, so the CSP must allow `'unsafe-inline'` scripts. Model output is sanitized with DOMPurify, but a sanitizer bypass would not be stopped by the CSP. Moving handlers to listeners would remove this.
- Secret redaction is pattern-based: it catches common key formats, not every possible credential.
- One API key protects everything; there are no per-user accounts or audit trails.

## Known Non-Goals

Early releases do not provide multi-user RBAC, tenant isolation, or a hardened browser key vault.
