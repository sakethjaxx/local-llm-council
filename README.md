# LLM Council

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-pytest-green)
![Runtime](https://img.shields.io/badge/runtime-local--first-informational)

LLM Council is a local-first multi-model review and decision engine with a FastAPI backend and web UI. It is for developers, researchers, and advanced users who want to compare, critique, and combine model outputs on their own machine or controlled infrastructure.

## 30-Second Pitch

Run several local or optional cloud LLMs as a structured review council. Each model analyzes the same topic, optionally critiques the others, and a chairman model produces a final verdict with risks and actions. The default path is local-first with Ollama, persistent run history, replay/export, and guardrails for self-hosted open-source use.

## Table of Contents

- [What It Does](#what-it-does)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Deployment Modes](#deployment-modes)
- [Security Notes](#security-notes)
- [Architecture](#architecture)
- [Testing](#testing)
- [Contributing](#contributing)

## What It Does

- Runs a council of local and optional cloud models in parallel, then produces a final synthesized verdict.
- Streams council progress live in the browser and supports prompt, file, and image-assisted workflows.
- Persists runs for replay, export, feedback, and metrics tracking.
- Uses Ollama for local model execution and supports configurable model rosters and token budgets.

## Quick Start

```bash
git clone <repo-url>
cd local-llm-council
./start.sh        # Windows: .\start.ps1
```

Then open http://localhost:8765. The script creates the venv, installs dependencies, sets up `.env`, and checks for Ollama.

Need a local model? Install [Ollama](https://ollama.com/download) and run `ollama pull llama3.2` — the app tells you exactly which models it needs if any are missing. See `docs/FIRST_RUN.md` for a walkthrough.

### Docker

```bash
COUNCIL_API_KEY=change-me docker compose up
```

Starts the API plus an Ollama container and auto-pulls required models on first run.

## Configuration

| Variable | Description |
| --- | --- |
| `OLLAMA_BASE_URL` | Ollama server URL. Defaults to `http://localhost:11434`. |
| `COUNCIL_HOST` | Host interface for the FastAPI server. Defaults to `127.0.0.1` for local-only access. |
| `COUNCIL_PORT` | Port used by the FastAPI server. Defaults to `8765`. |
| `COUNCIL_API_KEY` | Optional API key required for authenticated access when binding to non-localhost. |
| `COUNCIL_ALLOW_URL_FETCH` | Enables remote URL fetching for council inputs. Disabled by default because it increases attack surface. |
| `COUNCIL_ENABLE_PYTHON_TOOL` | Enables the Python REPL tool for phase-1 execution. Disabled by default. |
| `COUNCIL_MAX_UPLOAD_MB` | Maximum size for a single uploaded attachment in MB. Defaults to `20`. |
| `COUNCIL_MAX_FILES` | Maximum number of uploaded attachments per run. Defaults to `10`. |

## Deployment Modes

- Local only (default, no auth needed): `COUNCIL_HOST=127.0.0.1`
- LAN/VPS: must set `COUNCIL_API_KEY`.

## Security Notes

- Cloud API keys are stored in browser `localStorage`. Use them only on trusted machines and browsers.
- The Python tool is disabled by default, requires Docker on the host, and is intended for advanced users only.
- URL fetching is disabled by default. Enable it with `COUNCIL_ALLOW_URL_FETCH=true` only if you understand the SSRF risk.

## Architecture

LLM Council is a FastAPI application that orchestrates multiple model seats, streams intermediate output to a browser UI, persists run state and metrics locally, and can use Ollama-backed local models with optional cloud providers layered in. See `docs/ARCHITECTURE.md` for details.

## Testing

```bash
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/pytest tests/ -q --ignore=tests/eval
```

The local eval harness under `tests/eval/` is separate because it requires Ollama and a pinned local model.

## Docs

- `docs/FIRST_RUN.md` — Ollama setup walkthrough
- `docs/API.md` — HTTP endpoints with curl examples
- `docs/CUSTOMIZATION.md` — personas, providers, prompts
- `docs/TROUBLESHOOTING.md` — common issues and fixes
- `docs/ARCHITECTURE.md` — how it works

## Contributing

Contributions are welcome. See `CONTRIBUTING.md` for the development workflow and `SECURITY.md` for reporting vulnerabilities.
