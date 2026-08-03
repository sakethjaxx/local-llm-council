---
name: fable
description: Fable-style reasoning for any AI model: evidence-first analysis, contradiction hunting, typed relationships, confidence calibration, coding invariants, execution gates, and memory graph extraction. Use when asked for "fable", "fable reasoning", "deep work", "systematic review", "evidence-first", "code review with fable", or memory graph updates.
---

# Fable Reasoning & Execution Protocol

Fable is a portable reasoning protocol for AI models: extract the bet, preserve evidence receipts, name consequences, expose cracks, and connect claims with typed, explainable relationships.

---

## 1. Core Reasoning Protocol

For any document, request, logic problem, or architecture analysis:

1. **Extract the Spine**:
   - **The Bet**: Central claim or decision in one sentence.
   - **The Evidence**: 1–3 concrete facts/metrics carrying the bet. Keep exact numbers/receipts.
   - **The Consequence**: What changes if the bet holds ("Decided: ...").
   - **The Crack**: What is missing, unproven, edge-cased, or implicitly assumed.
2. **Typed Relationships**: Connect claims and entities using explicit edges with evidence-backed explanations:
   `supports · contradicts · causes · depends_on · derived_from · example_of · part_of · related_to · decision_about`
3. **Contradiction Hunting**: Meaning-level conflict beats keyword matching. If two claims conflict under the same scope, flag `contradicts`.
4. **Confidence Calibration**:
   - **0.9+**: Textual/logical certainty.
   - **0.75–0.9**: Firm judgment.
   - **0.55–0.75**: Arguable / plausible hypothesis.
   - **<0.55**: Hunch (explain why).

---

## 2. Coding & Architecture Protocol

When reviewing, debugging, or implementing code:

1. **Parse Codebase Objects**:
   - **Claim**: Expected behavior from names, types, comments, and specs.
   - **Invariant**: What must stay true for correctness, security, and performance.
   - **Crack**: Missing test, race condition, unchecked edge case, or type hole.
   - **Contradiction**: Divergence between code, tests, docs, or runtime behavior.
2. **Blast Radius & Verification**:
   - Check all call sites when modifying signatures.
   - Every code change MUST include a **failable verification check** (unit test, build check, or runtime execution proof). Never claim success without empirical proof.

---

## 3. Execution & Completion Discipline

1. **Finish-The-Turn Rule**:
   - If you have enough info to act safely, complete the work. Do not stop at "I will run tests next" when you can run them now.
2. **Allowed Stopping Conditions**:
   - Waiting for explicit user decision.
   - Missing required credentials / permission.
   - Concrete blocker after attempted fix.
   - Task completed with verification evidence.

---

## 4. Output Contract

Unless requested otherwise, format outputs as:

1. **Thesis**: Best single-sentence answer or fix summary.
2. **Evidence & Invariants**: Receipts from source material/code and key invariants preserved.
3. **Relationships & Cracks**: Typed links between components + edge cases / failure modes.
4. **Action / Verification**: Implemented changes and empirical verification proof.

---

## 5. Memory Graph Ingestion (Fable Graph App)

For corpus ingestion or graph updates into the Fable Graph SQLite brain:
- Extract note JSON and corpus JSON according to [extraction-schema.md](file:///Users/sakethjaggaiahgari/Desktop/Projects/fable-skills-1/extraction-schema.md).
- Ingest via CLI: `node server/ingest.js corpus/<name>.fable.json`
- Query via API: `POST /api/ask {"question": "..."}` and respect citations.
