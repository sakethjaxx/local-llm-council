import asyncio
import base64
import copy
import io
import json
import os
import pathlib
import socket
import sys
import zipfile
from typing import List, Optional
from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import Response

from cloud_keys import extract_cloud_keys
from hardware_detect import get_default_council_config
from io_parser import format_attachments_for_prompt, ingest_folder, parse_uploaded_file
from logging_utils import get_logger
from metrics_store import metrics_store
from ollama_manager import ensure_models_for_config
from project_graph import get_project_code_graph
from provider_caps import redact_config, supports_image_input
from routes_stream import (
    handle_dynamic_swarm as _handle_dynamic_swarm,
    stream_chat_lifecycle,
    stream_council_lifecycle,
    stream_review_project_lifecycle,
)
from shutdown_state import active_stream_count

logger = get_logger(__name__)

_BLOCKED_PATH_PREFIXES = (
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/.aws"),
    os.path.expanduser("~/.gnupg"),
    os.path.expanduser("~/.kube"),
    os.path.expanduser("~/.docker"),
    "/etc",
    "/sys",
    "/proc",
    "/dev",
    "/root",
    "/var/root",
    "/private/etc",
)

DEFAULT_REVIEW_FILE_BUDGET = 25
MAX_REVIEW_FILE_BUDGET = 120
REVIEW_CHAR_BUDGET = 120_000


def _main_attr(name: str, default):
    main_mod = sys.modules.get("main")
    if main_mod is not None and hasattr(main_mod, name):
        return getattr(main_mod, name)
    return default


def _allowed_origins() -> list[str]:
    raw = os.getenv("COUNCIL_CORS_ORIGINS", "")
    if not raw.strip():
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


def _reject_if_overloaded():
    max_active = _main_attr("MAX_CONCURRENT_STREAMS", 4)
    fn_count = _main_attr("active_stream_count", active_stream_count)
    if fn_count() >= max_active:
        raise HTTPException(
            status_code=429,
            detail=f"Server is at maximum capacity ({max_active} active runs). Please wait for an existing run to finish.",
        )


def _request_cloud_keys(request: Request) -> dict:
    return extract_cloud_keys(dict(request.headers))


def _shutdown_event_payload() -> dict:
    return {"type": "shutdown", "message": "Server shutdown requested. Ending stream."}


def _feature_flags() -> dict:
    return {
        "auto_pull": os.getenv("COUNCIL_AUTO_PULL", "true").lower() == "true",
        "search": os.getenv("COUNCIL_ENABLE_SEARCH", "false").lower() == "true",
        "dynamic_swarm": os.getenv("COUNCIL_ENABLE_DYNAMIC_SWARM", "false").lower() == "true",
        "python_tool": os.getenv("COUNCIL_ENABLE_PYTHON_TOOL", "false").lower() == "true",
        "python_tool_enabled": os.getenv("COUNCIL_ENABLE_PYTHON_TOOL", "false").lower() == "true",
    }


def _confine_to_project_root(candidate: str) -> str:
    resolved = os.path.realpath(candidate)
    for blocked in _BLOCKED_PATH_PREFIXES:
        if blocked and (resolved == blocked or resolved.startswith(blocked + os.sep)):
            raise HTTPException(status_code=403, detail=f"Access to sensitive directory is forbidden: {blocked}")

    allowed_root = os.getenv("COUNCIL_PROJECT_ROOT")
    if allowed_root:
        root = os.path.realpath(allowed_root)
        if resolved != root and not resolved.startswith(root + os.sep):
            raise HTTPException(status_code=403, detail=f"Path is outside the allowed COUNCIL_PROJECT_ROOT: {root}")
    return resolved


def _metrics_run_for_export(run_id: str) -> dict:
    store = _main_attr("metrics_store", metrics_store)
    for run in store.list_runs(limit=500):
        if run.get("run_id") == run_id:
            return redact_config(run)
    return {}


