import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from blast_radius import calculate_blast_radius
from hardware_detect import get_hardware_suggestion
from logging_utils import get_logger
from orchestrator import CouncilOrchestrator, parse_chairman_response
from project_graph import get_project_code_graph
from run_store import RunStore

logger = get_logger(__name__)


async def _run_check_diff():
    logger.info("precommit_hook_started")
    result = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True)
    diff = result.stdout
    if not diff.strip():
        logger.info("no_staged_changes")
        sys.exit(0)

    logger.info("precommit_review_started")

    # 1. Fetch changed files
    files_result = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True)
    changed_files = [f.strip() for f in files_result.stdout.split('\n') if f.strip()]

    # 2. Get Blast Radius
    blast_radius = calculate_blast_radius(changed_files)
    full_topic = blast_radius + "\n\n--- GIT DIFF ---\n" + diff
    hardware_config = get_hardware_suggestion()["config"]
    config = {
        "security": hardware_config.get("security", {}),
        "chairman": hardware_config.get("chairman", {}),
    }

    orchestrator = CouncilOrchestrator()
    chairman_output = ""

    async for event in orchestrator.run(
        topic_text=full_topic,
        attachments=None,
        custom_config=config,
        deep_debate=False
    ):
        if event.get("type") == "member_done" and event.get("member") == "chairman":
            chairman_output = event.get("full_text", "")
        elif event.get("type") == "member_token":
            sys.stdout.write(event.get("chunk", ""))
            sys.stdout.flush()
        elif event.get("type") == "token":
            sys.stdout.write(event.get("text", ""))
            sys.stdout.flush()
        elif event.get("type") == "phase_start":
            logger.info("phase_started", extra={"label": event.get("label")})

    logger.info("chairman_verdict_parse_started")
    data = parse_chairman_response(chairman_output)
    score = data.get("risk_score", 0)
    verdict = str(data.get("verdict", "")).upper()

    if "REJECT" in verdict or "BLOCK" in verdict or (isinstance(score, (int, float)) and score >= 8):
        logger.error("commit_blocked", extra={"risk_score": score, "action_items": data.get("action_items", [])})
        sys.exit(1)
    else:
        logger.info("commit_approved", extra={"risk_score": score})
        sys.exit(0)


async def _run_ask(topic: str, deep_debate: bool = False, fast_mode: bool = False, output_json: bool = False):
    logger.info("cli_ask_started", extra={"topic": topic, "deep_debate": deep_debate})
    orchestrator = CouncilOrchestrator()
    chairman_output = ""

    async for event in orchestrator.run(
        topic_text=topic,
        deep_debate=deep_debate,
        fast_mode=fast_mode,
    ):
        if event.get("type") == "member_done" and event.get("member") == "chairman":
            chairman_output = event.get("full_text", "")
        elif not output_json:
            if event.get("type") == "member_token":
                sys.stdout.write(event.get("chunk", ""))
                sys.stdout.flush()
            elif event.get("type") == "token":
                sys.stdout.write(event.get("text", ""))
                sys.stdout.flush()
            elif event.get("type") == "phase_start":
                print(f"\n--- {event.get('label', 'Phase')} ---")

    if output_json:
        data = parse_chairman_response(chairman_output)
        print(json.dumps(data, indent=2))
    else:
        print("\n")
    sys.exit(0)


async def _run_review(path: str, deep_debate: bool = False):
    target = Path(path).resolve()
    if not target.exists():
        print(f"Error: Path '{path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if target.is_file():
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Error reading file '{path}': {e}", file=sys.stderr)
            sys.exit(1)
        topic = f"Review file `{target.name}`:\n\n```\n{content[:8000]}\n```"
    else:
        code_graph = get_project_code_graph(target)
        topic = f"Architectural review of project directory `{target.name}`.\n\n{code_graph.get('summary', '')}"

    await _run_ask(topic, deep_debate=deep_debate)


def _show_history(limit: int = 10):
    store = RunStore()
    runs = store.list_runs(limit=limit)
    if not runs:
        print("No council runs found in history.")
        sys.exit(0)

    print(f"\n{'RUN ID':<18} {'STATUS':<12} {'TOPIC':<40}")
    print("-" * 72)
    for r in runs:
        run_id = str(r.get("run_id", ""))[:16]
        status = str(r.get("status", ""))
        topic = str(r.get("topic", "")).replace("\n", " ")[:38]
        print(f"{run_id:<18} {status:<12} {topic:<40}")
    print()
    sys.exit(0)


def _show_models():
    hw = get_hardware_suggestion()
    preset = hw.get("preset", "balanced")
    total_ram = hw.get("total_ram_gb", "unknown")
    vram = hw.get("vram_gb", "unknown")
    print(f"\nDetected Hardware: {total_ram} GB RAM, {vram} GB VRAM")
    print(f"Recommended Preset: {preset}")
    print("\nConfigured Roster:")
    for role, cfg in hw.get("config", {}).items():
        print(f"  - {role:<12}: {cfg.get('model', 'default')} ({cfg.get('persona', '')})")
    print()
    sys.exit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="council",
        description="🏛️ Local LLM Council: Hardware-aware, multi-agent review & decision engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # check_diff
    subparsers.add_parser("check_diff", help="Run pre-commit hook on staged git changes")

    # ask
    ask_p = subparsers.add_parser("ask", help="Ask a question or request council deliberation")
    ask_p.add_argument("topic", type=str, help="Question or topic for the council")
    ask_p.add_argument("--deep-debate", action="store_true", help="Enable multi-round debate")
    ask_p.add_argument("--fast-mode", action="store_true", help="Fast single-pass consensus")
    ask_p.add_argument("--json", action="store_true", help="Output chairman verdict as JSON")

    # review
    rev_p = subparsers.add_parser("review", help="Review a file or project directory")
    rev_p.add_argument("path", type=str, help="Path to file or directory")
    rev_p.add_argument("--deep-debate", action="store_true", help="Enable deep debate")

    # history
    hist_p = subparsers.add_parser("history", help="List recent council runs")
    hist_p.add_argument("--limit", type=int, default=10, help="Max runs to display")

    # models
    subparsers.add_parser("models", help="Display hardware profile and recommended model roster")

    return parser


async def main():
    parser = build_parser()

    # Handle backward-compatible check_diff if invoked directly without subparser parsing
    args = parser.parse_args(sys.argv[1:] if len(sys.argv) > 1 else ["--help"])

    if args.command == "check_diff":
        await _run_check_diff()
    elif args.command == "ask":
        await _run_ask(args.topic, deep_debate=args.deep_debate, fast_mode=args.fast_mode, output_json=args.json)
    elif args.command == "review":
        await _run_review(args.path, deep_debate=args.deep_debate)
    elif args.command == "history":
        _show_history(limit=args.limit)
    elif args.command == "models":
        _show_models()
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
