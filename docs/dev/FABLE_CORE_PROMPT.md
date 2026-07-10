# LLM Council — Core Intelligence Audit & Improvement Prompt (for Fable)

**Status:** Ready for Fable agent execution
**Scope:** Analyze the *core functioning* of the council — its actual deliberation quality — then find gaps, improve ease of use, and make it a genuinely better council.
**Companion doc:** `FABLE_PROMPT.md` covers setup/deploy/packaging gaps. **This prompt does NOT repeat that.** This one is about whether the council actually *thinks well* and how to make it think better.

---

## Mission

The council runs a 3-phase pipeline: independent analysis → peer cross-review → chairman synthesis. It *works*. The question this prompt answers is different and harder:

> **Does the council actually produce better answers than a single model would — and if not, why, and how do we fix that?**

Deliver two things:
1. A **CORE AUDIT REPORT** — honest analysis of how well the deliberation logic works, with evidence from the code.
2. **Concrete improvements** to the core (deliberation quality) and to ease of use — implemented, tested, simplest-solution-first.

**Guiding principle:** A council of clones that agree is worthless. Value comes from *diverse* reasoning, *real* disagreement surfacing, and *grounded* synthesis. Optimize for that, not for more phases or more features.

---

## PHASE 0: Understand the Core Before Touching It (audit first, no coding)

Read these and answer the questions honestly. Do **not** assume — cite `file:line`.

### 1. `orchestrator.py` — the pipeline
- Trace one full run: `run()` → `_member_analyze` (Phase 1) → `smart_phase.should_skip` → `_member_review` (Phase 2) → `_chairman_decide` (Phase 3).
- Q: Is Phase 2 a *real* debate or a single one-shot critique with no rebuttal/convergence? (Look: each member reviews peers *once*, results go straight to chairman. There is no second round, no voting, no updating of positions.)
- Q: Do members ever *see* each other's rebuttals and revise? Or is every position frozen after Phase 1?
- Q: `deep_debate=False` path (line ~681) hard-skips Phase 2 entirely and writes `"SKIPPED - Fast Code Review mode"`. When is fast mode the default? Does the user know they're getting a non-deliberating council?

### 2. `smart_phase.py` — the consensus gate (HIGH-VALUE TARGET)
This is the brain of "should we debate." It is likely broken in two ways:

- **Bug lead — disagreement detection is self-triggering.** `_has_explicit_disagreement()` (line 26) counts keyword markers across all analyses; `>= 3` forces Phase 2. But the Phase 1 prompt template (`agent_prompts/phase_prompts/phase1_analyze.txt`) *always* instructs members to output a `RISKS` section. So the marker `"risk"` is present in essentially every analysis, and `"but"` is near-universal English. **Verify:** does disagreement fire on virtually every run regardless of actual agreement? If so, the "smart" skip almost never happens and the gate is decorative.
- **Conceptual gap — cosine similarity ≠ agreement.** `should_skip()` embeds analyses with MiniLM and averages pairwise cosine similarity (line 31-57). But sentence-embedding similarity measures *topical/textual* likeness, not *conclusion* agreement. Two analyses "Ship it, low risk" and "Do not ship, high risk" are textually similar (same topic, same vocabulary) yet opposite in verdict. **Q: Is the council using a text-similarity proxy for semantic agreement?** That's a fundamental soundness problem.
- Q: `SKIP_THRESHOLD = 0.88` — is this ever tuned or validated against real runs? Any data?

### 3. Phase prompts (`agent_prompts/phase_prompts/*.txt`) — the actual reasoning instructions
- `phase1_analyze.txt`: every member gets the *same* rigid STRENGTHS/RISKS/RECOMMENDATIONS scaffold. Q: Does this flatten persona differences? A "security auditor" and a "product manager" produce structurally identical output. Where does genuine perspective diversity come from?
- Q: Is there any topic-type adaptation? A code-review topic and a strategy topic get the identical template.
- `phase3_chairman.txt`: chairman is told to synthesize but has **no grounding requirement** — it can assert "CONSENSUS POINTS" that no member actually made. Q: Is there any check that claimed consensus/disputes trace back to real member statements?

