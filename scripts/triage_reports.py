import os
import json
import re
import requests

OUT_DIR = "docs/internal/self-review-2026-05-28"


def main():
    markdown_content = ""
    for f in sorted(os.listdir(OUT_DIR)):
        if f.endswith(".md"):
            with open(os.path.join(OUT_DIR, f), "r") as fh:
                markdown_content += f"\n\n=== {f} ===\n\n" + fh.read()

    if not markdown_content.strip():
        print("No markdown reports found!")
        return

    print(f"Loaded {len(markdown_content)} chars from reports. Triaging...")

    prompt = f"""You are a senior engineer triaging code review reports.
Extract ONLY actionable findings that name a specific file. Ignore generic advice.
Group into P0 (security/crash) and P1 (logic/architecture/dead code).

Return ONLY valid JSON, no markdown, no explanation:
{{
    "P0": [{{"title": "...", "body": "file:line — description"}}],
    "P1": [{{"title": "...", "body": "file:line — description"}}]
}}

Reports:
{markdown_content[:18000]}
"""

    try:
        resp = requests.post(
            "http://127.0.0.1:11434/api/generate",
            json={"model": "qwen2.5:7b", "prompt": prompt, "format": "json", "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        print(f"[debug] raw response length: {len(raw)}")

        # strip markdown code fences if model wrapped output
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        p0 = data.get("P0", [])
        p1 = data.get("P1", [])
        print(f"[debug] P0={len(p0)} P1={len(p1)}")

        if not p0 and not p1:
            print("[warn] LLM returned empty results — reports may be too generic or context too large.")
            print("[hint] Run with smaller report chunks or use manual triage.")
            return

        sh_path = os.path.join(OUT_DIR, "create_issues.sh")
        with open(sh_path, "w") as sh:
            sh.write("#!/bin/bash\n\n# P0 Critical Issues\n")
            for item in p0:
                title = item["title"].replace('"', '\\"')
                body = item["body"].replace('"', '\\"')
                sh.write(f'gh issue create --title "{title}" --body "{body}" --label "self-review,P0"\n')

            sh.write("\n# P1 Correctness/Architecture Issues\n")
            for item in p1:
                title = item["title"].replace('"', '\\"')
                body = item["body"].replace('"', '\\"')
                sh.write(f'gh issue create --title "{title}" --body "{body}" --label "self-review,P1"\n')

        os.chmod(sh_path, 0o755)
        print(f"Generated {sh_path}")

    except json.JSONDecodeError as e:
        print(f"[error] JSON parse failed: {e}")
        print(f"[debug] raw: {raw[:500]}")
    except Exception as e:
        print(f"[error] {e}")


if __name__ == "__main__":
    main()
