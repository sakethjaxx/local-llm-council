# LLM Council

Local-first multi-model review and decision engine built with FastAPI, LiteLLM, and Ollama.

It runs a small council of specialist models in parallel, optionally lets them cross-review each other, and then produces a chairman verdict. The current build is aimed at **controlled demos** and local evaluation, not public multi-tenant deployment.

## What It Does

- Runs a 3-seat council plus chairman over a prompt or project brief
- Streams responses live in the web UI
- Supports local Ollama model rosters with hardware-aware defaults
- Supports optional cloud seats with browser-stored per-request API keys
- Accepts text plus uploaded files: `md`, `json`, `txt`, `pdf`, common code files, and images
- Includes demo presets, sample inputs, and preflight checks
- Supports token budget profiles: `Economy`, `Balanced`, `Performance`
- Tracks run metrics and exposes recent run summaries
- Persists runs for replay, feedback, and export
- Builds a project dependency graph for local analysis

## Demo-Ready Path

The app now includes a stable demo workflow in the web UI:

- `Fast Triage`
- `Code Review`
- `Image Review`

Each preset provides:

- a recommended roster
- toggle defaults
- starter topic text
- optional bundled sample files

Before launch, the UI runs a preflight check against the active roster and warns about:

- missing Ollama models
- image attachments without an image-capable seat
- oversized attachment batches that may slow a live demo

If `Dynamic Swarm` fails or selects models that are not installed, the app falls back to the stable roster instead of hard failing.

The UI also now includes:

- browser-side cloud key inputs for OpenAI, Anthropic, Gemini, and Groq
- token budget profile selection that changes actual phase token caps
- run replay for persisted runs
- local export of persisted runs as markdown, JSON, or zip

For repeatable demo validation, use:

- [demo_runner.md](/Users/sakethjaggaiahgari/Desktop/local-llm-council/demo_runner.md)
- [demo_scorecard_template.md](/Users/sakethjaggaiahgari/Desktop/local-llm-council/demo_scorecard_template.md)
- [demo_run_guide.md](/Users/sakethjaggaiahgari/Desktop/local-llm-council/demo_run_guide.md)
- [self_improvement_guide.md](/Users/sakethjaggaiahgari/Desktop/local-llm-council/self_improvement_guide.md)

## Guided Workflows

Use these documents depending on what you are trying to do:

- [demo_run_guide.md](/Users/sakethjaggaiahgari/Desktop/local-llm-council/demo_run_guide.md): step-by-step commands and UI flow for running the main demo scenarios
- [demo_runner.md](/Users/sakethjaggaiahgari/Desktop/local-llm-council/demo_runner.md): scenario-based demo validation checklist
- [demo_scorecard_template.md](/Users/sakethjaggaiahgari/Desktop/local-llm-council/demo_scorecard_template.md): notes template for scoring demo runs
- [self_improvement_guide.md](/Users/sakethjaggaiahgari/Desktop/local-llm-council/self_improvement_guide.md): how to use the council to review and improve this project itself over time

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

Cloud keys can also be entered directly in the UI. Those keys are stored only in the browser `localStorage`, sent per request as headers, and are not written to server-side run state.

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
- `GET /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/export?format=md|json|zip`
- `DELETE /runs/{run_id}`
- `POST /runs/{run_id}/feedback`
- `GET /metrics/runs`
- `GET /metrics/summary`

## Run Persistence And Export

Persisted runs can be:

- listed with `GET /runs`
- inspected in full with `GET /runs/{run_id}`
- replayed in the web UI
- exported from `GET /runs/{run_id}/export?format=md|json|zip`
- annotated with per-action feedback via `POST /runs/{run_id}/feedback`

Server-side export formats:

- `md` for a human-readable report
- `json` for redacted structured run data plus metrics
- `zip` bundling `report.md`, `run.json`, and `metrics.json`

Exports are redacted through the same config-redaction path used for persisted run state.

## Token Budgets

The web UI exposes three token budget profiles:

- `Economy` for lower-latency local runs
- `Balanced` as the default profile
- `Performance` for longer per-phase outputs

These profiles are not cosmetic. They change the actual `max_tokens` used for Phase 1, Phase 2, Phase 3, and follow-up chat.

## Eval Harness

A separate local eval harness lives under [tests/eval/README.md](/Users/sakethjaggaiahgari/Desktop/local-llm-council/tests/eval/README.md).

It is intentionally not part of the default pytest suite because it requires Ollama plus the pinned local model used in the golden topics file.

## File Inputs

The council accepts uploaded attachments through the web UI.

Supported prompt-folded files:

- Markdown
- JSON
- Text
- PDF
- Common code/config files like `py`, `js`, `ts`, `html`, `css`, `yaml`, `yml`

Supported image flow:

- Images are only useful when at least one selected seat is using a known image-capable model
- The preflight check warns if images are attached but the roster has no image-capable seat

## Testing

Run the main test suite with:

```bash
./venv/bin/pytest tests/ -q
```

Or run a smaller targeted unit subset with:

```bash
python -m unittest tests.test_main tests.test_orchestrator tests.test_input_and_router
```

The eval harness runs separately and should not be imported into the normal pytest path.

## Security Notes

This project is intended for local or otherwise trusted environments.

If you expose it publicly:

- disable the Python execution tool with `COUNCIL_ENABLE_PYTHON_TOOL=false`
- do not rely on local host execution as a sandbox boundary
- treat uploaded files and prompted code execution as sensitive attack surfaces
- understand that browser-stored cloud keys are only appropriate for trusted local use

## Shutdown Behavior

The server now handles `SIGTERM` as a best-effort graceful shutdown:

- active SSE streams receive a `shutdown` event
- the app allows a short drain window for in-flight streams
- mid-inference interruption is still best-effort because model backends may hold their own connection open

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
