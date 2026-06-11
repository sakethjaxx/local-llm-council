# Self-Improvement Trial Runs - 2026-06-09

These were local Ollama trial runs against the current `local-llm-council` workspace.

## Environment

- Models available: `qwen2.5:7b`, `gemma2:9b`, `llama3.1:8b`
- Token budget: `economy`
- Debate mode: disabled for latency
- URL fetching: disabled
- Completed persisted run: `a18dcf3a-1cf2-42f3-9451-e90f9eb9a1fc`

## Trial 1 - OSS Product Readiness

Prompt focus: can a new technical OSS user clone, run, trust, and get first-session value from LLM Council?

Attached evidence:

- `README.md`
- `pyproject.toml`
- `Dockerfile`
- `.github/workflows/test.yml`
- `static/index.html`
- `static/js/app.js`
- `static/js/state.js`
- `static/css/views.css`
- `env.example`

Run result:

- Status: `completed`
- Started: `2026-06-09 15:46:43`
- Finished: `2026-06-09 16:00:26`
- Parse tier: `json`
- Specificity score: `0.233`

Chairman verdict:

```json
{
  "verdict": "Address the identified security and documentation issues to enhance the project's stability, maintainability, and user experience.",
  "risk_score": 6,
  "action_items": [
    "Update Python version consistency",
    "Secure storage of API keys",
    "Improve documentation clarity",
    "Implement input validation for user inputs",
    "Enhance user experience by adding tooltips or inline help"
  ],
  "consensus": [
    "The codebase demonstrates strong structural organization, robust error handling, and reusable components.",
    "Security is a significant concern, particularly with the use of `localStorage` for storing API keys.",
    "Ensuring consistent Python versions across Dockerfile and dependencies will prevent runtime issues."
  ],
  "disputes": [
    "Disagreement on whether to update the Python version in the Dockerfile to match the specified dependency or keep it as is."
  ]
}
```

Member output excerpts:

```text
Technical Writer:
- Strengths: structured codebase, error handling, reusable components.
- Risks: browser localStorage key storage, Python version mismatch, unclear differentiators.
- Recommendations: clarify docs, align Python versions, explain key storage risk.

Product Engineer:
- Strengths: event handling, responsive design, clear state management.
- Risks: localStorage key storage, input validation, Python version mismatch, missing contextual help.
- Recommendations: update version consistency, improve env docs, add validation and tooltips.
```

## Aborted Trial - Reliability / Code Quality

I stopped this run before completion.

Reason: the attachment set was larger (`~70k` chars), which triggered another long summarization phase. The first trial had already shown that local self-review with broad file sets is slow enough to hurt iteration speed.

Aborted run id: `6968e4d9-7562-4f16-b923-076c2800621d`

## Findings From The Trial Process

1. Broad file-set self-review is too slow on local 7B defaults.

The first run took about 14 minutes, with several minutes spent before Phase 1 because `chunk_and_summarize()` had to summarize about `49k` chars. This is acceptable for a benchmark, but too slow for a normal self-improvement loop.

Suggested fix: add a "self-review fast path" that limits attachments to a small file group, skips summarization below a stricter cap, or uses deterministic file excerpts/diffs instead of summarizing every attached file.

2. First-run embedding initialization adds visible latency and network noise.

The run loaded `sentence-transformers/all-MiniLM-L6-v2` and made Hugging Face requests before analysis. That is expected if the model is not already cached, but it should be documented and ideally warmed up explicitly.

Suggested fix: add a startup or preflight line that says whether embedding model cache is ready.

3. LiteLLM and Pydantic warnings clutter the CLI/server output.

The run emitted repeated LiteLLM cost-calculation logs and Pydantic serializer warnings during Ollama streaming. This makes real progress signals hard to see.

Suggested fix: suppress or route third-party logs/warnings through the JSON logger at warning/error only.

4. Chairman output was valid JSON but too generic.

The run parsed cleanly, but `specificity_score=0.233`. The action items did not include file paths or exact changes, despite the prompt asking for concrete improvements.

Suggested fix: tighten the chairman prompt for self-review mode: require `file`, `line_or_section`, `change`, `why`, and `verification` fields for every action item.

5. The council flagged `localStorage` again, but this is an accepted local-first tradeoff.

The model treated browser key storage as a security blocker. For v0.1 this is acceptable if documented loudly. The action should be documentation and warnings, not a new auth/key vault system.

Suggested fix: add a README "Cloud key storage" note near Quick Start and a UI helper next to the cloud-key section.

## Recommended Next Self-Improvement Runs

Use narrow evidence sets:

1. `README.md`, `pyproject.toml`, `Dockerfile`, `.github/workflows/test.yml` for release readiness.
2. `orchestrator.py`, `summarizer.py`, `memory_store.py`, `skill_registry.py` for runtime latency and output quality.
3. `static/index.html`, `static/js/*.js`, `static/css/*.css` for UI and first-run UX.

Do not attach broad file sets unless the goal is an endurance benchmark.

## Trial 2 - Self-Review Workflow Meta-Review

Run time: 236.6s

Chairman parsed summary:

- Persisted run id: `d27c0779-720e-463d-bbae-57c826539229`
- Verdict: `Implement optimizations to reduce startup time, improve log quality, and enhance the specificity of generated content while addressing performance issues.`
- Risk score: `8`
- Parse tier: `json`
- Specificity score: `0.5`

Action items:

- Identify and optimize summarization processes to reduce startup time.
- Clean up logs to remove redundant and noisy lines.
- Develop standard prompts for improving the specificity of generated content.
- Optimize model size and complexity to minimize embedding initialization time.
- Implement log filtering or suppression for repetitive cost-calculation lines and Pydantic serializer warnings.

Raw chairman output:

```text
{
  "verdict": "Implement optimizations to reduce startup time, improve log quality, and enhance the specificity of generated content while addressing performance issues.",
  "risk_score": 8,
  "action_items": [
    "Identify and optimize summarization processes to reduce startup time",
    "Clean up logs to remove redundant and noisy lines",
    "Develop standard prompts for improving the specificity of generated content",
    "Optimize model size and complexity to minimize embedding initialization time",
    "Implement log filtering or suppression for repetitive cost-calculation lines and Pydantic serializer warnings"
  ],
  "consensus": [
    "Successful JSON parsing is a solid foundation.",
    "Recognizing localStorage key storage as an accepted tradeoff shows maturity in decision-making.",
    "The focus on security, performance, and maintainability is commendable."
  ],
  "disputes": [
    "Disagreement on the prioritization of model optimization vs. log filtering/suppression and cache mechanisms.",
    "Divergent views on whether caching sentence-transformers should be a higher priority than other optimizations."
  ]
}
```
