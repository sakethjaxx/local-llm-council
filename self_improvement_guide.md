# Self Improvement Guide

Use this guide to make the LLM Council review and improve itself in a structured way.

## Goal

This document explains:

1. how to make the council review this project itself
2. what parts of the project to target
3. what prompts to use
4. how to store the results
5. how to turn the findings into real improvements

The idea is simple:

- the council does work
- the council reviews its own work and codebase
- you save the results
- you fix one issue at a time
- you rerun and compare

That is how the project improves itself over time.

## 1. What "Self Improvement" Means Here

Self improvement does not mean the system magically rewrites itself.

It means:

- the council reviews the project itself
- the council identifies weaknesses
- the council suggests fixes
- you save those findings
- you implement the best ones
- you rerun the review later to see if the same weaknesses remain

In plain terms:

- first, the system becomes aware of its own problems
- then, you use that awareness to improve the system

## 2. What The Council Should Review

The council should review the project in multiple ways, not only as code.

### A. Product Review

Ask the council to review:

- clarity of the UI
- trustworthiness of outputs
- demo readiness
- whether the app feels confusing or brittle

Target files:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/SPEC.md`
- `static/index.html`
- `demo_run_guide.md`
- `demo_runner.md`

### B. Code Review

Ask the council to review:

- correctness risks
- hidden regressions
- maintainability
- duplicated logic
- weak error handling

Target files:

- `main.py`
- `orchestrator.py`
- `provider_caps.py`
- `run_store.py`
- `skill_registry.py`
- `memory_store.py`
- `router_agent.py`
- `search_engine.py`

### C. Prompt Review

Ask the council to review:

- whether prompts are too vague
- whether roles overlap too much
- whether the chairman prompt encourages low-quality formatting
- whether debate prompts actually cause useful disagreement

Target files:

- `agent_prompts/phase_prompts/phase1_analyze.txt`
- `agent_prompts/phase_prompts/phase2_review.txt`
- `agent_prompts/phase_prompts/phase3_chairman.txt`
- `agent_prompts/01_phase1_foundation.md`
- `agent_prompts/02_phase1_5_quick_wins.md`
- `agent_prompts/03_phase2_memory.md`
- `agent_prompts/04_phase2_skill_registry.md`
- `agent_prompts/05_phase2_fingerprint.md`
- `agent_prompts/06_phase2_eval_harness.md`

### D. Run Quality Review

Ask the council to review:

- whether previous verdicts were specific enough
- whether formatting degraded
- whether the same weakness appears across many runs
- whether Phase 2 was skipped too often
- whether the system sounded confident without enough evidence

Target data:

- `GET /runs`
- `GET /runs/{run_id}`
- exported run markdown files
- exported run JSON files
- metrics summaries

### E. UI And Presentation Review

Ask the council to review:

- text overflow
- raw markdown showing up
- raw JSON showing up
- whether cards stay readable
- whether replay/export views are understandable

Target files:

- `static/index.html`
- exported run markdown
- screenshots you capture from the UI

### F. Reliability Review

Ask the council to review:

- fallback behavior
- startup failures
- shutdown handling
- port conflicts
- model availability problems

Target files:

- `main.py`
- `ollama_manager.py`
- `shutdown_state.py`
- `hardware_detect.py`
- `metrics_store.py`

## 3. What Documents And Files You Should Feed Into The Council

When doing a self-review run, attach only the files relevant to that kind of review.

Use these groups.

### Core Understanding Set

Use this when the council needs broad context:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/SPEC.md`
- `IMPROVEMENT_PLAN.md`

### Backend Logic Set

Use this for system behavior:

- `main.py`
- `orchestrator.py`
- `provider_caps.py`
- `run_store.py`
- `metrics_store.py`
- `memory_store.py`
- `skill_registry.py`

### Prompting Set

Use this for role and output quality:

- `agent_prompts/phase_prompts/phase1_analyze.txt`
- `agent_prompts/phase_prompts/phase2_review.txt`
- `agent_prompts/phase_prompts/phase3_chairman.txt`

### Frontend Set

Use this for UI output and rendering:

- `static/index.html`
- screenshots from runs
- exported markdown outputs

### Demo Behavior Set

Use this for demo readiness:

- `demo_runner.md`
- `demo_scorecard_template.md`
- `demo_run_guide.md`
- sample run exports from `demo_history/`

## 4. Prompts To Use

Do not ask vague questions like:

- "Review this project"

Instead, use targeted prompts.

### Prompt 1: Whole Project Review

```text
Review this LLM Council project itself. Find the top 5 weaknesses across architecture, reliability, output quality, UI clarity, and maintainability.

For each weakness, provide:
1. what is going wrong
2. why it is happening
3. where it lives in the project
4. the user impact
5. the first concrete fix to make
```

### Prompt 2: Product Review

```text
Review this project as a product and demo system. Identify what would confuse a new user, reduce trust, or make the demo feel fragile.

For each issue, explain:
1. the user-facing problem
2. the root cause
3. what should be improved first
```

### Prompt 3: Code Quality Review

```text
Review this codebase for correctness risks, weak abstractions, duplicated logic, and likely future regressions.

Return the 5 most important issues with:
1. file or area
2. exact risk
3. why it matters
4. fix recommendation
5. what test should be added
```

### Prompt 4: Prompt Quality Review

