# Demo Runner

Use this runbook before a live demo, before tagging a release, or before pushing major changes.

## Goal

Validate that the current build is stable across the curated demo paths:

- `Fast Triage`
- `Code Review`
- `Image Review`
- `Dynamic Swarm` fallback
- mixed file ingestion

Run every scenario at least 3 times if you want meaningful consistency data.

## Environment Setup

```bash
source venv/bin/activate
uvicorn llm_council.main:app --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

## Before Each Run

1. Select the preset you want to evaluate.
2. Confirm the preflight box is green.
3. Use only the listed files for the scenario.
4. Record timings and notes in `demo_scorecard_template.md`.

## Scenario 1: Fast Triage

Preset:

- `Fast Triage`

Files:

- `architecture_brief.md`

Goal:

- validate the fastest stable council path

Check:

- launch succeeds with no missing-model errors
- chairman verdict appears quickly
- final action items are concrete

Target:

- verdict in under `20s`

## Scenario 2: Code Review

Preset:

- `Code Review`

Files:

- `code_review_request.md`
- `demo_metrics.json`

Goal:

- validate deep debate and code-oriented analysis

Check:

- phase 2 cross-review runs
- findings are specific and actionable
- chairman synthesis reflects real agreement or disagreement

Target:

- verdict in under `45s`

## Scenario 3: Image Review

Preset:

- `Image Review`

Files:

- `product_demo_notes.md`
- one screenshot or product image

Goal:

- validate image-aware review

Check:

- preflight shows an image-capable seat
- output references visual issues, not only text context
- run completes without format errors

Target:

- verdict in under `30s`

## Scenario 4: Dynamic Swarm Fallback

Preset:

- any stable preset

Toggle:

- enable `Dynamic Swarm`

Goal:

- validate safe degradation

Check:

- if swarm fails or chooses missing models, the UI warns clearly
- the council falls back to the stable roster
- the run still completes

Target:

- fallback success rate `100%`

## Scenario 5: Mixed Attachments

Preset:

- `Fast Triage`

Files:

- one markdown file
- one JSON file
- one PDF
- one image

Goal:

- validate multi-file ingestion and attachment robustness

Check:

- no crash during upload
- text-like files are folded into prompt context
- image handling is warned or supported correctly based on the roster

Target:

- completion rate `100%`

## Metrics Collection

After each scenario, inspect:

```bash
curl http://127.0.0.1:8765/metrics/runs
curl http://127.0.0.1:8765/metrics/summary
```

Track:

- `duration_ms`
- `llm_calls`
- `successful_calls`
- `failed_calls`
- `by_model`
- token usage when present

## Evaluation Criteria

Score each run from `1-5` on:

- launch reliability
- time to first useful output
- time to final verdict
- fallback behavior
- output quality
- UI clarity
- model/preset fit

## Demo Readiness Threshold

Treat the build as demo-healthy if:

- all 5 scenarios pass
- no core preset run fails
- preflight catches setup problems before launch
- fallback behavior works predictably
- average quality score is `>= 4/5`
- timings stay within your target range
