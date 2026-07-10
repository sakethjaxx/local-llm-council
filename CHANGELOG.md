# Changelog

All notable changes to this project will be documented here.

## Unreleased

### Deliberation trust (final pass)

- STANCE fallback: a member that omits its STANCE line gets one zero-temperature
  classification call before the gate gives up; unknown verdicts still fail safe into debate.
- Grounding enforced, not just reported: chairman consensus/dispute points that name no
  member are stripped below a 0.5 grounding ratio; the verdict card shows what was removed.
- New `chairman_verdict` SSE event carries the enforced verdict — the UI no longer parses
  raw chairman text.
- Council Confidence: one honest 0–100 signal (diversity/agreement/grounding/parse) streamed
  per run and persisted (migration 004); single-model councils are capped at 45.
- Rebuttal convergence detection (`rebuttal_result` event) feeds the agreement state.
- Feedback loop closed: run ratings adjust the confidence of skills extracted from that run,
  changing their retrieval rank (test-proven).
- Fixed: Ollama tag normalization (`llama3.2` now matches installed `llama3.2:latest`) —
  previously blocked runs with untagged roster models.
- Fixed: orchestrator no longer mutates already-yielded event dicts.
- Frontend refactored out of the 1950-line `index.html` monolith into buildless ES modules
  (`static/js/`) + extracted CSS; presets stay server-fed from `presets.json`.
- Deliberation story UI: live stance chips per seat, gate decision card, rebuttal
  convergence card, verdict with member receipts (click to jump to the source analysis),
  confidence breakdown card.
- First-run guided setup in-app: Ollama detection, one-click model pull with progress,
  actionable error cards with retry.
- Mode selector replaces the Deep Debate checkbox: "Fast — no debate" vs "Deliberate"
  stated plainly. Accessibility: aria-live regions, keyboard-operable controls,
  focus-visible styles, reduced-motion support.
- Live validation harness (`tests/eval/live_validation.py`) + upgraded eval harness
  measuring STANCE emission, gate correctness, rebuttal firing, grounding, confidence.
  Results in `REALITY_REPORT.md` (100% native STANCE emission on the small-model roster).

### Earlier unreleased work

- Hardened local-first defaults for OSS sharing.
- Added API-key dependency support, upload limits, URL-fetch controls, and safer markdown rendering.
- Added run persistence, export, replay, metrics, memory, and skill-registry improvements.
- Added packaging and contributor documentation groundwork.