def _render_run_markdown(run: dict, metrics: dict) -> str:
    lines = [
        "# Council Run Export",
        "",
        f"Run ID: {run.get('run_id', '')}",
        f"Status: {run.get('status', '')}",
        "",
        "## Topic",
        run.get("topic", ""),
        "",
    ]
    chairman_phase = next(
        (p for p in run.get("phases", []) if p.get("phase") == 3 and p.get("member_id") == "chairman"),
        None,
    )
    if chairman_phase:
        lines.extend(["## Chairman Verdict", chairman_phase.get("output", ""), ""])

    for phase in run.get("phases", []):
        seat = (run.get("roster") or {}).get(phase.get("member_id"), {})
        label = seat.get("label") or phase.get("member_id", "unknown")
        lines.extend([f"## Phase {phase.get('phase')} — {label}", "", phase.get("output", ""), ""])

    if run.get("feedback"):
        lines.append("## Feedback\n")
        for item in run["feedback"]:
            lines.append(f"- Action {item.get('action_index')}: {item.get('rating')} {item.get('note', '').strip()}".rstrip())
        lines.append("")

    if metrics:
        lines.extend(["## Metrics", "", json.dumps(metrics, indent=2), ""])
    return "\n".join(lines)


def _pick_top_files(graph_data: dict, k: int = DEFAULT_REVIEW_FILE_BUDGET) -> list[str]:
    stats = graph_data.get("stats", {})
    seen: set[str] = set()
    result: list[str] = []

    def take(path: str) -> bool:
        if not path or path in seen:
            return False
        seen.add(path)
        result.append(path)
        return len(result) >= k

    for item in stats.get("top_inbound", []) + stats.get("top_outbound", []):
        path = item[0] if isinstance(item, (list, tuple)) else item.get("id", "")
        if take(path):
            return result

    for node in graph_data.get("nodes", []):
        path = node.get("id", "") if isinstance(node, dict) else str(node)
        if take(path):
            return result

    for iso in stats.get("isolated", []):
        if take(iso):
            return result

    return result


