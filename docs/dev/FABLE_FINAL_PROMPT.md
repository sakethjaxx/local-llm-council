# LLM Council — Final Version Prompt (Product × LLM × UI)

**Status:** Ready for Fable execution. Third and final pass.
**Prior passes (already landed — do NOT redo):**
- `d263dc0` — production gaps: one-command setup, Ollama-down errors, Windows encoding, CI, Docker, docs.
- `d9af24d` — core deliberation: stance-based consensus gate, one bounded rebuttal round, clone warning, chairman grounding, STANCE lines, event stream (`smart_phase_decision`, `rebuttal_start`, `chairman_grounding`).

This pass makes it a **finished product**, not a working prototype. Three senior roles, one shippable result.

---

## Operating Model: Three Roles, One Owner

You are simultaneously three people. Stay in role when the work is role-specific; the Product Engineer breaks ties.

- **Senior Product Engineer (owner).** Owns scope, priority, and the end-to-end user journey. Kills features that don't earn their complexity. Every change answers: *does this make the council more useful or more trustworthy to a real user?* Ships thin vertical slices, not horizontal polish.
- **Senior LLM Engineer.** Owns deliberation quality and its measurement. Answers: *is the output actually better than one model, and can we prove it with an eval — not a vibe?* Owns prompt reliability across small local models, grounding enforcement, and the feedback loop.
- **Senior UI Engineer.** Owns the frontend as a real codebase, not a 1400-line HTML file. Owns making the deliberation *visible and legible*, accessibility, responsive layout, and the empty/error/loading states that decide whether a first-timer succeeds.

---

## PHASE 0: Pin Scope + Audit Reality (no coding)

### 0.1 Resolve the one fork that changes everything
Decide and state explicitly, in a `SCOPE.md`:

> **Is the final target (A) a local single-user tool, or (B) a self-hostable multi-user product?**

Default per the free-of-cost / local-first mandate in `CLAUDE.md`: **(A) local single-user**, with (B) as a documented "advanced deployment," not a core requirement. If you pick (A), do NOT build auth systems, multi-tenancy, or horizontal scaling — that's scope creep. If the audit reveals (B) is implied by existing code (`COUNCIL_API_KEY`, CORS, per-request cloud keys already exist), keep those as-is but don't expand them.

Every priority below is ranked assuming (A). Re-rank if you justify (B).

### 0.2 Prove the core works end-to-end (the gap I could not close)
No live LLM run has ever validated the new deliberation path. Before any new feature:

1. Ensure Ollama is available (`ollama pull llama3.2` — small, fast).
2. Run the eval harness: `tests/eval/run_eval.py`. Fix it if it's stale (it references the old 2-tuple `should_skip` and `SKIPPED` label logic — verify against current `smart_phase.py` / `orchestrator.py`).
3. Run **3 real councils**: one where seats should agree, one contested, one ambiguous. Capture: did every seat emit a parseable `STANCE:` line? Did the gate decide correctly? Did the rebuttal round fire only on the contested one? Did the chairman's consensus points actually name members?
4. **Write down the STANCE emission rate.** If small models drop the STANCE line often, the gate silently degrades to "always debate" and half of pass 2's value evaporates. This is the #1 risk to verify.

Produce a **REALITY REPORT**: what actually happens on live models vs. what the code assumes.

---

## PHASE 1: LLM Engineer — Make Quality Real and Measurable

Ranked by impact on trustworthiness.

### A. STANCE reliability (CRITICAL — depends on 0.2 findings)
If emission rate is <95% on the default local roster:
- Add a **cheap fallback stance extractor**: when a member omits `STANCE:`, run a tiny zero-temp classification prompt (same model) — "In one word, PROCEED/HOLD/MIXED?" — over their analysis. One extra short call, only on miss. Cache it into the stance info so the gate and UI both see it.
- Keep the current fail-safe (missing → debate) as the last resort if even the fallback fails.
- Do NOT weaken `extract_stance`'s "unknown token → None" safety; the synonym map + fallback is the right layering.

### B. Enforce grounding, don't just report it (SOUNDNESS)
Today `_grounding_ratio` is logged and shown but nothing acts on it.
- If grounding ratio < a threshold (start 0.5, make it explainable), **re-prompt the chairman once** with an explicit instruction to attribute every point to a member label, or strip the unattributed points from the final verdict before display. Simplest sound option: strip + note "N unattributed claims removed."
- Never present an ungrounded consensus point as consensus. That's the entire trust proposition.

### C. Close the feedback loop (QUALITY — currently dead telemetry)
`run_feedback` table, `_specificity_score`, and quality metrics are **write-only**. Nothing consumes them. Pick the simplest loop that demonstrably changes a future run:
- Minimum viable: surface aggregate quality (avg specificity, grounding, stance-agreement rate, thumbs up/down) on a **metrics view**, and use thumbs-down on a run to down-rank the skill/memory it produced (skills already have a `confidence` column — decrement it). 
- Prove it with a test: a down-rated run's extracted skill drops in retrieval rank.
- If a real loop is too much for this pass, at minimum make the metrics **visible and honest** so the user can self-correct — but say so in `ROADMAP.md`.

### D. One aggregate "Council Confidence" signal (PRODUCT × LLM)
Users don't know how much to trust a verdict. Combine what you already compute into one honest 0-100 signal:
- diversity (distinct models across seats — clones cap it low),
- stance agreement (unanimous vs. split-then-converged vs. unresolved),
- grounding ratio,
- chairman parse tier.
Surface it prominently with a one-line "why." Do not inflate: three clones agreeing must score *lower* than two diverse models converging after real debate.

