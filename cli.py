import sys
import subprocess
import asyncio
import json
from orchestrator import CouncilOrchestrator
from blast_radius import calculate_blast_radius
from hardware_detect import get_hardware_suggestion

async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "check_diff":
        print("== ZeroTrust Council Git Pre-Commit Hook ==")
        result = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True)
        diff = result.stdout
        if not diff.strip():
            print("No staged changes found.")
            sys.exit(0)
            
        print("Summoning the ZeroTrust Council to review your commit...")
        
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
                print(f"\n\n--- {event['label']} ---\n")
                
        print("\n\nParsing Chairman Verdict...")
        try:
            data = json.loads(chairman_output)
            score = data.get("risk_score", 0)
            verdict = data.get("verdict", "").upper()
            
            if verdict == "REJECT" or score >= 8:
                print(f"\n[❌ COMMIT BLOCKED] Risk Score: {score}/10")
                for action in data.get("action_items", []):
                    print(f"- {action}")
                sys.exit(1)
            else:
                print(f"\n[✅ COMMIT APPROVED] Risk Score: {score}/10")
                sys.exit(0)
        except Exception as e:
            print("\n[⚠️ WARNING] Failed to parse Chairman JSON. Allowing commit by default.")
            sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
