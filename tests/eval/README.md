# Eval Harness

Requires Ollama running with model from `golden_topics.json` `model_pin`.

Run all topics:

```bash
python tests/eval/run_eval.py
```

Run one topic:

```bash
python tests/eval/run_eval.py --topic code_review
```

Results appended to `eval_results.jsonl` in project root.

NOT part of default pytest suite. Run manually before shipping prompt changes.

Smart Phase skip rate warning: if >40% of runs skip Phase 2, the 0.88 threshold
may be too aggressive — users are losing cross-critique without knowing.
