#!/usr/bin/env python3
"""Live end-to-end validation of the deliberation path against real Ollama models.

Runs three scenarios (expected-agree, contested, ambiguous) on a genuinely
diverse small-model roster and reports the facts the code assumes:

  - STANCE emission rate (native vs fallback vs missing) per seat
  - gate decision + reason for each scenario
  - whether the rebuttal round fired, and only on splits
  - chairman grounding ratio / enforcement
  - council confidence score

Usage: python tests/eval/live_validation.py
Not part of the default pytest suite — requires a running Ollama server.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

RESULTS_PATH = Path(__file__).parent.parent.parent / "live_validation_results.json"

ROSTER = {
    "optimist": {
        "label": "Product Advocate",
        "model": "ollama/llama3.2",
        "color": "#4D6BFE",
        "icon": "P",
        "persona": "You are the Product Advocate. Focus on user value, speed to market, and momentum. You lean toward shipping and iterating unless the downside is severe.",
    },
    "skeptic": {
        "label": "Risk Assessor",
        "model": "ollama/gemma2:2b",
        "color": "#FF4444",
        "icon": "R",
        "persona": "You are the Risk Assessor. Focus on failure modes, irreversible harm, and downside exposure. You lean toward blocking anything with unresolved serious risk.",
    },
    "pragmatist": {
        "label": "Systems Engineer",
        "model": "ollama/qwen2.5:3b",
        "color": "#00A76F",
        "icon": "S",
        "persona": "You are the Systems Engineer. Focus on implementation practicality, team capacity, and operational cost. Judge on evidence.",
    },
    "chairman": {
        "label": "Chairman",
        "model": "ollama/qwen2.5:3b",
        "color": "#F5C842",
        "icon": "C",
        "persona": "You are the Chairman. Synthesize the council into a final JSON verdict.",
    },
}

SCENARIOS = [
    {
        "id": "expected_agree",
        "expectation": "all seats PROCEED, gate skips cross-review",
        "topic": (
            "Proposal: add automated backups for our production database. We currently have none. "
            "The backup tool is free, tested, and takes one afternoon to set up. Should we do it?"
        ),
    },
    {
        "id": "contested",
        "expectation": "seats split, debate + rebuttal fire",
        "topic": (
            "Proposal: ship our ML model tomorrow to hit a contractual deadline. It reaches 95% accuracy "
            "overall but only 78% for minority demographic groups. Missing the deadline costs us the contract "
            "and possibly the company. Shipping risks discriminatory outcomes and reputational damage. Ship or hold?"
        ),
    },
    {
        "id": "ambiguous",
        "expectation": "MIXED stances plausible, debate fires",
        "topic": (
            "Proposal: our 3-person startup must choose between microservices and a monolith for a new SaaS "
            "product. Both are viable; team has experience with both. Which way should we go?"
        ),
    },
]


async def run_scenario(scenario: dict) -> dict:
    from llm_council.orchestrator import CouncilOrchestrator

    orch = CouncilOrchestrator()
    started = time.time()
    record = {
        "id": scenario["id"],
        "expectation": scenario["expectation"],
        "gate": None,
        "rebuttal_fired": False,
        "rebuttal_result": None,
        "grounding": None,
        "verdict": None,
        "confidence": None,
        "phase2_skipped": None,
        "errors": [],
    }

    async for event in orch.run(
        topic_text=scenario["topic"],
        attachments=None,
        custom_config=json.loads(json.dumps(ROSTER)),
        deep_debate=True,
        run_id=f"live_{scenario['id']}_{int(started)}",
        token_budget_profile="economy",
    ):
        etype = event.get("type")
        if etype == "smart_phase_decision":
            record["gate"] = {
                "skip": event.get("skip"),
                "reason": event.get("reason"),
                "stances": event.get("stances"),
                "stance_sources": event.get("stance_sources"),
                "split": event.get("split"),
            }
        elif etype == "phase_start" and event.get("phase") == 2:
            record["phase2_skipped"] = "SKIPPED" in (event.get("label") or "")
        elif etype == "rebuttal_start":
            record["rebuttal_fired"] = True
        elif etype == "rebuttal_result":
            record["rebuttal_result"] = {"converged": event.get("converged")}
        elif etype == "chairman_grounding":
            record["grounding"] = {k: event.get(k) for k in ("ratio", "removed", "kept", "enforced")}
        elif etype == "chairman_verdict":
            record["verdict"] = {
                "verdict": (event.get("verdict") or "")[:200],
                "parse_tier": event.get("parse_tier"),
                "consensus_points": len(event.get("consensus") or []),
                "dispute_points": len(event.get("disputes") or []),
            }
        elif etype == "council_confidence":
            record["confidence"] = {
                "score": event.get("score"),
                "agreement_state": event.get("agreement_state"),
                "explanation": event.get("explanation"),
            }
        elif etype == "error":
            record["errors"].append(event.get("message"))

    record["latency_s"] = round(time.time() - started, 1)
    return record


def stance_stats(results: list[dict]) -> dict:
    seats = 0
    counts = {"native": 0, "fallback": 0, "rebuttal": 0}
    resolved = 0
    for record in results:
        gate = record.get("gate") or {}
        sources = gate.get("stance_sources") or {}
        stances = gate.get("stances") or {}
        seats += 3  # three council seats per scenario
        resolved += len(stances)
        for source in sources.values():
            if source in counts:
                counts[source] += 1
    missing = seats - resolved
    return {
        "seats_total": seats,
        **counts,
        "missing": missing,
        "native_rate": round(counts["native"] / seats, 3) if seats else None,
        "recovered_rate": round(resolved / seats, 3) if seats else None,
    }


async def main():
    print("Live validation — roster: llama3.2 / gemma2:2b / qwen2.5:3b (chairman qwen2.5:3b)\n")
    results = []
    for scenario in SCENARIOS:
        print(f"-> {scenario['id']} ({scenario['expectation']})")
        try:
            record = await run_scenario(scenario)
        except Exception as exc:
            record = {"id": scenario["id"], "fatal": str(exc)}
        results.append(record)
        print(json.dumps(record, indent=2)[:1500])
        print()

    stats = stance_stats([r for r in results if "fatal" not in r])
    print("=" * 60)
    print("STANCE EMISSION:", json.dumps(stats))

    payload = {"timestamp": time.time(), "results": results, "stance_stats": stats}
    RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Written to {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
