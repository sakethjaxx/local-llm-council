"""User-acceptance suite: drives an *installed* LLM Council end to end.

Black-box: runs the `council` / `council-serve` console scripts from --bin-dir,
talks to the server over HTTP, and uses real Ollama models (nothing mocked).
The server runs from a temp directory, so package data must come from the wheel.

    python -m build && python -m venv .audit-tmp/u
    .audit-tmp/u/Scripts/pip install dist/*.whl      # bin/ on Linux/macOS
    .audit-tmp/u/Scripts/python tests/uat/run_uat.py --model ollama/llama3.2:latest

Run it with the UAT venv's Python: scripts are found next to that interpreter.

Needs a running Ollama with --model pulled. Add --slow for the CLI `ask`
journey on the default (hardware-suggested) roster, and --browser to also run
tests/uat/browser_uat.cjs (needs `npm ci` in tools/frontend + Playwright Chromium).
Exit code 1 if any scenario fails.
"""

import argparse
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
FAKE_TOPIC_SECRET = "sk-uatFAKE0123456789abcdefXYZ"
DOTENV_SECRET = "UAT_DOTENV_SECRET_42"
TOPIC = (
    "A single-user local app stores council run history. Should it use SQLite in WAL mode "
    "or one JSON file per run? Answer briefly. (Pasted by mistake: OPENAI_API_KEY="
    f"{FAKE_TOPIC_SECRET})"
)
PERSONA_SUFFIX = " Be concise: at most 5 short bullet points."

SCENARIOS: list[tuple[str, str, tuple, object, str]] = []
CTX: dict = {}


def scenario(sid: str, story: str, needs: tuple = (), tag: str = "fast"):
    def deco(fn):
        SCENARIOS.append((sid, story, needs, fn, tag))
        return fn
    return deco


def check(cond, message: str):
    if not cond:
        raise AssertionError(message)


def log(message: str):
    print(f"    {message}", flush=True)


def seat(label: str, model: str, persona: str) -> dict:
    return {"label": label, "model": model, "icon": label[0], "color": "#0071e3", "persona": persona + PERSONA_SUFFIX}


def roster(model: str, analysts: int) -> dict:
    seats = {
        "architect": seat("Architect", model, "You are a pragmatic software architect."),
        "security": seat("Security", model, "You are a security reviewer."),
    }
    config = dict(list(seats.items())[:analysts])
    config["chairman"] = seat("Chairman", model, "You are the Chairman. Synthesize the council into a verdict.")
    return config


def sse(client: httpx.Client, method: str, path: str, **kwargs) -> list[dict]:
    """Collect SSE events; print progress so a long CPU-bound run is visibly alive."""
    events = []
    started = time.monotonic()
    timeout = httpx.Timeout(30.0, read=900.0)
    with client.stream(method, path, timeout=timeout, **kwargs) as resp:
        if resp.status_code != 200:
            resp.read()
            raise AssertionError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            events.append(event)
            kind = event.get("type")
            stamp = f"[{time.monotonic() - started:6.0f}s]"
            if kind == "phase_start":
                log(f"{stamp} phase {event.get('phase')}: {event.get('label')}")
            elif kind == "member_done":
                log(f"{stamp} {event.get('member')} done ({len(event.get('full_text') or '')} chars)")
            elif kind in ("error", "warning", "done"):
                log(f"{stamp} {kind}: {event.get('message') or event.get('status')}")
    return events


def of_type(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e.get("type") == kind]


