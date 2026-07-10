# Demo Run Guide

Use this guide to run the LLM Council demo step by step on your machine.

## Goal

This guide helps you:

1. start the backend cleanly
2. confirm Ollama is ready
3. open the UI
4. run the main demo scenarios
5. save the outputs for later review

## 1. Clean Start

From your terminal:

```bash
cd ~/local-llm-council
source venv/bin/activate
```

If port `8765` might still be occupied, check it:

```bash
lsof -i :8765
```

If you see a PID, stop it:

```bash
kill PID_HERE
```

If needed:

```bash
kill -9 PID_HERE
```

Check Ollama is alive:

```bash
curl http://127.0.0.1:11434/api/tags
```

You should see JSON with models.

## 2. Start the App

```bash
uvicorn llm_council.main:app --host 127.0.0.1 --port 8765
```

Leave that terminal open.

Open the browser at:

```text
http://127.0.0.1:8765
```

## 3. Confirm You Are Ready

Before running any demo:

- make sure the page loads
- check the preflight box
- confirm it does not show missing models
- do not enable extra toggles unless the scenario says to

The installed text-demo models should be:

- `qwen2.5:7b`
- `gemma2:9b`
- `llama3.1:8b`

## 4. Demo Run 1: Fast Triage

In the UI:

- choose preset: `Fast Triage`
- attach file: `src/llm_council/resources/demo_samples/architecture_brief.md`
- leave `Dynamic Swarm` off
- leave `Deep Debate` off
- click `Run council`

What to look for:

- run starts cleanly
- no missing-model warning
- output stays inside the cards
- chairman verdict appears
- action items are concrete

After the run:

```bash
curl http://127.0.0.1:8765/runs
```

## 5. Demo Run 2: Code Review

In the UI:

- choose preset: `Code Review`
- attach:
  - `src/llm_council/resources/demo_samples/code_review_request.md`
  - `src/llm_council/resources/demo_samples/demo_metrics.json`
- keep `Deep Debate` on if preset enables it
- click `Run council`

What to look for:

- Phase 2 runs
- findings are specific
- chairman summarizes agreement or disagreement
- formatting is clean

After the run:

```bash
curl http://127.0.0.1:8765/metrics/summary
curl http://127.0.0.1:8765/runs
```

## 6. Demo Run 3: Product Review

In the UI:

- choose preset: `Product Review`
- attach: `src/llm_council/resources/demo_samples/product_demo_notes.md`
- click `Run council`

What to look for:

- output is readable
- no raw hashes or overflowing text
- verdict is concise and useful

## 7. Demo Run 4: Dynamic Swarm Fallback

In the UI:

- start from any stable preset, preferably `Fast Triage`
- enable `Dynamic Swarm`
- run the council

What to look for:

- if routing fails or picks unavailable models, the app warns clearly
- it falls back to the stable roster
- the run still completes

This is a reliability demo, not a quality demo.

## 8. Optional Image Demo

Only do this if you install an image-capable model later, such as:

- `gemma3:4b`
- `qwen2.5vl:7b`

Then:

- use `Product Review`
- attach `src/llm_council/resources/demo_samples/product_demo_notes.md`
- also attach an image or screenshot
- confirm preflight shows an image-capable seat

Right now the installed set is text-first, so skip this unless you add a vision model.

## 9. Inspect and Save Outputs

List all runs:

```bash
curl http://127.0.0.1:8765/runs
```

Inspect one run fully:

```bash
curl http://127.0.0.1:8765/runs/RUN_ID
```

Export that run as markdown:

```bash
curl "http://127.0.0.1:8765/runs/RUN_ID/export?format=md" -o demo_run.md
```

Export as JSON:

```bash
curl "http://127.0.0.1:8765/runs/RUN_ID/export?format=json" -o demo_run.json
```

Create a folder for saved runs:

```bash
mkdir -p demo_history
```

Store them with dates:

```bash
curl "http://127.0.0.1:8765/runs/RUN_ID/export?format=json" -o demo_history/$(date +%F)_fast_triage.json
curl "http://127.0.0.1:8765/runs/RUN_ID/export?format=md" -o demo_history/$(date +%F)_fast_triage.md
```

## 10. What To Record For Each Run

For each demo run, note:

- preset used
- files attached
- whether preflight was green
- whether output stayed inside the cards
- whether raw markdown or hashes appeared
- whether the verdict felt useful
- total run time
- run ID

You can write this in `demo_scorecard_template.md`.

## 11. If Something Goes Wrong

If the app does not start:

- check port `8765`
- check traceback in terminal

If the UI loads but runs fail:

- check preflight
- confirm Ollama is running
- confirm models exist with:

```bash
curl http://127.0.0.1:11434/api/tags
```

If formatting looks broken:

- hard refresh browser
- rerun the scenario
- export the run and inspect the raw output

If the app is stuck:

- stop the backend with `Ctrl+C`
- restart `uvicorn`

## 12. Clean Stop When Done

In the app terminal:

- press `Ctrl+C`

If you need to force stop later:

```bash
lsof -i :8765
kill PID_HERE
```

## 13. Recommended Exact Order

Use this order:

1. Start backend
2. Run `Fast Triage`
3. Run `Code Review`
4. Run `Product Review`
5. Run `Dynamic Swarm Fallback`
6. Export the best run
7. Save metrics summary

Commands after the batch:

```bash
curl http://127.0.0.1:8765/metrics/summary -o demo_history/$(date +%F)_metrics_summary.json
curl http://127.0.0.1:8765/runs -o demo_history/$(date +%F)_runs.json
```

## 14. Minimal Cheat Sheet

Start:

```bash
cd ~/local-llm-council
source venv/bin/activate
uvicorn llm_council.main:app --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

Run presets:

- `Fast Triage` + `src/llm_council/resources/demo_samples/architecture_brief.md`
- `Code Review` + `src/llm_council/resources/demo_samples/code_review_request.md` + `src/llm_council/resources/demo_samples/demo_metrics.json`
- `Product Review` + `src/llm_council/resources/demo_samples/product_demo_notes.md`

Save runs:

```bash
curl http://127.0.0.1:8765/runs
curl "http://127.0.0.1:8765/runs/RUN_ID/export?format=json" -o demo_history/run.json
```
