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
| `smart_phase_decision` | deep-debate only: `skip`, `reason`, `split`, `stances` (per member: `verdict`, `confidence`, `summary`), `stance_sources` (per member: `native` \| `fallback`), `score` (cosine divergence telemetry) |
| `rebuttal_start` | `label` — fires only when stances split |
| `rebuttal_result` | `converged` (bool), `stances` (post-rebuttal, source `rebuttal`) |
| `chairman_grounding` | `ratio` (0–1 or null), `removed`, `kept`, `enforced` — unattributed consensus/dispute points are stripped when ratio < 0.5 |
| `chairman_verdict` | the enforced verdict: `verdict`, `risk_score`, `action_items`, `consensus`, `disputes`, `parse_tier`, `removed_points` |
| `council_confidence` | `score` (0–100), `components` (diversity/agreement/grounding/parse, each 0–1), `agreement_state`, `clone_capped`, `explanation`, `stances`, `stance_sources` |
| `swarm_routed` | new roster (dynamic swarm only) |
| `warning` / `error` | `message` |
| `done` | run finished |

Trust semantics: render the verdict from `chairman_verdict` (grounding-enforced), not by parsing `member_done` full text. A single-model council is capped at confidence 45 (`clone_capped: true`).

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

Feedback closes a learning loop: `rating: "down"` lowers the confidence of skills
extracted from that run (−0.15, floor 0.05), dropping their retrieval rank in future
councils; `"up"` reinforces (+0.05, cap 1.0). The response includes `skills_adjusted`.

## Metrics

```bash
GET /metrics/runs?limit=20     # recent runs with latency/status
GET /metrics/summary           # aggregates
GET /metrics/quality?limit=100 # parse tier, divergence, specificity, grounding, confidence per run
```

`/metrics/quality` summary includes `avg_grounding_ratio` and `avg_council_confidence`.

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