def run_cli(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [CTX["council"], *args], cwd=CTX["workdir"], env=CTX["env"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def parse_verdict(text: str) -> dict:
    from council.phase_chairman import parse_chairman_response  # same parser the CLI uses
    return parse_chairman_response(text)


# ---------------------------------------------------------------- install / CLI

@scenario("U01", "Installed `council` CLI reports its version and lists every subcommand")
def u01(c):
    out = run_cli(["--version"])
    check(out.returncode == 0 and "0.1.0" in out.stdout, f"--version: rc={out.returncode} {out.stdout!r} {out.stderr[-300:]!r}")
    helptext = run_cli(["--help"]).stdout
    for cmd in ("check_diff", "ask", "review", "history", "models"):
        check(cmd in helptext, f"--help missing {cmd}")


@scenario("U02", "`council models` shows the detected hardware and a suggested roster")
def u02(c):
    out = run_cli(["models"])
    check(out.returncode == 0, f"rc={out.returncode} {out.stderr[-300:]}")
    check("Suggested roster" in out.stdout and "ollama/" in out.stdout, out.stdout[-400:])
    log(out.stdout.strip().splitlines()[1] if out.stdout.strip() else "")


@scenario("U03", "Server started from the installed package serves the UI and all assets offline")
def u03(c):
    log(f"booted in {CTX['boot_s']:.1f}s")
    html = c.get("/")
    check(html.status_code == 200 and "LLM Council" in html.text, f"GET / -> {html.status_code}")
    check("cdn.jsdelivr" not in html.text and "unpkg.com" not in html.text, "index.html still loads a CDN script")
    for asset in ("/static/vendor/purify.min.js", "/static/vendor/marked.umd.js", "/static/vendor/vis-network.min.js",
                  "/static/js/state.js", "/static/app.js", "/static/style.css", "/static/css/responsive.css"):
        r = c.get(asset)
        check(r.status_code == 200 and len(r.content) > 100, f"{asset} -> {r.status_code}")


@scenario("U04", "Health endpoints report the server and the Ollama connection as ready")
def u04(c):
    check(c.get("/health").json() == {"status": "ok"}, "/health")
    ready = c.get("/health/ready").json()
    check(ready == {"status": "ready", "ollama": True}, f"/health/ready -> {ready}")


@scenario("U05", "Default roster, presets, demo catalog, hardware and model catalog all load")
def u05(c):
    check("chairman" in c.get("/config/default").json(), "default config has no chairman")
    presets = c.get("/presets").json()
    check(presets, "no presets")
    catalog = c.get("/demo/catalog").json()
    check(catalog, "empty demo catalog")
    check("config" in c.get("/hardware/suggest").json(), "hardware suggestion has no config")
    models = c.get("/models/catalog").json()
    installed = [m["model_id"] for m in models.get("models", []) if m.get("installed")]
    check(CTX["model"] in installed, f"{CTX['model']} not reported installed: {installed}")
    log(f"{len(installed)} installed models detected via Ollama HTTP API")


@scenario("U06", "Preflight says ready for installed models and names a missing one")
def u06(c):
    ok = c.post("/ollama/check", json={"council_config": roster(CTX["model"], 2), "attachment_names": ["notes.md"]}).json()
    check(ok.get("ready") is True, f"ready roster -> {ok}")
    bad = roster(CTX["model"], 1)
    bad["architect"]["model"] = "ollama/uat-missing-model:1b"
    miss = c.post("/ollama/check", json={"council_config": bad}).json()
    check(miss.get("ready") is False and any("uat-missing-model" in m for m in miss.get("missing", [])), f"missing -> {miss}")


@scenario("U07", "Bad input gets a clear 422 instead of starting a run")
def u07(c):
    cases = {
        "empty topic": c.post("/council/stream", data={"topic_text": "  "}),
        "roster not JSON": c.post("/council/stream", data={"topic_text": "x", "council_config": "{bad"}),
        "17 seats": c.post("/council/stream", data={"topic_text": "x", "council_config": json.dumps(
            {f"s{i}": seat("S", CTX["model"], "p") for i in range(17)})}),
        "seat without model": c.post("/ollama/check", json={"council_config": {"chairman": {"label": "C"}}}),
        "chat role spoof": c.post("/council/chat", json={"member_id": "architect", "messages": [{"role": "root", "content": "hi"}]}),
        "topic over 200k": c.post("/council/stream", data={"topic_text": "x" * 200_001}),
    }
    for name, resp in cases.items():
        check(resp.status_code == 422, f"{name}: expected 422, got {resp.status_code} {resp.text[:200]}")


@scenario("U08", "Browser and filesystem boundaries hold against a hostile page")
def u08(c):
    evil = c.post("/ingest/folder", json={"folder_path": str(CTX["project"])}, headers={"Origin": "https://evil.example"})
    check(evil.status_code == 403, f"cross-origin ingest -> {evil.status_code}")
    outside = c.post("/ingest/folder", json={"folder_path": str(CTX["workdir"])})
    check(outside.status_code == 403, f"path outside COUNCIL_PROJECT_ROOT -> {outside.status_code}")
    spoof = c.get("/health", headers={"Host": "attacker.example"})
    check(spoof.status_code == 400, f"spoofed Host -> {spoof.status_code}")
    headers = c.get("/health").headers
    check(headers.get("x-frame-options") == "DENY" and headers.get("x-content-type-options") == "nosniff", dict(headers))
    status = c.get("/status")
    check(status.status_code == 403, f"/status without COUNCIL_API_KEY -> {status.status_code}")


@scenario("U09", "Folder ingest picks up source files but never secret files")
def u09(c):
    body = c.post("/ingest/folder", json={"folder_path": str(CTX["project"]), "max_files": 20}).json()
    names = sorted(a["filename"] for a in body["attachments"])
    check("app.py" in names and "README.md" in names, f"files: {names}")
    check(".env" not in names and "prod.env" not in names, f"secret file ingested: {names}")
    check(DOTENV_SECRET not in json.dumps(body), "secret value leaked into ingest output")
    log(f"ingested {names}")


@scenario("U10", "A roster with a model that is not installed fails fast with a clear error")
def u10(c):
    bad = roster(CTX["model"], 1)
    bad["architect"]["model"] = "ollama/uat-missing-model:1b"
    events = sse(c, "POST", "/council/stream", data={"topic_text": "hello", "council_config": json.dumps(bad)})
    errors = of_type(events, "error")
    check(errors and "uat-missing-model" in errors[0]["message"], f"events: {[e.get('type') for e in events]}")
    check(not of_type(events, "phase_start"), "pipeline started despite missing model")


# ---------------------------------------------------------------- real-model journeys

@scenario("U11", "Core journey: topic + attachment -> two analysts -> chairman verdict", tag="llm")
def u11(c):
    started = time.monotonic()
    events = sse(c, "POST", "/council/stream", data={
        "topic_text": TOPIC,
        "council_config": json.dumps(roster(CTX["model"], 2)),
        "token_budget_profile": "economy",
    }, files=[("attachments", ("notes.md", b"# Notes\nRuns are written once and read for replay.\n", "text/markdown"))])
    CTX["u11_seconds"] = time.monotonic() - started
    run_started = of_type(events, "run_started")
    check(run_started, "no run_started event")
    run_id = run_started[0]["run_id"]
    check(not of_type(events, "error"), f"errors: {of_type(events, 'error')}")
    phases = {e.get("phase") for e in of_type(events, "phase_start")}
    check({1, 3} <= phases, f"phases seen: {phases}")
    done_members = {e["member"] for e in of_type(events, "member_done")}
    check({"architect", "security", "chairman"} <= done_members, f"members done: {done_members}")
    done = of_type(events, "done")
    check(done and done[-1].get("status") == "completed", f"done event: {done}")
    chairman = [e for e in of_type(events, "member_done") if e["member"] == "chairman"][-1]["full_text"]
    verdict = parse_verdict(chairman)
    check(verdict.get("_parse_tier") != "parse_failed" and verdict.get("verdict"), f"unparseable verdict: {chairman[:300]!r}")
    CTX["run_id"] = run_id
    CTX["verdict"] = verdict
    log(f"run {run_id} in {CTX['u11_seconds']:.0f}s -> verdict={verdict.get('verdict')!r} risk={verdict.get('risk_score')} "
        f"actions={len(verdict.get('action_items') or [])} parse={verdict.get('_parse_tier')}")


@scenario("U12", "The run is saved for replay, with the pasted secret redacted", needs=("run_id",), tag="llm")
def u12(c):
    listed = [r["run_id"] for r in c.get("/runs").json()["runs"]]
    check(CTX["run_id"] in listed, "run missing from /runs")
    run = c.get(f"/runs/{CTX['run_id']}").json()
    check(run.get("status") == "completed", f"status {run.get('status')}")
    dump = json.dumps(run)
    check(FAKE_TOPIC_SECRET not in dump, "pasted API key persisted in the run record")
    check("[REDACTED_SECRET]" in run.get("topic", ""), "topic was not redacted")
    by_phase = {}
    for p in run.get("phases", []):
        by_phase.setdefault(p["phase"], set()).add(p["member_id"])
    check({"architect", "security"} <= by_phase.get(1, set()) and "chairman" in by_phase.get(3, set()), f"phases {by_phase}")


@scenario("U13", "User can rate an action item, and the rating is stored", needs=("run_id",), tag="llm")
def u13(c):
    ok = c.post(f"/runs/{CTX['run_id']}/feedback", json={"action_index": 0, "rating": "thumbs_up", "note": "useful"})
    check(ok.status_code == 200 and ok.json().get("recorded"), f"feedback -> {ok.status_code} {ok.text[:200]}")
    feedback = c.get(f"/runs/{CTX['run_id']}").json().get("feedback", [])
    check(any(f["rating"] == "thumbs_up" and f["note"] == "useful" for f in feedback), f"feedback not stored: {feedback}")
    check(c.post(f"/runs/{CTX['run_id']}/feedback", json={"action_index": 0, "rating": "meh"}).status_code == 422, "bad rating accepted")
    check(c.post("/runs/no-such-run/feedback", json={"action_index": 0, "rating": "ignored"}).status_code == 404, "unknown run")


@scenario("U14", "User can export the run as Markdown, JSON and ZIP", needs=("run_id",), tag="llm")
def u14(c):
    rid = CTX["run_id"]
    md = c.get(f"/runs/{rid}/export", params={"format": "md"})
    check(md.status_code == 200 and "text/markdown" in md.headers["content-type"] and "Chairman Verdict" in md.text, md.text[:200])
    check(f'filename="{rid}.md"' in md.headers.get("content-disposition", ""), "no download filename")
    js = c.get(f"/runs/{rid}/export", params={"format": "json"}).json()
    check(js["run"]["run_id"] == rid, "json export run_id")
    archive = zipfile.ZipFile(io.BytesIO(c.get(f"/runs/{rid}/export", params={"format": "zip"}).content))
    check(set(archive.namelist()) == {"report.md", "run.json", "metrics.json"}, archive.namelist())
    check(c.get(f"/runs/{rid}/export", params={"format": "pdf"}).status_code == 400, "unsupported format accepted")
    check(c.get("/runs/no-such-run/export").status_code == 404, "unknown run export")
    check(FAKE_TOPIC_SECRET not in md.text + json.dumps(js), "secret in export")


@scenario("U15", "User can ask a follow-up question to one council member", tag="llm")
def u15(c):
    events = sse(c, "POST", "/council/chat", json={
        "member_id": "architect",
        "messages": [{"role": "user", "content": "In one sentence: what is your single biggest concern with JSON files?"}],
        "council_config": roster(CTX["model"], 1),
        "token_budget_profile": "economy",
    })
    text = "".join(e.get("chunk", "") for e in of_type(events, "chat_token"))
    check(of_type(events, "chat_done") and not of_type(events, "error"), f"events {[e.get('type') for e in events]}")
    check(len(text.strip()) > 10 and not text.lstrip().startswith("[Error"), f"reply: {text[:200]!r}")
    log(f"reply: {text.strip()[:120]!r}")


@scenario("U16", "Review Local Project reviews real source files and never sends .env contents", tag="llm")
def u16(c):
    events = sse(c, "POST", "/council/review-project", json={
        "path": str(CTX["project"]), "council_config": roster(CTX["model"], 1),
        "token_budget_profile": "economy", "max_files": 5,
    })
    info = of_type(events, "project_info")
    check(info, f"no project_info: {[e.get('type') for e in events]}")
    check(not of_type(events, "error"), f"errors: {of_type(events, 'error')}")
    check(of_type(events, "done") and of_type(events, "done")[-1].get("status") == "completed", "review did not complete")
    rid = of_type(events, "run_started")[0]["run_id"]
    CTX["review_run_id"] = rid
    check(DOTENV_SECRET not in json.dumps(events) + json.dumps(c.get(f"/runs/{rid}").json()), ".env secret reached the council")
    log(f"project_info: {json.dumps({k: v for k, v in info[0].items() if k != 'type'})[:160]}")


@scenario("U17", "`council history` shows the runs made through the web server", needs=("run_id",), tag="llm")
def u17(c):
    out = run_cli(["history", "--limit", "10"])
    check(out.returncode == 0 and CTX["run_id"][:16] in out.stdout, f"rc={out.returncode} {out.stdout[-400:]}")


@scenario("U18", "User can delete a run from history", needs=("review_run_id",), tag="llm")
def u18(c):
    rid = CTX["review_run_id"]
    check(c.delete(f"/runs/{rid}").json().get("deleted"), "delete failed")
    check(c.get(f"/runs/{rid}").status_code == 404, "deleted run still readable")
    check(rid not in [r["run_id"] for r in c.get("/runs").json()["runs"]], "deleted run still listed")
    check(c.delete("/runs/no-such-run").status_code == 404, "deleting unknown run")


@scenario("B01", "Browser journey: pick Turbo models, run the council, read the verdict, open the replay", tag="browser")
def b01(c):
    node = shutil.which("node")
    check(node, "node not found")
    env = {**os.environ, "COUNCIL_PREVIEW_URL": CTX["base_url"], "NODE_PATH": str(REPO / "tools/frontend/node_modules"),
           "COUNCIL_UI_OUTPUT": str(CTX["out"] / "screenshots")}
    proc = subprocess.run([node, str(REPO / "tests/uat/browser_uat.cjs")], env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=2400)
    for line in (proc.stdout + proc.stderr).strip().splitlines()[-12:]:
        log(line)
    check(proc.returncode == 0, "browser journey failed")


@scenario("S01", "`council ask --json --fast-mode` answers on the default hardware roster", tag="slow")
def s01(c):
    out = run_cli(["ask", "Is SQLite WAL mode safe for a single-user desktop app? Answer briefly.", "--json", "--fast-mode"],
                  timeout=3600)
    check(out.returncode == 0, f"rc={out.returncode} stderr={out.stderr[-600:]}")
    data = json.loads(out.stdout)
    check(data.get("verdict"), f"no verdict: {out.stdout[:300]}")
    log(f"verdict={data.get('verdict')!r} risk={data.get('risk_score')}")


@scenario("Z01", "Server log has no unhandled tracebacks")
def z01(c):
    text = CTX["server_log"].read_text(encoding="utf-8", errors="replace")
    check("Traceback (most recent call last)" not in text, text[text.find("Traceback"):][:1500])


# ---------------------------------------------------------------- harness

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_project(root: Path):
    root.mkdir(parents=True)
    (root / "app.py").write_text("import store\n\n\ndef main():\n    return store.save({'ok': True})\n", encoding="utf-8")
    (root / "store.py").write_text(
        "import json\nimport sqlite3\n\n\ndef save(record):\n    with sqlite3.connect('runs.db') as conn:\n"
        "        conn.execute('CREATE TABLE IF NOT EXISTS runs (body TEXT)')\n"
        "        conn.execute('INSERT INTO runs VALUES (?)', (json.dumps(record),))\n", encoding="utf-8")
    (root / "README.md").write_text("# Sample\nTiny app that saves run records.\n", encoding="utf-8")
    (root / ".env").write_text(f"DB_PASSWORD={DOTENV_SECRET}\n", encoding="utf-8")
    (root / "prod.env").write_text(f"API_TOKEN={DOTENV_SECRET}\n", encoding="utf-8")


def start_server(bin_dir: Path):
    serve = shutil.which("council-serve", path=str(bin_dir))
    check(serve, f"council-serve not found in {bin_dir}")
    CTX["server_log"] = CTX["out"] / "server.log"
    started = time.monotonic()
    proc = subprocess.Popen([serve], cwd=CTX["workdir"], env=CTX["env"], stdout=CTX["server_log"].open("w"),
                            stderr=subprocess.STDOUT)
    while time.monotonic() - started < 180:
        if proc.poll() is not None:
            raise SystemExit(f"council-serve exited with {proc.returncode}:\n{CTX['server_log'].read_text()[-2000:]}")
        try:
            if httpx.get(CTX["base_url"] + "/health", timeout=2).status_code == 200:
                CTX["boot_s"] = time.monotonic() - started
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    proc.kill()
    raise SystemExit("council-serve did not become healthy within 180s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bin-dir", default=str(Path(sys.executable).parent), help="dir with council / council-serve scripts")
    ap.add_argument("--model", default="ollama/llama3.2:latest", help="installed Ollama model used for every seat")
    ap.add_argument("--only", default="", help="comma-separated scenario ids (fast scenarios always run)")
    ap.add_argument("--no-llm", action="store_true", help="skip real-model scenarios")
    ap.add_argument("--browser", action="store_true", help="run the real-model browser journey (B01)")
    ap.add_argument("--slow", action="store_true", help="run S01 on the default roster (can take an hour on CPU)")
    ap.add_argument("--out", default=str(REPO / ".audit-tmp" / "uat"), help="report, server log and screenshots")
    args = ap.parse_args()

    bin_dir = Path(args.bin_dir).resolve()
    CTX["council"] = shutil.which("council", path=str(bin_dir))
    check(CTX["council"], f"council not found in {bin_dir}")
    CTX["model"] = args.model
    CTX["out"] = Path(args.out).resolve()
    CTX["out"].mkdir(parents=True, exist_ok=True)
    CTX["workdir"] = Path(tempfile.mkdtemp(prefix="council-uat-"))
    CTX["project"] = CTX["workdir"] / "project"
    make_project(CTX["project"])
    port = free_port()
    CTX["base_url"] = f"http://127.0.0.1:{port}"
    data = CTX["workdir"] / "data"
    data.mkdir()
    CTX["env"] = {k: v for k, v in os.environ.items() if not k.startswith("COUNCIL_")} | {
        "COUNCIL_PORT": str(port),
        "COUNCIL_DB_PATH": str(data / "council_runs.db"),
        "COUNCIL_METRICS_FILE": str(data / "metrics.jsonl"),
        "COUNCIL_PROJECT_ROOT": str(CTX["project"]),
        "COUNCIL_LOG_FORMAT": "text",
        "COUNCIL_LLM_TIMEOUT": "1200",
        "COUNCIL_MAX_PARALLEL_MEMBERS": "1",
        "COUNCIL_MEMORY_MODEL": args.model,
    }
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    enabled = {"fast"} | (set() if args.no_llm else {"llm"}) | ({"browser"} if args.browser else set()) | ({"slow"} if args.slow else set())
    print(f"UAT: model={args.model} server={CTX['base_url']} workdir={CTX['workdir']}", flush=True)

    server = start_server(bin_dir)
    results = []
    try:
        with httpx.Client(base_url=CTX["base_url"], timeout=60) as client:
            for sid, story, needs, fn, tag in SCENARIOS:
                if tag not in enabled or (only and sid not in only and tag != "fast"):
                    results.append((sid, "SKIP", story, 0.0, f"tag {tag} not enabled"))
                    continue
                missing = [n for n in needs if n not in CTX]
                if missing:
                    results.append((sid, "BLOCKED", story, 0.0, f"needs {', '.join(missing)}"))
                    print(f"[BLOCKED] {sid} {story}", flush=True)
                    continue
                print(f"[RUN] {sid} {story}", flush=True)
                started = time.monotonic()
                try:
                    fn(client)
                    results.append((sid, "PASS", story, time.monotonic() - started, ""))
                except Exception as exc:  # report and keep going: UAT wants the whole picture
                    detail = f"{type(exc).__name__}: {exc}"
                    if not isinstance(exc, AssertionError):
                        detail += "\n" + traceback.format_exc(limit=3)
                    results.append((sid, "FAIL", story, time.monotonic() - started, detail))
                print(f"  -> {results[-1][1]} ({results[-1][3]:.1f}s) {results[-1][4][:500]}", flush=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()

    print("\n" + "=" * 100)
    for sid, status, story, secs, detail in results:
        print(f"{sid:<4} {status:<8} {secs:7.1f}s  {story}")
    counts = {s: sum(1 for r in results if r[1] == s) for s in ("PASS", "FAIL", "BLOCKED", "SKIP")}
    print("=" * 100 + f"\n{counts}")
    report = CTX["out"] / "report.json"
    report.write_text(json.dumps({
        "model": args.model, "base_url": CTX["base_url"], "core_run_seconds": CTX.get("u11_seconds"),
        "verdict": {k: v for k, v in CTX.get("verdict", {}).items() if not k.startswith("_")},
        "results": [dict(zip(("id", "status", "story", "seconds", "detail"), r)) for r in results],
    }, indent=2), encoding="utf-8")
    print(f"report: {report}\nserver log: {CTX['server_log']}")
    sys.exit(1 if counts["FAIL"] or counts["BLOCKED"] else 0)


if __name__ == "__main__":
    main()
