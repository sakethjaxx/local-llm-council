# Troubleshooting

## "Ollama is not reachable at http://localhost:11434"

Ollama is not installed or not running.

- Install: https://ollama.com/download
- Start: `ollama serve` (or launch the desktop app)
- Running elsewhere? Set `OLLAMA_BASE_URL=http://host:11434` in `.env`

## "Missing local models. Install them with: ollama pull ..."

The error message lists the exact pull commands. Run them, or set `COUNCIL_BOOTSTRAP_LOCAL_MODELS=true` in `.env` to auto-pull on demand.

## UI loads but a run fails immediately

Check the red banner message — it states the cause. Then verify:

```bash
curl http://localhost:8765/ollama/status
```

`ollama_running` and `missing` tell you what to fix.

## Stream stalls or stops mid-run

- Cold model load can take 30–60s on first request; keep-alive pings keep the connection open — wait a bit.
- A 7B+ model on low RAM can swap heavily. Check the hardware suggestion: `curl http://localhost:8765/hardware/suggest` and use a smaller roster.
- Check server logs for `llm_call_attempt_failed` entries.

## CORS error in browser console

Set `COUNCIL_CORS_ORIGINS` in `.env` to include the origin you are browsing from, e.g. `COUNCIL_CORS_ORIGINS=http://localhost:3000`.

## "COUNCIL_API_KEY must be set when binding to non-localhost"

You set `COUNCIL_HOST` to something other than `127.0.0.1`. Either bind to localhost or set `COUNCIL_API_KEY` (clients then send it in the `X-API-Key` header).

## Port 8765 already in use

Set `COUNCIL_PORT=8766` (or any free port) in `.env`.

## Docker: API starts but runs fail

The API container talks to the `ollama` container via `OLLAMA_BASE_URL=http://ollama:11434` (set in docker-compose.yml). Models are pulled into the `ollama_data` volume on first run when `COUNCIL_BOOTSTRAP_LOCAL_MODELS=true` — the first run can take minutes while models download.

## Tests fail with ModuleNotFoundError

Install dev dependencies into the venv:

```bash
./venv/bin/pip install -r requirements-dev.txt   # Windows: .\venv\Scripts\pip install -r requirements-dev.txt
```
