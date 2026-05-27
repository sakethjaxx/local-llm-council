# Contributing

Thanks for helping improve LLM Council. Keep contributions focused, testable, and aligned with the local-first product direction.

## Development Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp env.example .env
./venv/bin/pytest tests/ -q
```

Ollama is required for real council runs, but most unit tests use stubs and should pass without a running model server.

## Pull Request Expectations

- Describe the user-facing problem and the implementation approach.
- Keep unrelated refactors out of feature or bug-fix PRs.
- Add or update tests for behavior changes.
- Run `./venv/bin/pytest tests/ -q` before opening a PR.
- Document new environment variables, endpoints, or security-sensitive behavior.

## Project Direction

The default product target is a single-user, local-first, self-hosted review tool. Multi-user RBAC, hosted SaaS behavior, and cloud-only defaults are out of scope for early releases.
