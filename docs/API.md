# HTTP API

Base URL: `http://localhost:8765`. If `COUNCIL_API_KEY` is set, send it as `X-API-Key` on every request.

## Run a council (SSE)

```bash
curl -N -X POST http://localhost:8765/council/stream \
  -F "topic_text=Should we migrate from PostgreSQL to DynamoDB?" \
  -F "deep_debate=true"
```

Multipart form fields: `topic_text`, `council_config` (JSON string), `token_budget_profile`, `dynamic_swarm`, `deep_debate`, `attachments` (files, max 10 / 20MB each).

SSE events (one JSON object per `data:` line):

| type | payload |
|---|---|
| `run_started` | `run_id` |
| `model_status` | `ollama_running`, `required`, `missing`, `ready`, `hint` |
| `phase_start` | `phase` (1–3), `label` |
| `member_thinking` | `member`, `meta` (seat config) |
| `member_token` | `member`, `chunk` (streamed text) |
| `member_done` | `member`, `full_text` |
| `swarm_routed` | new roster (dynamic swarm only) |
| `warning` / `error` | `message` |
| `done` | run finished |

Keep-alive comments (`: keep-alive`) are sent every 20s of silence.

## Chat with a member (SSE)

```bash
curl -N -X POST http://localhost:8765/council/chat \
  -H "Content-Type: application/json" \
  -d '{"member_id": "chairman", "messages": [{"role": "user", "content": "Elaborate on risk #2"}]}'
```

## Review a local project (SSE)

```bash
curl -N -X POST http://localhost:8765/council/review-project \
  -H "Content-Type: application/json" \
  -d '{"path": ".", "deep_debate": false}'
```

## Runs & feedback

```bash
GET    /runs?limit=50                 # persisted run list
GET    /runs/{run_id}                 # full run with phase outputs
GET    /runs/{run_id}/export?format=md|json|zip
DELETE /runs/{run_id}
POST   /runs/{run_id}/feedback        # {"action_index": 0, "rating": "up", "note": ""}
```

## Metrics

```bash
GET /metrics/runs?limit=20     # recent runs with latency/status
GET /metrics/summary           # aggregates
GET /metrics/quality?limit=100 # parse tier, divergence, specificity per run
```

## Config & status

```bash
GET  /health                 # liveness: {"status": "ok"}
GET  /health/ready           # readiness incl. Ollama reachability
GET  /status                 # detailed status (requires COUNCIL_API_KEY)
GET  /ollama/status          # required/installed/missing models + hint
POST /ollama/check           # preflight a specific config: {"council_config": {...}}
POST /ollama/bootstrap       # pull missing models now
GET  /config/presets         # roster presets for the UI
GET  /demo/catalog           # demo scenarios
GET  /hardware/suggest       # RAM-based default roster
GET  /council/memory         # memory graph data
GET  /skills?limit=50        # learned skills
GET  /project/code-graph     # AST dependency graph of a path
```

## Cloud provider keys (opt-in)

Send per-request headers; keys are never persisted server-side:

```
X-OpenAI-API-Key, X-Anthropic-API-Key, X-Gemini-API-Key, X-Groq-API-Key, X-OpenRouter-API-Key
```
