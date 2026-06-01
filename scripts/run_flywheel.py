import json
import time
import requests
import os
import sys

BASE_URL = "http://127.0.0.1:8765"
OUT_DIR = "docs/internal/self-review-2026-05-28"

def run_pass(name: str, endpoint: str, data: dict, files=None, is_json=False):
    print(f"=== Starting Pass: {name} ===")
    
    if is_json:
        resp = requests.post(f"{BASE_URL}{endpoint}", json=data, stream=True)
    else:
        req_files = []
        if files:
            for f in files:
                if os.path.exists(f):
                    req_files.append(("attachments", (os.path.basename(f), open(f, "rb"), "text/plain")))
                else:
                    print(f"  [!] Missing file: {f}")
        resp = requests.post(f"{BASE_URL}{endpoint}", data=data, files=req_files, stream=True)
    
    resp.raise_for_status()
    
    run_id = None
    for line in resp.iter_lines():
        if line:
            decoded = line.decode('utf-8')
            if decoded.startswith("data:"):
                try:
                    payload = json.loads(decoded[5:].strip())
                    if payload.get("type") == "run_started":
                        run_id = payload.get("run_id")
                        print(f"  [+] Run ID: {run_id}")
                    elif payload.get("type") == "member_thinking":
                        print(f"  [...] {payload.get('member')} thinking in phase {payload.get('phase', 1)}...")
                    elif payload.get("type") == "phase_start":
                        print(f"  [->] Phase {payload.get('phase')}: {payload.get('label')}")
                    elif payload.get("type") == "error":
                        print(f"  [X] Error: {payload.get('message')}")
                        break
                    elif payload.get("type") == "done":
                        print(f"  [✓] Run Completed.")
                        break
                except json.JSONDecodeError:
                    pass

    if files:
        for _, file_tuple in req_files:
            file_tuple[1].close()

    if run_id:
        print(f"  [+] Exporting Markdown...")
        time.sleep(2) # Give it a second to save
        export_resp = requests.get(f"{BASE_URL}/runs/{run_id}/export?format=md")
        export_resp.raise_for_status()
        
        out_path = os.path.join(OUT_DIR, f"{name}.md")
        with open(out_path, "w") as f:
            if "application/json" in export_resp.headers.get("Content-Type", ""):
                f.write(export_resp.json().get("markdown", export_resp.text))
            else:
                f.write(export_resp.text)
        print(f"  [✓] Saved to {out_path}")
    else:
        print("  [!] Failed to get run_id")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # Pass A: Architecture (Already completed)
    # run_pass(
    #     "A_Architecture",
    #     "/council/stream",
    #     {
    #         "topic_text": "Audit this codebase for dead code, redundant abstractions, and architectural drift. Focus on the orchestrator pipeline phases and data flows. Output a punch list of files to delete, functions to merge, or schemas to migrate."
    #     },
    #     files=["orchestrator.py", "main.py", "router_agent.py", "smart_phase.py", "memory_store.py", "run_store.py"]
    # )
    
    # Pass B: Security
    run_pass(
        "B_Security",
        "/council/stream",
        {
            "topic_text": "Security and OSS-shipping review. Threat model: local-first FastAPI server, cloud keys passed as headers. Check CORS, path traversal, key leaks. Output severity-ranked issues with file:line refs.",
            "deep_debate": "true"
        },
        files=["main.py", "cloud_keys.py", "io_parser.py", "provider_caps.py", "tool_repl.py", "SECURITY.md", "env.example", "Dockerfile"]
    )
    
    # Pass C: Frontend
    run_pass(
        "C_Frontend",
        "/council/stream",
        {
            "topic_text": "Frontend review of static files. Find redundant controls, accessibility gaps, responsive failures, and inline styles. Output an ordered refactor checklist."
        },
        files=["static/index.html", "static/js/app.js", "static/css/views.css"]
    )

    # Pass D: AST Auto Review
    run_pass(
        "D_AST_Auto",
        "/council/review-project",
        {
            "path": ".",
            "deep_debate": False
        },
        is_json=True
    )

if __name__ == "__main__":
    main()