def _read_files_as_attachments(root: str, rel_paths: list[str]) -> list[dict]:
    root_path = pathlib.Path(root).resolve()
    attachments = []
    per_file_cap = max(2_000, REVIEW_CHAR_BUDGET // max(1, len(rel_paths)))
    for rel in rel_paths:
        full = root_path / rel
        try:
            text = full.read_text(encoding="utf-8", errors="replace")[:per_file_cap]
            attachments.append({
                "kind": "text",
                "filename": rel,
                "content_type": "text/plain",
                "text": text,
                "summary": f"File: {rel}",
            })
        except Exception:
            continue
    return attachments


async def _parse_uploads(
    attachments: Optional[list[UploadFile]], max_files: int, max_upload_mb: int, max_total_bytes: int
) -> list[dict]:
    if len(attachments or []) > max_files:
        raise HTTPException(status_code=400, detail=f"Max {max_files} attachments per run")

    max_upload_bytes = max_upload_mb * 1024 * 1024
    parsed_attachments: list[dict] = []
    total_bytes = 0

    for upload in attachments or []:
        if not upload or not upload.filename:
            continue
        raw = await upload.read(max_upload_bytes + 1)
        if len(raw) > max_upload_bytes:
            raise HTTPException(status_code=400, detail=f"File {upload.filename} exceeds {max_upload_mb}MB limit")
        total_bytes += len(raw)
        if total_bytes > max_total_bytes:
            raise HTTPException(status_code=400, detail="Total attachment size exceeds 50MB limit")
        parsed = parse_uploaded_file(upload.filename, upload.content_type or "application/octet-stream", raw)
        if parsed.get("kind") == "image":
            parsed["data"] = base64.b64encode(raw).decode()
        parsed_attachments.append(parsed)
    return parsed_attachments


def _parse_config_json(council_config: Optional[str]) -> tuple[Optional[dict], Optional[str]]:
    if not council_config:
        return None, None
    try:
        return json.loads(council_config), None
    except (json.JSONDecodeError, ValueError) as exc:
        err = str(exc)
        logger.warning("council_config_parse_failed", extra={"error": err})
        return None, err


async def execute_export_run(run_store, run_id: str, format: str = "md"):
    export_format = (format or "md").strip().lower()
    run = redact_config(await asyncio.to_thread(run_store.get_run, run_id))
    fn_metrics = _main_attr("_metrics_run_for_export", _metrics_run_for_export)
    metrics = fn_metrics(run_id)

    if not run:
        return Response(
            content=json.dumps({"error": "run_not_found", "run_id": run_id}),
            media_type="application/json",
            status_code=404,
        )

    fn_render = _main_attr("_render_run_markdown", _render_run_markdown)
    markdown = fn_render(run, metrics)
    payload = {"run": run, "metrics": metrics}

    if export_format == "md":
        return Response(
            content=markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.md"'},
        )

    if export_format == "json":
        return Response(
            content=json.dumps(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.json"'},
        )

    if export_format == "zip":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.md", markdown)
            archive.writestr("run.json", json.dumps(run, indent=2))
            archive.writestr("metrics.json", json.dumps(metrics, indent=2))
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
        )

    return Response(
        content=json.dumps({"error": "unsupported_format", "format": export_format}),
        media_type="application/json",
        status_code=400,
    )


def execute_ollama_check(req_council_config, req_attachment_names):
    cfg = copy.deepcopy(req_council_config or get_default_council_config())
    fn_ensure = _main_attr("ensure_models_for_config", ensure_models_for_config)
    status = fn_ensure(cfg, auto_pull=False)
    has_image_input = any(name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) for name in req_attachment_names)
    image_seats = [seat.get("label", seat_id) for seat_id, seat in cfg.items() if supports_image_input(seat.get("model", ""))]
    warnings = []
    if has_image_input and not image_seats:
        warnings.append("Image attachments are selected, but no seat is using a known image-capable local model.")
    if len(req_attachment_names) > 5:
        warnings.append("Large attachment batches can slow the demo. Prefer 1-3 focused files.")
    return {
        **status,
        "warnings": warnings,
        "image_seats": image_seats,
    }


def execute_status_check(run_db_path: str, ollama_ok: bool, feature_flags: dict) -> dict:
    import sqlite3 as _sqlite3
    db_ok = False
    try:
        conn = _sqlite3.connect(run_db_path, timeout=1)
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception:
        pass

    keys = {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
        "groq": bool(os.getenv("GROQ_API_KEY")),
    }
    return {
        "status": "ok" if db_ok else "degraded",
        "ollama": ollama_ok,
        "db": db_ok,
        "keys_configured": keys,
        "features": feature_flags,
    }


def start_server():
    import uvicorn
    host = os.getenv("COUNCIL_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("COUNCIL_PORT", "8765"))
    api_key = os.getenv("COUNCIL_API_KEY", "").strip()

    if host.strip().lower() not in {"127.0.0.1", "localhost"} and not api_key:
        raise SystemExit(
            "ERROR: COUNCIL_API_KEY must be set when binding to non-localhost. "
            "Set COUNCIL_API_KEY or use COUNCIL_HOST=127.0.0.1"
        )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((host, port)) == 0:
            print(f"\n⚠️  Port {port} is already in use by another process.")
            print(f"👉 Free the port with:  lsof -ti :{port} | xargs kill -9")
            print(f"👉 Or use a different port:  COUNCIL_PORT=8766 python run.py\n")
            raise SystemExit(1)

    reload = os.getenv("COUNCIL_RELOAD", "false").strip().lower() == "true"
    print(f"\n🚀 LLM Council starting on http://{host}:{port}")
    uvicorn.run("council.main:app", host=host, port=port, reload=reload)
