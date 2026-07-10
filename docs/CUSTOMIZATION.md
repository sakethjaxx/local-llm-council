# Customization

## Custom personas

A council config is a JSON object mapping seat ids to seat configs. Pass it as the `council_config` form field on `/council/stream`, or add it to `src/llm_council/resources/presets.json`:

```json
{
  "architect": {
    "label": "Lead Architect",
    "model": "ollama/qwen2.5:7b",
    "color": "#4D6BFE",
    "icon": "A",
    "persona": "You are the Lead Architect. Focus on maintainability and simplification."
  },
  "chairman": {
    "label": "Chairman",
    "model": "ollama/qwen2.5:7b",
    "persona": "You synthesize the council's analyses into a final verdict."
  }
}
```

Rules: every seat needs `model` and `persona`; the `chairman` seat is required; persona text is injected into the phase prompts verbatim — write it as a role instruction.

## Adding a model or provider

Models route through LiteLLM, so any LiteLLM-supported model id works (`ollama/mistral`, `gpt-4o-mini`, `claude-fable-5`, ...). To make the app aware of a model's capabilities (context window, vision, response_format, strengths), add an entry to `MODELS` in `src/llm_council/provider_caps.py`. Unknown models fall back to conservative defaults.

Cloud keys are supplied per-request via headers (see [API.md](API.md)) or `.env`.

## Tweaking phase prompts

Prompts live in `src/llm_council/resources/agent_prompts/phase_prompts/`:

- `phase1_analyze.txt` — independent analysis (receives `{persona}`)
- `phase2_review.txt` — peer critique (receives `{persona}`)
- `phase3_chairman.txt` — chairman synthesis (expects the JSON schema in `ChairmanDecision`)

Edit and restart. Keep `{persona}` placeholders, and keep phase 3 demanding JSON with `verdict`, `risk_score`, `action_items`, `consensus`, `disputes` — the parser has fallbacks, but valid JSON gives the best UI rendering.

## Token budgets

Profiles are defined in `src/llm_council/budget_profiles.py` and selected per-run with the `token_budget_profile` form field. Add a profile there to change per-phase output limits.

## Smart phase threshold

Phase 2 is skipped when all Phase 1 analyses agree (pairwise cosine similarity above threshold). Tune with `COUNCIL_SMART_PHASE_THRESHOLD` (default `0.88`) in `.env`.
