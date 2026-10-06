import argparse
import asyncio
import json
import logging
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


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("local-llm-council")
    except Exception:
        return "dev"


def _quiet_logs() -> None:
    """Keep stdout for results: send logs to stderr, WARNING+ unless COUNCIL_LOG_LEVEL is set."""
    for stream in (sys.stdout, sys.stderr):
        # Model output can hold any Unicode; never crash on a legacy console codepage.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    root = logging.getLogger()
    if "COUNCIL_LOG_LEVEL" not in os.environ:
        root.setLevel(logging.WARNING)
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(sys.stderr)


def _status(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


async def _collect_verdict(events) -> dict:
    """Report phase/member progress on stderr and return the parsed chairman verdict.

    Members run in parallel, so their token streams are not echoed: interleaved
    they would be unreadable.
    """
    labels = {"chairman": "Chairman"}
    chairman_output = ""
    async for event in events:
        kind = event.get("type")
        member = event.get("member")
        if kind == "phase_start":
            _status(f"\n== {event.get('label', 'Phase')} ==")
        elif kind == "member_thinking":
            labels[member] = (event.get("meta") or {}).get("label") or member
        elif kind == "member_done":
            if member == "chairman":
                chairman_output = event.get("full_text", "")
            _status(f"  {labels.get(member, member)}: {'failed' if event.get('errored') else 'done'}")
        elif kind in ("warning", "error"):
            _status(f"[{kind}] {event.get('message', '')}")
    return parse_chairman_response(chairman_output)


def _print_verdict(data: dict) -> None:
    print(f"\nVerdict: {data.get('verdict')}")
    print(f"Risk score: {data.get('risk_score')}/10 | Confidence: {data.get('confidence')}/10")
    for title, key in (("Action items", "action_items"), ("Consensus", "consensus"), ("Disputes", "disputes")):
        items = data.get(key) or []
        if items:
            print(f"\n{title}:")
            for item in items:
                print(f"  - {item}")


async def _run_check_diff():
    result = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True)
    diff = result.stdout
    if not diff.strip():
        _status("council: no staged changes to review.")
        sys.exit(0)
        return

    files_result = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True)
    changed_files = [f.strip() for f in files_result.stdout.split('\n') if f.strip()]
    _status(f"council: reviewing {len(changed_files)} staged file(s)...")

    blast_radius = calculate_blast_radius(changed_files)
    full_topic = blast_radius + "\n\n--- GIT DIFF ---\n" + diff
    hardware_config = get_hardware_suggestion()["config"]
    config = {
        "security": hardware_config.get("security", {}),
        "chairman": hardware_config.get("chairman", {}),
    }

    data = await _collect_verdict(CouncilOrchestrator().run(
        topic_text=full_topic,
        attachments=None,
        custom_config=config,
        deep_debate=False,
    ))
    _print_verdict(data)
    score = data.get("risk_score", 0)
    verdict = str(data.get("verdict", "")).upper()

    if "REJECT" in verdict or "BLOCK" in verdict or (isinstance(score, (int, float)) and score >= 8):
        _status("council: commit blocked. Fix the items above, or bypass with `git commit --no-verify`.")
        sys.exit(1)
    else:
        sys.exit(0)


async def _run_ask(
    topic: str,
    deep_debate: bool = False,
    fast_mode: bool = False,
    output_json: bool = False,
    attachments: list[dict] | None = None,
):
    data = await _collect_verdict(CouncilOrchestrator().run(
        topic_text=topic,
        attachments=attachments,
        deep_debate=deep_debate,
        token_budget_profile="economy" if fast_mode else None,
    ))
    if output_json:
        print(json.dumps(data, indent=2))
    else:
        _print_verdict(data)
    sys.exit(1 if data.get("_parse_tier") == "parse_failed" else 0)