```text
Review these council prompt files. Identify where the personas overlap, where the prompts are too vague, and where the chairman output quality may degrade.

For each finding, explain:
1. which prompt is weak
2. why the wording causes poor output
3. how to rewrite it
```

### Prompt 5: Previous Run Review

```text
Review these past council runs. Identify repeated weaknesses in reasoning quality, formatting, confidence, and usefulness.

For each pattern, explain:
1. what repeated issue appears
2. how often it appears
3. what system change could reduce it
```

### Prompt 6: UI Review

```text
Review the frontend output quality of this project. Focus on text overflow, raw markdown visibility, raw JSON display, card readability, and clarity of chairman output.

For each issue:
1. describe the visual problem
2. identify the likely code location
3. explain the user impact
4. suggest the fix
```

## 5. How To Run A Self-Review Session

### Step 1

Start the backend:

```bash
cd /Users/sakethjaggaiahgari/Desktop/local-llm-council
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

### Step 2

Choose a review type:

- whole project review
- product review
- code review
- prompt review
- run quality review
- UI review

### Step 3

Paste the matching prompt from this document.

### Step 4

Attach only the relevant files.

Do not attach the entire repo every time.

Smaller, focused evidence gives better reviews.

### Step 5

Run the council and wait for the verdict.

### Step 6

Save the run ID and export the run.

List runs:

```bash
curl http://127.0.0.1:8765/runs
```

Inspect a run:

```bash
curl http://127.0.0.1:8765/runs/RUN_ID
```

Export markdown:

```bash
curl "http://127.0.0.1:8765/runs/RUN_ID/export?format=md" -o self_review.md
```

Export JSON:

```bash
curl "http://127.0.0.1:8765/runs/RUN_ID/export?format=json" -o self_review.json
```

## 6. How To Store Results For Future Self Review

Create a folder:

```bash
mkdir -p self_review_history
```

Save every important review run with a clear name:

```bash
curl "http://127.0.0.1:8765/runs/RUN_ID/export?format=json" -o self_review_history/$(date +%F)_project_review.json
curl "http://127.0.0.1:8765/runs/RUN_ID/export?format=md" -o self_review_history/$(date +%F)_project_review.md
curl http://127.0.0.1:8765/metrics/summary -o self_review_history/$(date +%F)_metrics_summary.json
```

Also write a short note for yourself:

```text
2026-05-23
- biggest issue found: chairman formatting inconsistency
- next action: tighten phase 3 output formatting
```

Why:

- saved runs become evidence
- later the council can review its own past reviews

## 7. How To Turn Findings Into Real Improvements

Do not try to fix everything from one run.

Use this process:

### Step 1

Pick the top 1 issue only.

### Step 2

Convert it into an action:

- fix code
- change prompt
- add a test
- improve UI formatting
- improve fallback behavior
- improve documentation

### Step 3

Implement the fix.

### Step 4

Run tests:

```bash
./venv/bin/pytest tests/ -q
```

### Step 5

Run the same self-review prompt again later.

Then compare:

- did the same problem still appear
- did it become smaller
- did a new problem appear

## 8. Implementation Actions The Council Should Recommend

When the council reviews the project, ask it to always end with concrete actions.

Good actions look like this:

- update `static/index.html` to wrap long code blocks
- tighten chairman output parsing in `orchestrator.py`
- add tests for markdown and JSON rendering regressions
- improve `phase3_chairman.txt` to reduce loose formatting
- raise visibility of fallback warnings in the UI
- add a new self-review preset
- store more structured run postmortems

Bad actions look like this:

- "make it better"
- "improve UX"
- "increase quality"

Always push the council toward specific action.

## 9. What A Good Self Improvement Cycle Looks Like

A good cycle looks like this:

1. run the council on itself
2. save the run
3. identify the top issue
4. implement one fix
5. add one test if needed
6. rerun tests
7. rerun the same self-review later
8. compare outputs

This is how the system gradually becomes better.

## 10. Recommended Weekly Routine

### Run 1

Whole project review

Use:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/SPEC.md`
- `IMPROVEMENT_PLAN.md`

### Run 2

Code review

Use:

- `main.py`
- `orchestrator.py`
- `provider_caps.py`
- `run_store.py`
- `skill_registry.py`

### Run 3

Prompt review

Use:

- `agent_prompts/phase_prompts/phase1_analyze.txt`
- `agent_prompts/phase_prompts/phase2_review.txt`
- `agent_prompts/phase_prompts/phase3_chairman.txt`

### Run 4

Past-run review

Use:

- saved files from `self_review_history/`

### Then

- export the best and most important runs
- record the top issue
- implement one fix
- run tests

## 11. Optional: Create A Dedicated Self Review Preset

Later, you can add a preset just for this workflow.

It could:

- default to `Deep Debate` on
- use a more critical topic prompt
- include an adversarial persona
- focus on architecture, quality, and failure modes

That would make self-review easier to repeat.

## 12. Minimum Version

If you want the shortest useful version of all this:

1. run the app
2. use the whole project review prompt
3. attach `README.md`, `docs/ARCHITECTURE.md`, `docs/SPEC.md`, `IMPROVEMENT_PLAN.md`
4. export the run
5. fix the top issue
6. run `./venv/bin/pytest tests/ -q`
7. repeat next week

That alone is enough to start building a self-improving review loop.
