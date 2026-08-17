#!/usr/bin/env python3
"""
Live performance and latency benchmark for LLM Council on local Ollama hardware.
Measures TTFT, phase durations, token throughput, and smart consensus gate timings.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

# Add src/council to python path
src_dir = str(Path(__file__).resolve().parent.parent.parent / "src" / "council")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from orchestrator import CouncilOrchestrator
from hardware_detect import get_hardware_suggestion


async def benchmark_run(topic_name: str, topic_text: str, attachments: list, deep_debate: bool = False):
    print(f"\n========================================================")
    print(f"🚀 BENCHMARKING: {topic_name}")
    print(f"Deep Debate: {deep_debate}")
    print(f"========================================================")

    hw = get_hardware_suggestion()
    config = hw["config"]
    print(f"Hardware Tier: {hw['tier_name']}")
    print(f"Concurrent RAM Budget: {hw['budget_gb']} GB")
    print(f"Roster Strategy: {hw['strategy']}")

    orchestrator = CouncilOrchestrator()
    
    phase_start_times = {}
    phase_durations = {}
    member_tokens = {}
    member_durations = {}
    member_ttft = {}
    first_token_seen = {}
    
    run_start = time.perf_counter()
    current_phase = None
    skipped_phase_2 = False

    async for event in orchestrator.run(
        topic_text=topic_text,
        attachments=attachments,
        custom_config=config,
        deep_debate=deep_debate,
        token_budget_profile="economy",  # Fast baseline for benchmark
    ):
        etype = event.get("type")
        now = time.perf_counter()
        
        if etype == "phase_start":
            pname = event.get("label", f"Phase {event.get('phase', '?')}")
            current_phase = pname
            phase_start_times[pname] = now
            print(f"\n⏱️  Phase Started: {pname}")
            
        elif etype == "smart_phase_evaluation":
            score = event.get("agreement_score", 0.0)
            skipped = event.get("phase_skipped", False)
            skipped_phase_2 = skipped
            print(f"   [Smart Phase Gate] Min Pairwise Agreement: {score:.3f} | Skip Phase 2: {skipped}")
            
        elif etype == "member_token":
            m = event.get("member")
            chunk = event.get("chunk", "")
            if m not in first_token_seen:
                first_token_seen[m] = now
                if current_phase in phase_start_times:
                    member_ttft[m] = now - phase_start_times[current_phase]
            member_tokens[m] = member_tokens.get(m, 0) + 1  # Approximate chunks
            
        elif etype == "member_done":
            m = event.get("member")
            full_text = event.get("full_text", "")
            words = len(full_text.split())
            approx_tokens = int(words * 1.3)
            member_tokens[m] = approx_tokens
            print(f"   ✓ {m.upper():10} finished: ~{approx_tokens} tokens ({words} words)")

    total_time = time.perf_counter() - run_start
    total_tokens = sum(member_tokens.values())
    tps = total_tokens / total_time if total_time > 0 else 0

    print(f"\n📊 --- METRICS SUMMARY ---")
    print(f"Total Wall-Clock Time : {total_time:.2f} seconds")
    print(f"Total Tokens Generated: ~{total_tokens} tokens")
    print(f"Effective Throughput  : {tps:.1f} tokens/second")
    print(f"Smart Phase 2 Skipped : {skipped_phase_2}")
    if member_ttft:
        avg_ttft = sum(member_ttft.values()) / len(member_ttft)
        print(f"Average TTFT          : {avg_ttft:.2f} seconds")

    return {
        "topic": topic_name,
        "total_time_s": round(total_time, 2),
        "total_tokens": total_tokens,
        "tokens_per_sec": round(tps, 1),
        "smart_phase_skipped": skipped_phase_2,
    }


async def main():
    samples_dir = Path(__file__).resolve().parent.parent.parent / "src" / "council" / "demo_samples"
    
    # 1. Test Architecture Brief (Fast Triage / Consensus)
    arch_file = samples_dir / "architecture_brief.md"
    arch_text = arch_file.read_text() if arch_file.exists() else "Review system architecture."
    
    # Attachments parsed representation
    attachments = [{
        "kind": "text",
        "filename": "architecture_brief.md",
        "content_type": "text/markdown",
        "text": arch_text,
    }]
    
    res1 = await benchmark_run("1. Fast Triage (Architecture Brief)", "Review this architecture brief and prioritize next steps.", attachments, deep_debate=False)

    print("\n" + "="*60)
    print("🏆 FINAL EMPIRICAL BENCHMARK SCORECARD")
    print("="*60)
    print(f"Run: {res1['topic']}")
    print(f"Duration: {res1['total_time_s']}s")
    print(f"Total Tokens: {res1['total_tokens']}")
    print(f"Throughput: {res1['tokens_per_sec']} tok/s")
    print(f"Phase 2 Consensus Bypass: {res1['smart_phase_skipped']}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
