# LLM Council

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-pytest-green)
![Runtime](https://img.shields.io/badge/runtime-local--first-informational)

LLM Council is a local-first multi-model review and decision engine with a FastAPI backend and web UI. It is for developers, researchers, and advanced users who want to compare, critique, and combine model outputs on their own machine or controlled infrastructure.

## 30-Second Pitch

Run several local or optional cloud LLMs as a structured review council. Each model analyzes the same topic, optionally critiques the others, and a chairman model produces a final verdict with risks and actions. The default path is local-first with Ollama, persistent run history, replay/export, and guardrails for self-hosted open-source use.

## Table of Contents

- [What It Does](#what-it-does)
- [Quick Start](#quick-start)
- [Run A Council](#run-a-council)
- [Docker](#docker)
- [Configuration](#configuration)
- [Deployment Modes](#deployment-modes)
- [Security Notes](#security-notes)
- [Architecture](#architecture)
- [Testing](#testing)
- [Contributing](#contributing)

## What It Does

- Runs a council of local and optional cloud models in parallel, then produces a final synthesized verdict.
- Makes the deliberation visible and verifiable: every seat stakes an explicit stance
  (PROCEED/HOLD/MIXED), a consensus gate skips debate only on genuine unanimity, splits
  trigger cross-review plus one bounded rebuttal round, and the chairman's verdict is
  grounding-enforced — consensus claims that no member actually made are stripped.
- Reports an honest **Council Confidence** score (0–100) per run, combining seat
  diversity, agreement path, verdict grounding, and parse quality. A council of clones
  (all seats on one model) is capped at 45 and warned about — agreement between copies
  of the same model is weak evidence.
- Streams council progress live in the browser and supports prompt, file, and image-assisted workflows.
- Persists runs for replay, export, feedback, and metrics tracking. Thumbs-down feedback
  lowers the retrieval rank of skills learned from that run — ratings change future councils.
- Uses Ollama for local model execution and supports configurable model rosters and token budgets.

Two modes, honestly labeled: **Fast** (3 independent opinions, no debate) and
**Deliberate** (stance gate → cross-review → rebuttal → grounded verdict).

## Quick Start

The startup script is the easiest path. It creates the virtual environment, installs dependencies, copies `env.example` to `.env`, checks Ollama, and starts the FastAPI server.

```bash
git clone <repo-url>
cd local-llm-council
./start.sh
```

On Windows PowerShell:

```powershell
.\start.ps1
```

Then open http://localhost:8765.

Need a local model? Install [Ollama](https://ollama.com/download) and run `ollama pull llama3.2` — the app tells you exactly which models it needs if any are missing. See `docs/FIRST_RUN.md` for a walkthrough.

## Run A Council

1. Install Python 3.12+ and [Ollama](https://ollama.com/download).

2. Start Ollama. The desktop app usually starts it automatically; otherwise run:

```bash
ollama serve
```

3. Pull at least one local model:

```bash
ollama pull llama3.2
```

The app checks the configured council roster before each run. If a model is missing, the UI returns the exact `ollama pull ...` command to run. You can also set `COUNCIL_BOOTSTRAP_LOCAL_MODELS=true` in `.env` to let the app auto-pull local models.

4. Start the server from the repo root:

```bash
./start.sh
```

On Windows PowerShell:

```powershell
.\start.ps1
```

Manual start, useful when the virtual environment already exists:

```bash
python -m venv venv
./venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=src ./venv/bin/python -m llm_council.main
```

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\src"
.\venv\Scripts\python.exe -m llm_council.main
```

5. Open http://localhost:8765 in your browser.

6. Enter a topic or question, optionally attach files/images, choose Fast or Deep Debate, and press **Run Council**.

7. Watch the seats stream their analysis. Fast mode collects independent opinions and moves to the chairman. Deep Debate can add cross-review and one rebuttal round before the chairman verdict.

8. Review the final chairman verdict, grounded claims, council confidence, action items, and saved run history. Runs are stored locally in `council_runs.db`.

Quick health checks:

```bash
curl http://localhost:8765/health
curl http://localhost:8765/health/ready
curl http://localhost:8765/ollama/status
```

## Repository layout

Application code uses a standard `src/` package layout:

- `src/llm_council/` - Python package and FastAPI application
- `src/llm_council/web/static/` - buildless frontend assets
- `src/llm_council/resources/` - prompts, presets, and demo samples
- `tests/` - unit and integration tests
- `docs/` - architecture, API, and customization notes

On Windows PowerShell, use `curl.exe` if `curl` resolves to `Invoke-WebRequest`.

Optional direct API smoke test:

```bash
curl -N -X POST http://localhost:8765/council/stream \
  -F "topic_text=Should we ship this change?" \
  -F "deep_debate=false"
```

See `docs/FIRST_RUN.md` for a longer first-run walkthrough.

## Docker

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

- `docs/FIRST_RUN.md` — Ollama setup walkthrough (the UI also has an in-app guided setup)
- `docs/API.md` — HTTP endpoints with curl examples, full SSE event contract
- `docs/CUSTOMIZATION.md` — personas, providers, prompts
- `docs/TROUBLESHOOTING.md` — common issues and fixes
- `docs/ARCHITECTURE.md` — how it works
- `docs/SCOPE.md` — what this product is (and is not)
- `docs/REALITY_REPORT.md` — live-model validation results vs. code assumptions
- `docs/ROADMAP.md` — deliberately deferred work

## Contributing

Contributions are welcome. See `CONTRIBUTING.md` for the development workflow and `SECURITY.md` for reporting vulnerabilities.
