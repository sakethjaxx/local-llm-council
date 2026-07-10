# Reality Report — Live Validation vs. Code Assumptions

Date: 2026-07-06. Machine: Windows 11, CPU-only Ollama 0.31.1.
Roster under test: `llama3.2` (3B) / `gemma2:2b` / `qwen2.5:3b`, chairman `qwen2.5:3b` —
three genuinely distinct small models, economy token budget.

Two validation paths:
1. **Direct orchestrator runs** (`tests/eval/live_validation.py`) — three scenarios:
   expected-agree, contested, ambiguous. Results in `dev/live_validation_results.json`.
2. **Full HTTP/SSE run** through `POST /council/stream` on the refactored frontend
   event contract.

## What held up

| Code assumption | Live result |
|---|---|
| Members end Phase 1 with a parseable `STANCE:` line | **9/9 native emission (100%)** across all three scenarios, plus 3/3 on the HTTP run. The zero-temp fallback classifier never had to fire. Target was ≥95%. |
| Gate decides on stances, not vocabulary | Correct on every run: splits detected and debated; unanimity path proven by unit tests (no live scenario produced unanimity — see below). |
| Rebuttal fires only on split | True on all runs. |
| Chairman emits valid `ChairmanDecision` JSON | `parse_tier: "json"` on all runs (qwen2.5:3b chairman). |
| Grounding rule followed | Ratios 0.75–1.0 live; enforcement (strip at <0.5) never needed on live runs, proven by unit tests. |
| Confidence signal computes end-to-end | 77–84 on the live scenarios, honest explanations attached. |

## What reality corrected

1. **Model tag mismatch blocked every HTTP run** (found by the SSE e2e, invisible to
   direct-orchestrator tests): `ollama pull llama3.2` installs `llama3.2:latest`, and
   `ensure_models_for_config` compared raw strings, reporting the model missing.
   Fixed with `:latest` normalization in `ollama_manager.py` + `tests/test_ollama_manager.py`.

2. **Yielded events were mutated after emission**: the rebuttal round updated
   `gate_info["stances"]`/`["stance_sources"]` in place — the same dicts already yielded
   in `smart_phase_decision`. SSE consumers were safe (serialized immediately) but direct
   consumers (eval harness) saw history rewritten (`native` sources became `rebuttal`).
   Fixed: events yield copies.

3. **Windows console encoding**: `→` in eval output crashed under cp1252. ASCII now.

## What to know (not bugs — behavior)

- **Personas dominate small models.** The "expected agree" scenario (an obviously good
  backup proposal) still split, because the Risk Assessor persona ("lean toward blocking")
  reliably produces HOLD. Unanimity on a 3-persona adversarial roster is rare by design;
  the gate's skip path mostly pays off on homogeneous-persona rosters.
- **Rebuttals never converged live.** 2–3B models defend their stances. The round still
  earns its cost: updated stances + concessions flow into the chairman brief. See ROADMAP.
- **Latency on CPU-only Windows: 20–27 min per deep-debate run** with these small models
  and economy budget. Live demos on CPU should use fast mode or expect this.
- **Confidence 77–84 on unresolved splits** reads high at a glance; diversity/grounding/
  parse components are genuinely strong in those runs and the explanation line carries
  the caveat. Weight tuning tracked in ROADMAP.

## Verified end-to-end event order (HTTP)

Confirmed on a completed live run through `POST /council/stream`:

`run_started → model_status → phase_start(1) → member_thinking/token/done ×3 →
smart_phase_decision (split, 3/3 native stances) → phase_start(2) → reviews ×3 →
rebuttal_start → rebuttals ×3 → rebuttal_result (converged: false) → phase_start(3) →
chairman stream → chairman_grounding (ratio 1.0) → chairman_verdict (parse_tier
fenced_json, 3 consensus + 2 disputes, 0 removed) → council_confidence (83:
diversity 1.0 / agreement 0.45 / grounding 1.0 / parse 0.95) → done`

Note the chairman emitted `fenced_json` on this run (markdown-fenced JSON) — the
tiered parser handled it and the confidence component reflected the small penalty.

## Still unverified

- Behavior of the 7B–14B default rosters (Tier 2/3) — this machine validated the small
  tier only. STANCE emission should only improve with model size; re-run
  `tests/eval/live_validation.py` after pulling a bigger roster to confirm.
- `/ollama/bootstrap` pull-from-UI flow was exercised at the API level, not through a
  cold-start browser session.
