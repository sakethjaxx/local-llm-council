# First Run Guide

## 1. Install Ollama

Download from https://ollama.com/download (Windows, macOS, Linux).

Verify it is running:

```bash
curl http://localhost:11434/api/tags
```

If that fails, start it with `ollama serve` (the desktop app starts it automatically).

## 2. Pull a model

```bash
ollama pull llama3.2
```

The default roster is chosen automatically based on your RAM. The server tells you exactly which models are missing (and the `ollama pull` commands to run) when you start a council run — or set `COUNCIL_BOOTSTRAP_LOCAL_MODELS=true` in `.env` to auto-pull them.

## 3. Start the council

```bash
./start.sh        # Linux/macOS
.\start.ps1       # Windows
```

The script creates a venv, installs dependencies, copies `env.example` to `.env`, checks Ollama, and starts the server.

## 4. Open the UI

Go to http://localhost:8765. Pick a preset (or keep the default roster), type a topic, and press Run. You will see each seat's analysis stream live, then cross-review, then the chairman's verdict.

## Expected startup output

```
Server starting on http://localhost:8765
INFO:     Uvicorn running on http://127.0.0.1:8765
```

## Quick health checks

```bash
curl http://localhost:8765/health          # {"status": "ok"}
curl http://localhost:8765/health/ready    # includes "ollama": true when Ollama is up
curl http://localhost:8765/ollama/status   # required/installed/missing models + hint
```

Something wrong? See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
