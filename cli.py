import sys
import subprocess
import asyncio
import json
from orchestrator import CouncilOrchestrator
from blast_radius import calculate_blast_radius
from hardware_detect import get_hardware_suggestion
from logging_utils import get_logger


logger = get_logger(__name__)

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

if __name__ == "__main__":
    asyncio.run(main())
