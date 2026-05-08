# LLM Council

Local-first multi-model review and decision engine built with FastAPI, LiteLLM, and Ollama.

It runs a small council of specialist models in parallel, optionally lets them cross-review each other, and then produces a chairman verdict. The current build is aimed at **controlled demos** and local evaluation, not public multi-tenant deployment.

## What It Does

- Runs a 3-seat council plus chairman over a prompt or project brief
- Streams responses live in the web UI
- Supports local Ollama model rosters with hardware-aware defaults
- Accepts text plus uploaded files: `md`, `json`, `txt`, `pdf`, common code files, and images
- Includes demo presets, sample inputs, and preflight checks
- Tracks run metrics and exposes recent run summaries
- Builds a project dependency graph for local analysis

## Demo-Ready Path

The app now includes a stable demo workflow in the web UI:

- `Fast Triage`
- `Code Review`
- `Vision Review`

Each preset provides:

- a recommended roster
- toggle defaults
- starter topic text
- optional bundled sample files

Before launch, the UI runs a preflight check against the active roster and warns about:

- missing Ollama models
- image attachments without a vision-capable seat
- oversized attachment batches that may slow a live demo

If `Dynamic Swarm` fails or selects models that are not installed, the app falls back to the stable roster instead of hard failing.

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies.
3. Make sure Ollama is installed and running.
4. Pull the models you plan to demo.
5. Start the FastAPI app.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

## Recommended Local Models

For controlled demos, preinstall the exact models used by your preset.

Example pulls:

```bash
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b
ollama pull gemma2:2b
ollama pull gemma2:9b
ollama pull gemma3:4b
ollama pull llama3.2:3b
ollama pull llama3.1:8b
ollama pull deepseek-r1:8b
```

## Environment

Copy `env.example` to `.env`.

API keys are optional for the default local-first path. Ollama-only demos do not require OpenAI, Anthropic, Gemini, OpenRouter, or Groq keys.

Important flags:

- `COUNCIL_CORS_ORIGINS`
- `COUNCIL_ENABLE_PYTHON_TOOL`
- `COUNCIL_METRICS_FILE`
- `COUNCIL_MAX_RECENT_RUNS`
- `COUNCIL_BOOTSTRAP_LOCAL_MODELS`

## Main Endpoints

- `GET /health`
- `GET /hardware/suggest`
- `GET /ollama/status`
- `POST /ollama/check`
- `POST /ollama/bootstrap`
- `POST /council/stream`
- `POST /council/chat`
- `GET /council/memory`
- `GET /project/code-graph`
- `GET /demo/catalog`
- `GET /metrics/runs`
- `GET /metrics/summary`

## File Inputs

The council accepts uploaded attachments through the web UI.

Supported prompt-folded files:

- Markdown
- JSON
- Text
- PDF
- Common code/config files like `py`, `js`, `ts`, `html`, `css`, `yaml`, `yml`

Supported image flow:

- Images are only useful when at least one selected seat is using a known vision-capable model
- The preflight check warns if images are attached but the roster has no vision-capable seat

## Testing

Run the targeted unit suite with:

```bash
python -m unittest tests.test_main tests.test_orchestrator tests.test_input_and_router
```

## Security Notes

This project is intended for local or otherwise trusted environments.

If you expose it publicly:

- disable the Python execution tool with `COUNCIL_ENABLE_PYTHON_TOOL=false`
- do not rely on local host execution as a sandbox boundary
- treat uploaded files and prompted code execution as sensitive attack surfaces

## Current Scope

Good fit:

- local demos
- architectural review
- code review experiments
- comparing local model rosters

Not yet a strong fit:

- public SaaS deployment
- untrusted multi-user hosting
- production-grade workflow enforcement without more hardening