### 4. `router_agent.py` — roster diversity
- `generate_swarm()` forces every generated persona to `model = base_model` (line 80). `_apply_capability_routing` can reassign by strength, but on a typical local setup only **one** Ollama model is installed.
- Q: **Council-of-clones problem.** If all 3 seats run the same base model with only persona-prompt differences, their errors are *correlated* — they share the same blind spots, training biases, and failure modes. A council of one model wearing three hats. Does the code do anything to enforce or even measure diversity? Does the UI warn the user "all seats are the same model → limited value"?

### 5. `_specificity_score` / quality metrics (`orchestrator.py` line 154)
- This is the only automated quality signal. Q: Does *anything* consume it to improve future runs, or is it write-only telemetry? Is there a feedback loop at all?

### Produce the CORE AUDIT REPORT:
```
CORE FINDING: [name]
EVIDENCE: [file:line + what the code actually does]
IMPACT ON ANSWER QUALITY: [why this makes the council worse / no better than 1 model]
SEVERITY: [SOUNDNESS / QUALITY / POLISH]
FIX DIRECTION: [simplest change that materially improves deliberation]
```
Rank by IMPACT ON ANSWER QUALITY, not by effort.

---

## PHASE 1: Core Improvements (deliberation quality — do these first)

Only implement what the audit *confirms*. Simplest robust fix each time. Candidate directions (validate before building):

### A. Fix the consensus gate (likely CRITICAL — soundness)
The gate decides whether the council debates. If it's self-triggering or measuring the wrong thing, everything downstream is noise.
- Replace the keyword-count + text-cosine heuristic with an **agreement signal that reflects conclusions**, not vocabulary. Simplest robust option: a tiny structured "position extraction" — have each Phase 1 member emit a one-line `STANCE:` (e.g. verdict + confidence) alongside prose, then compare *stances*, not full-text embeddings.
- If keeping embeddings, at minimum stop letting the mandatory `RISKS` heading auto-fire disagreement — strip the scaffold headings before marker scan, or drop the keyword heuristic entirely in favor of stance comparison.
- Whatever you choose: make the skip decision **explainable** ("skipped debate because all 3 stances = SHIP, avg confidence 0.8"). Surface it in the SSE stream + UI.

### B. Make Phase 2 an actual debate (QUALITY)
Right now it's one-shot parallel critique with no convergence. Cheapest real upgrade: a **single rebuttal round** — after critiques, let each member see the critiques *of their own analysis* and either concede or defend in 2-3 sentences. This is where councils beat single models. Keep it to ONE extra round; don't build an infinite argument loop.
- Guard it: only run the rebuttal when there's genuine disagreement (from the fixed gate in A). No disagreement → no debate → save latency.

### C. Attack the council-of-clones problem (QUALITY)
- Detect when all seats share the same base model and **tell the user** in the UI ("⚠ 3 seats, 1 model — perspectives may be correlated. Add a second model for real diversity.").
- Where multiple local models exist, *prefer* spreading seats across distinct models over reusing one. Diversity of *model* beats diversity of *persona prompt*.
- Make personas produce genuinely different *reasoning*, not the same template reworded — see D.

### D. Differentiate Phase 1 by persona/topic (QUALITY)
- Loosen the rigid STRENGTHS/RISKS/RECOMMENDATIONS scaffold so a security seat reasons about threats and a product seat reasons about users — instead of both filling identical boxes. Keep enough structure that the chairman can still parse it.
- Optional: light topic-type detection (code vs. strategy vs. research) to pick the analysis framing.

### E. Ground the chairman (SOUNDNESS)
- Require the chairman to only claim CONSENSUS/DISPUTE points that are **traceable to actual member statements**. Simplest enforcement: instruct it to quote or reference the member label for each consensus/dispute point, and lightly validate that claimed agreement isn't invented.

---

## PHASE 2: Ease-of-Use Improvements (only after core is sound)

