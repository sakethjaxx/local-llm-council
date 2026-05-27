# Agent Task: Phase 2d — Eval Harness (5 Golden Topics)

## Context

Working directory: `/Users/sakethjaggaiahgari/Desktop/local-llm-council`
Stack: FastAPI, LiteLLM, SQLite, Python 3.13 tested, 3.12+ intended
Tests: `./venv/bin/pytest tests/ -q` — must stay green (currently 30 passing)

**Prerequisites:**
- `embeddings.py` with `get_embedder()` singleton (Phase 1.5)
- Orchestrator functional end-to-end with Ollama running

Read before starting:
- `orchestrator.py` — how to call `run()` programmatically, what it returns
- `embeddings.py` — `get_embedder()` for cosine scoring
- `run_store.py` — `RunStore` interface

## Goal

Build a local eval harness that scores output quality against reference verdicts. 30 existing tests verify plumbing only. This suite detects prompt regressions and model-quality changes.

**Not part of the default pytest suite** — runs separately (requires Ollama). Must stay decoupled from `tests/` to avoid breaking CI.

## What to Build

### 1. `tests/eval/golden_topics.json`

Five fixed topics covering diverse council use cases. Each has a `topic`, `reference_verdict`, and `minimum_score` threshold.

```json
{
  "version": "1",
  "model_pin": "ollama/qwen2.5:7b",
  "topics": [
    {
      "id": "code_review",
      "topic": "Review this Python function for bugs and performance: def get_user(id): return db.query('SELECT * FROM users WHERE id=' + str(id))",
      "reference_verdict": "Critical SQL injection vulnerability. String concatenation in query. Must use parameterized queries. No input validation. No error handling.",
      "minimum_score": 0.65
    },
    {
      "id": "architecture_decision",
      "topic": "Should we use a microservices architecture or a monolith for a new 3-person startup building a SaaS product?",
      "reference_verdict": "Monolith recommended for 3-person team. Microservices add operational complexity that outweighs benefits at small scale. Start monolith, extract services when bottlenecks identified.",
      "minimum_score": 0.60
    },
    {
      "id": "ethics_tradeoff",
      "topic": "Our ML model achieves 95% accuracy overall but only 78% accuracy for minority demographic groups. Should we ship it?",
      "reference_verdict": "Do not ship without addressing disparity. 17-point accuracy gap is discriminatory. Requires rebalancing training data, fairness constraints, or separate models per group. Legal and ethical risk.",
      "minimum_score": 0.55
    },
    {
      "id": "factual_dispute",
      "topic": "Team is split: engineer A says Redis is the right cache layer, engineer B says Memcached is better. Evaluate for a session store with 10M daily active users.",
      "reference_verdict": "Redis preferred. Supports persistence, richer data structures, pub/sub, cluster mode. Memcached faster for pure string cache but lacks Redis's reliability features for session storage at scale.",
      "minimum_score": 0.60
    },
    {
      "id": "data_pipeline",
      "topic": "Design a data pipeline to ingest 500GB/day of JSON logs, run 3 transformation steps, and expose results via API. Budget is zero for managed cloud services.",
      "reference_verdict": "Use Kafka or Redpanda for ingestion. Apache Spark or DuckDB for batch transforms. Store results in PostgreSQL or ClickHouse. Serve via FastAPI. All open-source, zero managed cost.",
      "minimum_score": 0.55
    }
  ]
}
```

### 2. `tests/eval/run_eval.py`

Standalone script. Drives the orchestrator, scores results, logs to `eval_results.jsonl`.