async def _run_review(path: str, deep_debate: bool = False, output_json: bool = False):
    target = Path(path).resolve()
    if not target.exists():
        print(f"Error: Path '{path}' does not exist.", file=sys.stderr)
        sys.exit(1)
        return

    attachments = None
    if target.is_file():
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Error reading file '{path}': {e}", file=sys.stderr)
            sys.exit(1)
            return
        topic = f"Review file `{target.name}`:\n\n```\n{content[:8000]}\n```"
    else:
        # Same file selection as the web UI's "Review Local Project".
        from main_routes_helper import DEFAULT_REVIEW_FILE_BUDGET, _pick_top_files, _read_files_as_attachments

        code_graph = get_project_code_graph(target)
        top_files = _pick_top_files(code_graph, DEFAULT_REVIEW_FILE_BUDGET)
        attachments = _read_files_as_attachments(str(target), top_files)
        _status(f"council: reviewing {len(attachments)} of {code_graph['stats']['files']} files in {target.name}")
        topic = code_graph.get("review_input") or f"Architectural review of project directory `{target.name}`."

    await _run_ask(topic, deep_debate=deep_debate, output_json=output_json, attachments=attachments)


def _show_history(limit: int = 10):
    store = RunStore()
    runs = store.list_runs(limit=limit)
    if not runs:
        print("No council runs found in history.")
        sys.exit(0)
        return

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
    print(f"\nDetected hardware: {hw.get('ram_gb', '?')} GB RAM (model memory budget ~{hw.get('budget_gb', '?')} GB)")
    print(f"Roster strategy: {hw.get('strategy', 'shared')}")
    if hw.get("reason"):
        print(f"  {hw['reason']}")
    print("\nSuggested roster:")
    for role, cfg in hw.get("config", {}).items():
        print(f"  - {cfg.get('label', role):<18} {cfg.get('model', 'default')}")
    pulls = hw.get("recommended_pull") or []
    if pulls:
        print("\nPull the missing models with:")
        for cmd in pulls:
            print(f"  {cmd}")
    print()
    sys.exit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="council",
        description="Local LLM Council: hardware-aware, multi-model review & decision engine"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # check_diff
    subparsers.add_parser("check_diff", help="Review staged git changes (exit 1 blocks the commit)")

    # ask
    ask_p = subparsers.add_parser("ask", help="Ask a question or request council deliberation")
    ask_p.add_argument("topic", type=str, help="Question or topic for the council")
    ask_p.add_argument("--deep-debate", action="store_true", help="Enable the Phase 2 peer cross-review")
    ask_p.add_argument("--fast-mode", action="store_true", help="Use the economy token budget for shorter, faster answers")
    ask_p.add_argument("--json", action="store_true", help="Output chairman verdict as JSON")

    # review
    rev_p = subparsers.add_parser("review", help="Review a file or project directory")
    rev_p.add_argument("path", type=str, help="Path to file or directory")
    rev_p.add_argument("--deep-debate", action="store_true", help="Enable the Phase 2 peer cross-review")
    rev_p.add_argument("--json", action="store_true", help="Output chairman verdict as JSON")

    # history
    hist_p = subparsers.add_parser("history", help="List recent council runs")
    hist_p.add_argument("--limit", type=int, default=10, help="Max runs to display")

    # models
    subparsers.add_parser("models", help="Display hardware profile and recommended model roster")

    return parser


async def main():
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if len(sys.argv) > 1 else ["--help"])

    if args.command == "check_diff":
        await _run_check_diff()
    elif args.command == "ask":
        await _run_ask(args.topic, deep_debate=args.deep_debate, fast_mode=args.fast_mode, output_json=args.json)
    elif args.command == "review":
        await _run_review(args.path, deep_debate=args.deep_debate, output_json=args.json)
    elif args.command == "history":
        _show_history(limit=args.limit)
    elif args.command == "models":
        _show_models()
    else:
        parser.print_help()
        sys.exit(0)


def entrypoint():
    """Sync wrapper for the `council` console script (entry points cannot await)."""
    _quiet_logs()
    asyncio.run(main())


if __name__ == "__main__":
    entrypoint()
