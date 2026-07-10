# Roadmap

What is deliberately not in this release, and why.

## Deferred

### Full package migration
The repo still uses root-level imports. A `src/llm_council/` package layout is
deferred until after the orchestration extraction stabilizes, so the first
testability pass can avoid a large import-only migration.

### Schema ownership cleanup
`run_store.py` remains the runtime schema owner for now. The SQL files under
`migrations/` are human-readable mirrors until a later migration-loader pass
promotes them to the executable source of truth.

### Offline frontend assets
The UI still loads Google Fonts, `marked`, `DOMPurify`, and `vis-network` from
CDNs. Vendoring those assets is a separate local-first hardening task so this
milestone can stay focused on orchestration testability.

### Specificity-score feedback loop
`_specificity_score` (how concrete the chairman's action items are) is computed,
persisted, and visible via `/metrics/quality` — but nothing *acts* on it yet.
A real loop (e.g. re-prompting the chairman when specificity is low, or weighting
skill extraction by it) needs design: naive re-prompts add latency for marginal
gain on small local models. The run-feedback → skill-confidence loop shipped
instead because it demonstrably changes future runs and is testable.

### Confidence weight tuning
`council_confidence` weights (diversity .30 / agreement .30 / grounding .25 /
parse .15) are reasoned defaults validated against three live scenarios, not
fitted to outcome data. Live runs showed unresolved splits still scoring 77–84
when diversity/grounding/parse are perfect — the explanation line carries the
caveat, but the weights deserve revisiting once enough rated runs accumulate
in `runs.council_confidence` + `run_feedback`.

### Rebuttal convergence on small models
In live validation, no rebuttal round converged — 2–3B models defend their
stance essentially always. The bounded single round stays (cheap, occasionally
concedes, feeds the chairman updated stances), but prompting small models to
genuinely update on critique is an open quality problem. Do not add more rounds;
improve the rebuttal prompt or gate convergence on model size instead.

### Multi-user deployment (scope B)
Per `SCOPE.md`: auth, tenancy, and scaling stay out. `COUNCIL_API_KEY` + CORS
remain the documented ceiling for advanced deployments.

## Candidate next steps (unordered)

- Persist per-seat stance history and show drift across runs on the metrics view.
- A "council disagreed with you" surface: when a user thumbs-down a verdict the
  council was highly confident in, flag the run for review.
- Vision-capable seat preset once a small local vision model is reliable enough.