A better-thinking council is worthless if nobody can drive it. Apply the same simplest-fix rule.

- **Make the deliberation visible.** The user should *see* disagreement surface and get resolved — that's the product. Stream: stances → who disagreed with whom → rebuttals → verdict. If the UI just shows walls of text, the council's value is invisible.
- **Explain the mode.** If `deep_debate` defaults to a Phase-2-skipping "fast" mode, the user is getting three parallel opinions with no cross-examination and may not know. Make the mode explicit and its tradeoff obvious (fast = no debate; full = real deliberation).
- **One-click "why this verdict."** Let the user expand any consensus/dispute point to the member statements behind it. Ties into E.
- **Confidence honesty.** Surface when the council is a single model in 3 hats (low independent confidence) vs. genuinely diverse (higher confidence). Don't present clone-consensus as strong consensus.

Ease-of-use scoring (simplify anything under 3/5): steps-to-use, clarity of what the council did, does the user understand the verdict's basis, first-time success.

---

## Constraints (from CLAUDE.md — do not violate)

- **Free-of-cost mandate:** every default path runs on Ollama + local libs. No cloud LLM in any required flow. Cloud stays opt-in.
- **Single embedder singleton** — import from `embeddings.py`; never load SentenceTransformer twice.
- **`redact_config()`** before any roster/config JSON serialization.
- **SQLite:** WAL mode; **no new columns without a migration path**.
- **Tests** in `tests/`, pytest, in-memory SQLite, no DB mocking. Keep the existing 30 passing; add tests for every core change (esp. the consensus gate — test that opposite stances do NOT skip debate, and identical stances DO).
- Do not modify `memory_graph.py`. Do not grow `index.html` before extracting config to `presets.json`.
- Async everywhere for LLM calls.

---

## Validation (prove the core actually improved)

Code passing is not enough — show the deliberation got *better*.

1. **Consensus-gate test:** feed 3 analyses with opposite verdicts but similar wording → gate must NOT skip debate. Feed 3 genuinely agreeing stances → gate SHOULD skip. Old code likely fails the first.
2. **Debate-adds-value check:** pick a topic where seats disagree; show the rebuttal round changed at least one position or sharpened the chairman's dispute list vs. the no-debate path.
3. **Clone warning:** run with all-same-model roster → UI/stream must warn about correlated perspectives.
4. **Grounding check:** verify chairman consensus points map to real member statements (no invented agreement).
5. **Regression:** `pytest tests/ -q` green; no free-of-cost violations; latency not blown up (one rebuttal round max).

---

## Deliverables Checklist

**Core (must):**
- [ ] CORE AUDIT REPORT with `file:line` evidence, ranked by answer-quality impact
- [ ] Consensus gate fixed to reflect conclusions, not vocabulary — with explainable output
- [ ] Single rebuttal round when (and only when) real disagreement exists
- [ ] Council-of-clones detection + user warning
- [ ] Chairman grounding (consensus/disputes traceable to members)
- [ ] Tests for each, including the opposite-stance gate test

**Ease of use (should):**
- [ ] Deliberation made visible in the stream/UI (stances → disagreement → rebuttal → verdict)
- [ ] Mode (fast vs. full debate) made explicit with its tradeoff
- [ ] "Why this verdict" drill-down to member statements

**Do NOT:**
- [ ] Add phases/features that don't improve answer quality
- [ ] Add cloud calls to any default flow
- [ ] Build an unbounded debate loop (one rebuttal round, hard cap)
- [ ] Present clone-consensus as strong consensus

---

## The One-Sentence Test

When done, this must be true:

> *A user submits a contested topic, watches three genuinely-reasoning seats disagree, sees them cross-examine and partly converge, and receives a chairman verdict whose every consensus/dispute point traces to something a member actually said — and the app never pretended three copies of one model were a diverse council.*

If any clause is false, the core isn't fixed yet.

---

**Now: audit the core honestly, prove where it fails to beat a single model, fix the deliberation logic with the simplest sound changes, then make that deliberation visible. Go.**
