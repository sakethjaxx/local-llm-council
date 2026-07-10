#!/usr/bin/env python3
"""
Local eval harness — requires Ollama running with the model_pin model.
Usage: python tests/eval/run_eval.py [--topic code_review] [--all]
Not part of default pytest suite.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np

# Add src layout to path when running without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from llm_council.embeddings import get_embedder


GOLDEN_PATH = Path(__file__).parent / "golden_topics.json"
RESULTS_PATH = Path(__file__).parent.parent.parent / "eval_results.jsonl"


def cosine_sim(a, b):
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-9))


def _build_eval_config(model: str) -> dict:
    return {
        "architect": {
            "label": "Critical Analyst",
            "model": model,
            "color": "#4D6BFE",
            "icon": "A",
            "persona": "You are the Critical Analyst. Find concrete flaws, weak assumptions, and missing safeguards. Be direct and evidence-focused.",
        },
        "security": {
            "label": "Systems Architect",
            "model": model,
            "color": "#FF4444",
            "icon": "S",
            "persona": "You are the Systems Architect. Evaluate system design, scaling tradeoffs, and implementation practicality.",
        },
        "perf": {
            "label": "Risk Assessor",
            "model": model,
            "color": "#00FF00",
            "icon": "R",
            "persona": "You are the Risk Assessor. Focus on failure modes, operational risks, ethics, and downside exposure.",
        },
        "chairman": {
            "label": "Chairman",
            "model": model,
            "color": "#F5C842",
            "icon": "C",
            "persona": "You are the Chairman. Synthesize the council into a final JSON verdict with a clear recommendation.",
        },
    }


async def eval_topic(topic_entry: dict, model: str) -> dict:
    from llm_council.chairman_result import parse_chairman_response
    from llm_council.orchestrator import CouncilOrchestrator

    orch = CouncilOrchestrator()
    config = _build_eval_config(model)

    start = time.time()
    chairman_raw = ""
    smart_phase_skipped = False
    gate = None
    rebuttal_fired = False
    grounding_ratio = None
    confidence_score = None

    async for event in orch.run(
        topic_text=topic_entry["topic"],
        attachments=None,
        custom_config=config,
        deep_debate=True,
        run_id=f"eval_{topic_entry['id']}_{int(start)}",
    ):
        etype = event.get("type")
        if etype == "phase_start" and event.get("phase") == 2:
            label = event.get("label", "")
            smart_phase_skipped = "SKIPPED" in label
        elif etype == "smart_phase_decision":
            gate = {
                "skip": event.get("skip"),
                "split": event.get("split"),
                "stance_sources": event.get("stance_sources", {}),
                "stances_resolved": len(event.get("stances", {})),
            }
        elif etype == "rebuttal_start":
            rebuttal_fired = True
        elif etype == "chairman_grounding":
            grounding_ratio = event.get("ratio")
        elif etype == "council_confidence":
            confidence_score = event.get("score")
        elif etype == "member_done" and event.get("member") == "chairman":
            chairman_raw = event.get("full_text", "")

    latency = time.time() - start

    chairman_result = parse_chairman_response(chairman_raw) if chairman_raw else {}
    chairman_verdict = chairman_result.get("verdict", "") if chairman_result else ""

    embedder = get_embedder()
    ref_emb = embedder.encode(topic_entry["reference_verdict"])
    got_emb = embedder.encode(chairman_verdict) if chairman_verdict else embedder.encode("")
    score = cosine_sim(ref_emb, got_emb)

    passed = score >= topic_entry["minimum_score"]
    native_stances = sum(1 for source in (gate or {}).get("stance_sources", {}).values() if source == "native")
    entry = {
        "topic_id": topic_entry["id"],
        "score": round(score, 4),
        "minimum_score": topic_entry["minimum_score"],
        "passed": passed,
        "latency_s": round(latency, 2),
        "smart_phase_skipped": smart_phase_skipped,
        "gate": gate,
        "stance_native": native_stances,
        "stance_resolved": (gate or {}).get("stances_resolved", 0),
        "rebuttal_fired": rebuttal_fired,
        "grounding_ratio": grounding_ratio,
        "council_confidence": confidence_score,
        "verdict_length": len(chairman_verdict),
        "timestamp": time.time(),
        "model": model,
    }

    with RESULTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    status = "PASS" if passed else "FAIL"
    print(
        f"  [{status}] {topic_entry['id']}: score={score:.3f} "
        f"(min={topic_entry['minimum_score']}) latency={latency:.1f}s "
        f"phase2_skipped={smart_phase_skipped}"
    )
    return entry


async def main():
    parser = argparse.ArgumentParser(description="Run the local eval harness.")
    parser.add_argument("--topic", help="Run a single topic by id.")
    parser.add_argument("--all", action="store_true", help="Run all topics.")
    args = parser.parse_args()

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    model = golden["model_pin"]
    topics = golden["topics"]

    if args.topic:
        topics = [t for t in topics if t["id"] == args.topic]
        if not topics:
            print(f"Unknown topic id: {args.topic}")
            sys.exit(1)

    print(f"\nRunning eval harness — model: {model}")
    print(f"Topics: {[t['id'] for t in topics]}\n")

    results = []
    for topic in topics:
        print(f"→ {topic['id']}")
        result = await eval_topic(topic, model)
        results.append(result)

    scores = [result["score"] for result in results]
    mean_score = sum(scores) / len(scores)
    skip_rate = sum(1 for result in results if result["smart_phase_skipped"]) / len(results)
    passed = sum(1 for result in results if result["passed"])
    seats_total = 3 * len(results)
    native_total = sum(result.get("stance_native", 0) for result in results)
    resolved_total = sum(result.get("stance_resolved", 0) for result in results)

    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{len(results)} passed")
    print(f"Mean score: {mean_score:.3f}")
    print(f"Phase 2 skip rate: {skip_rate * 100:.0f}%")
    print(f"STANCE native emission: {native_total}/{seats_total} ({native_total / seats_total * 100:.0f}%)")
    print(f"STANCE resolved (native+fallback): {resolved_total}/{seats_total} ({resolved_total / seats_total * 100:.0f}%)")
    if resolved_total < seats_total * 0.95:
        print("\nWARNING: stance resolution below 95% — the gate degrades to always-debate.")

    if mean_score < 0.60:
        print("\nWARNING: Mean score below 0.60 — prompt or model quality degraded.")
    if skip_rate > 0.40:
        print(
            f"\nWARNING: Phase 2 skip rate {skip_rate * 100:.0f}% > 40% — "
            "smart_phase threshold may be too low."
        )

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