```python
#!/usr/bin/env python3
"""
Local eval harness — requires Ollama running with the model_pin model.
Usage: python tests/eval/run_eval.py [--topic code_review] [--all]
Not part of default pytest suite.
"""
import asyncio, json, sys, time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from embeddings import get_embedder
import numpy as np

GOLDEN_PATH = Path(__file__).parent / "golden_topics.json"
RESULTS_PATH = Path(__file__).parent.parent.parent / "eval_results.jsonl"

def cosine_sim(a, b):
    a, b = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

async def eval_topic(topic_entry: dict, model: str) -> dict:
    from orchestrator import Orchestrator
    from run_store import RunStore

    run_store = RunStore()
    orch = Orchestrator(run_store=run_store)

    roster = [
        {"model": model, "persona": "Critical Analyst"},
        {"model": model, "persona": "Systems Architect"},
        {"model": model, "persona": "Risk Assessor"},
    ]

    start = time.time()
    result = await orch.run(
        topic=topic_entry["topic"],
        roster=roster,
        chairman_model=model,
        run_id=f"eval_{topic_entry['id']}_{int(start)}"
    )
    latency = time.time() - start

    chairman_verdict = result.get("verdict", "") if result else ""

    embedder = get_embedder()
    ref_emb = embedder.encode(topic_entry["reference_verdict"])
    got_emb = embedder.encode(chairman_verdict) if chairman_verdict else embedder.encode("")
    score = cosine_sim(ref_emb, got_emb)

    passed = score >= topic_entry["minimum_score"]
    smart_phase_skipped = result.get("smart_phase_skipped", False) if result else False

    entry = {
        "topic_id": topic_entry["id"],
        "score": round(score, 4),
        "minimum_score": topic_entry["minimum_score"],
        "passed": passed,
        "latency_s": round(latency, 2),
        "smart_phase_skipped": smart_phase_skipped,
        "verdict_length": len(chairman_verdict),
        "timestamp": time.time(),
        "model": model,
    }

    with open(RESULTS_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {topic_entry['id']}: score={score:.3f} (min={topic_entry['minimum_score']}) latency={latency:.1f}s phase2_skipped={smart_phase_skipped}")
    return entry

async def main():
    golden = json.loads(GOLDEN_PATH.read_text())
    model = golden["model_pin"]
    topics = golden["topics"]

    if "--topic" in sys.argv:
        idx = sys.argv.index("--topic")
        tid = sys.argv[idx + 1]
        topics = [t for t in topics if t["id"] == tid]
        if not topics:
            print(f"Unknown topic id: {tid}")
            sys.exit(1)

    print(f"\nRunning eval harness — model: {model}")
    print(f"Topics: {[t['id'] for t in topics]}\n")

    results = []
    for topic in topics:
        print(f"→ {topic['id']}")
        r = await eval_topic(topic, model)
        results.append(r)

    scores = [r["score"] for r in results]
    mean_score = sum(scores) / len(scores)
    skip_rate = sum(1 for r in results if r["smart_phase_skipped"]) / len(results)
    passed = sum(1 for r in results if r["passed"])

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{len(results)} passed")
    print(f"Mean score: {mean_score:.3f}")
    print(f"Phase 2 skip rate: {skip_rate*100:.0f}%")

    if mean_score < 0.60:
        print("\nWARNING: Mean score below 0.60 — prompt or model quality degraded.")
    if skip_rate > 0.40:
        print(f"\nWARNING: Phase 2 skip rate {skip_rate*100:.0f}% > 40% — smart_phase threshold may be too low.")

    sys.exit(0 if passed == len(results) else 1)

if __name__ == "__main__":
    asyncio.run(main())
```

### 3. `tests/eval/README.md`

Document how to run:
```
# Eval Harness

Requires Ollama running with model from golden_topics.json model_pin.

Run all topics:
  python tests/eval/run_eval.py

Run one topic:
  python tests/eval/run_eval.py --topic code_review

Results appended to eval_results.jsonl in project root.

NOT part of default pytest suite. Run manually before shipping prompt changes.

Smart Phase skip rate warning: if >40% of runs skip Phase 2, the 0.88 threshold
may be too aggressive — users are losing cross-critique without knowing.
```

## Acceptance Criteria

- `python tests/eval/run_eval.py` runs all 5 topics end-to-end without errors (requires Ollama)
- Each topic scores against its `minimum_score` threshold
- Mean score and Phase 2 skip rate printed at end
- Skip rate warning fires if >40% topics skipped Phase 2
- Results appended to `eval_results.jsonl` (not overwritten)
- `./venv/bin/pytest tests/ -q` still passes (eval is NOT imported by pytest)
- Script exits with code 0 on all pass, 1 on any fail

## Do Not

- Import eval scripts from `tests/conftest.py` or any test file
- Call cloud LLM APIs
- Block on embedding model load — `get_embedder()` is lazy and cached
- Hard-code Ollama URL — use the same URL resolution as the orchestrator
- Make golden_topics.json topics too broad (they must have a clearly correct direction)
