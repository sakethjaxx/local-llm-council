import sys
import subprocess
import asyncio
import json
from orchestrator import CouncilOrchestrator
from blast_radius import calculate_blast_radius
from hardware_detect import get_hardware_suggestion
from logging_utils import get_logger


logger = get_logger(__name__)


def _preflight_check() -> None:
    from ollama_manager import is_ollama_available, get_missing_models, pull_model, auto_pull_enabled
    from hardware_detect import get_hardware_suggestion

    print("\n── LLM Council Preflight ──────────────────")

    if not is_ollama_available():
        print("✗ Ollama not found.")
        print("  Install: https://ollama.ai  then re-run 'local-llm-council start'")
        sys.exit(1)
    print("✓ Ollama found")

    hw = get_hardware_suggestion()
    print(f"✓ Hardware: {hw['ram_gb']}GB RAM → {hw['tier_name']}")

    missing = get_missing_models(hw["config"])
    if not missing:
        print("✓ All required models present")
    else:
        print(f"\n  Missing models ({len(missing)}):")
        for m in missing:
            print(f"    • {m}")

        if auto_pull_enabled():
            answer = "y"
        else:
            try:
                answer = input(f"\n  Pull {len(missing)} model(s) now? [Y/n] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"

        if answer in ("", "y", "yes"):
            for model in missing:
                print(f"  Pulling {model}...")
                result = pull_model(model)
                if result["success"]:
                    print(f"  ✓ {model} ready")
                else:
                    print(f"  ✗ Failed: {result['stderr'][:200]}")
                    print(f"    Run manually: ollama pull {model}")
        else:
            print("\n  ⚠ Skipping pull. Council may fail if models are missing.")

    print("───────────────────────────────────────────\n")


async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "check_diff":
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
            "security": hardware_config["security"],
            "chairman": hardware_config["chairman"],
        }
        
        orchestrator = CouncilOrchestrator()
        chairman_output = ""
        
        async for event in orchestrator.run(full_topic, None, None, config, deep_debate=False):
            if event["type"] == "member_done" and event["member"] == "chairman":
                chairman_output = event["full_text"]
            elif event["type"] == "token":
                sys.stdout.write(event["text"])
                sys.stdout.flush()
            elif event["type"] == "phase_start":
                logger.info("phase_started", extra={"label": event["label"]})
                
        logger.info("chairman_verdict_parse_started")
        try:
            data = json.loads(chairman_output)
            score = data.get("risk_score", 0)
            verdict = data.get("verdict", "").upper()
            
            if verdict == "REJECT" or score >= 8:
                logger.error("commit_blocked", extra={"risk_score": score, "action_items": data.get("action_items", [])})
                sys.exit(1)
            else:
                logger.info("commit_approved", extra={"risk_score": score})
                sys.exit(0)
        except Exception:
            logger.warning("chairman_json_parse_failed_allowing_commit", exc_info=True)
            sys.exit(0)
            
    elif len(sys.argv) > 1 and sys.argv[1] == "start":
        import uvicorn
        import os
        _preflight_check()
        host = os.getenv("COUNCIL_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = int(os.getenv("COUNCIL_PORT", "8765"))
        logger.info(f"starting_llm_council_server on {host}:{port}")
        uvicorn.run("main:app", host=host, port=port, reload=False)
        
    else:
        print("Usage: local-llm-council [start | check_diff]")
        print("  start      - Launch the Local LLM Council web interface")
        print("  check_diff - Run as a git pre-commit hook")
        sys.exit(1)

def run_cli():
    asyncio.run(main())


if __name__ == "__main__":
    run_cli()
