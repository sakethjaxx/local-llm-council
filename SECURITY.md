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

- `COUNCIL_HOST` defaults to `127.0.0.1`.
- Set `COUNCIL_API_KEY` before binding to LAN or public interfaces.
- Remote URL fetching is disabled unless `COUNCIL_ALLOW_URL_FETCH=true`.
- The Python execution tool is disabled by default and requires Docker when enabled.
- Browser-stored cloud keys are appropriate only on trusted machines and browsers.

## Known Non-Goals

Early releases do not provide multi-user RBAC, tenant isolation, or a hardened browser key vault.