**Constraints:** free-of-cost default path; no cloud in required flow; shared embedder singleton; async LLM calls; new SQLite columns need a migration in `migrations/`.

---

## PHASE 2: UI Engineer — Make the Deliberation Legible

The council's value is *visible reasoning*. Right now the frontend is a single ~1400-line `index.html` and the new events render as plain status cards. Fix the architecture *and* the experience.

### E. Frontend architecture (do this first — `CLAUDE.md` forbids growing `index.html` further)
- Extract inline config/presets to data files already hinted at (`presets.json` exists — use it; stop hardcoding).
- Split `index.html` into a small, buildless module structure (ES modules or a minimal Vite setup — keep zero-cost, no heavy framework unless justified). Separate: SSE event handling, rendering, state, styles.
- No behavior change in this step — pure refactor, guarded by the fact that the app still runs. This unblocks everything else.

### F. Deliberation as the hero, not a log (PRODUCT × UI)
The stream currently dumps text. Design the run view around the *story*:
1. **Stances first** — a compact row per seat: verdict chip (PROCEED/HOLD/MIXED) + confidence, live as Phase 1 completes.
2. **The gate decision** — visibly "they agree → skipping debate" or "they split → debating," using the `smart_phase_decision` reason already streamed.
3. **Disagreement map** — who challenged whom in cross-review; who conceded vs. defended in the rebuttal round (the `rebuttal_start` event + rebuttal text are already emitted).
4. **Verdict with receipts** — each consensus/dispute point expandable to the member statement behind it (ties to grounding). One-click "why this verdict."
5. **Council Confidence** (from D) up top with its honest breakdown.

### G. First-run and failure states (PRODUCT — decides first-time success)
- **Empty state**: fresh user, no models — an in-UI guided setup (detect Ollama via `/ollama/status`, show the exact pull command, a "pull now" button hitting `/ollama/bootstrap` with live progress), not a doc link.
- **Error states**: the helpful Ollama-down hint already exists server-side — render it as an actionable card with a retry, not a red toast that vanishes.
- **Model management**: let the user see installed models and swap a seat's model from the UI. Warn (using the existing clone detection) when all seats collapse to one model.

### H. Responsive + accessible (POLISH — but table stakes for "final")
- Works on a laptop and a phone.
- Keyboard navigable, ARIA on the live regions (SSE updates must announce), sufficient contrast (the cyberpunk theme likely fails WCAG — offer an accessible theme toggle).

---

## PHASE 3: Product Engineer — Ship Quality

### I. Honest defaults and mode clarity
- The `deep_debate` toggle controls whether *any* cross-examination happens. Make the default and its tradeoff unmistakable in the UI (fast = 3 parallel opinions, no debate; full = real deliberation). A user should never get non-deliberating output thinking they got a council.

### J. Trust & safety pass (keep, don't expand for scope A)
- Verify `redact_config()` still covers every serialization boundary touched by new events (`smart_phase_decision` carries stances — confirm no key leakage).
- Python REPL tool stays off by default; confirm the new rebuttal path can't invoke it unexpectedly.

### K. Definition of Done (all must be true)
- [ ] Live end-to-end run validated on the default local roster (REALITY REPORT attached).
- [ ] STANCE emission ≥95% (native or via fallback); gate decisions correct on the 3 scenario runs.
- [ ] Grounding enforced, not just measured — no unattributed consensus reaches the user.
- [ ] Council Confidence signal shown, honest about clones.
- [ ] Feedback loop either closed (with a test proving it) or metrics made visible + deferred explicitly in ROADMAP.
- [ ] `index.html` refactored out of monolith; `presets.json` is the source of truth for presets.
- [ ] Run view tells the deliberation story (stances → gate → debate → grounded verdict).
- [ ] First-run empty state guides model setup in-UI; errors are actionable cards.
- [ ] Responsive + keyboard-accessible + contrast-checked.
- [ ] `pytest tests/ -q --ignore=tests/eval` green (currently 95); new behavior has tests; no free-of-cost violations; migrations for any new columns.
- [ ] Docs updated (README, ARCHITECTURE, API for new events, TROUBLESHOOTING).

---

## Non-Negotiables (from `CLAUDE.md`)
- Free-of-cost default path (Ollama + local libs). Cloud opt-in only.
- Single embedder singleton (`embeddings.py`). Never load SentenceTransformer twice.
- `redact_config()` before any roster/config JSON serialization.
- SQLite WAL; no new columns without a migration.
- Tests in `tests/`, pytest, in-memory SQLite, no DB mocking.
- Do not modify `memory_graph.py`.
- Async everywhere for LLM calls.

## Anti-Scope (do NOT build)
- Auth systems / multi-tenancy / horizontal scaling (unless Phase 0 justifies scope B).
- A heavy frontend framework if a buildless module split suffices.
- An unbounded debate loop (rebuttal stays one round).
- New pipeline phases that don't measurably improve output.
- Cloud calls in any default flow.

---

## The One-Sentence Test
> A first-time user with no models installed is guided to a working council in-app, submits a contested question, watches three *diverse* seats stake out positions, sees the split trigger a debate, watches at least one seat concede, and receives a verdict with a confidence score and receipts tracing every claim to a member — on their laptop or phone, for free, with the app never once pretending clones were a council.

If any clause is false, it isn't final yet. Audit reality first, then build the simplest thing that makes each clause true.
