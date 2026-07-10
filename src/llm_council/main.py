"""
LLM Council - Local multi-model decision engine
FastAPI backend with SSE streaming for real-time council progress
"""

import asyncio
import base64
import copy
import io
import json
import os
import pathlib
import signal
import zipfile
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from llm_council.demo_catalog import get_demo_catalog, load_presets
from llm_council.budget_profiles import DEFAULT_TOKEN_BUDGET_PROFILE, TOKEN_BUDGET_PROFILES, normalize_token_budget_profile
from llm_council.cloud_keys import extract_cloud_keys, scoped_cloud_keys
from llm_council.hardware_detect import get_default_council_config, get_hardware_suggestion
from llm_council.io_parser import parse_uploaded_file
from llm_council.logging_utils import get_logger
from llm_council.memory_store import memory_store
from llm_council.metrics_store import metrics_store
from llm_council.ollama_manager import auto_pull_enabled, ensure_models_for_config, ollama_base_url
from llm_council.orchestrator import CouncilOrchestrator, DEFAULT_MEMBER_CONFIG
from llm_council.provider_caps import redact_config, supports_image_input
from llm_council.project_graph import get_project_code_graph
from llm_council.run_store import DB_PATH as RUN_DB_PATH, run_store
from llm_council.shutdown_state import clear_shutdown_request, is_shutdown_requested, request_shutdown, track_active_stream, wait_for_active_streams
from llm_council.skill_registry import skill_registry

load_dotenv()
logger = get_logger(__name__)
PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "web" / "static"
DEMO_SAMPLES_DIR = PACKAGE_DIR / "resources" / "demo_samples"


def _is_localhost(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost"}


def verify_api_key(x_api_key: str = Header(None)) -> None:
    expected_api_key = os.getenv("COUNCIL_API_KEY", "").strip()
    if not expected_api_key:
        return
    if x_api_key != expected_api_key:
        raise HTTPException(status_code=403, detail="Forbidden")


def require_api_key(x_api_key: str = Header(None)) -> None:
    expected_api_key = os.getenv("COUNCIL_API_KEY", "").strip()
    if not expected_api_key:
        raise HTTPException(status_code=403, detail="COUNCIL_API_KEY is required for this endpoint")
    if x_api_key != expected_api_key:
        raise HTTPException(status_code=403, detail="Forbidden")


def _handle_sigterm(signum, frame):
    del signum, frame
    request_shutdown()


try:
    signal.signal(signal.SIGTERM, _handle_sigterm)
except (ValueError, AttributeError):
    pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    clear_shutdown_request()
    asyncio.create_task(asyncio.to_thread(memory_store.rebuild_embeddings))
    asyncio.create_task(asyncio.to_thread(memory_store.prune_memory))
    asyncio.create_task(asyncio.to_thread(skill_registry.deduplicate_skills))
    yield
    if is_shutdown_requested():
        await asyncio.to_thread(wait_for_active_streams, 10.0, 0.1)


app = FastAPI(
    title="LLM Council",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)],
)


def _allowed_origins() -> list[str]:
    configured = os.getenv("COUNCIL_CORS_ORIGINS", "").strip()
    if not configured:
        return ["http://localhost:8765", "http://127.0.0.1:8765"]
    if configured == "*":
        return ["*"]
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _feature_flags() -> dict:
    return {
        "python_tool_enabled": os.getenv("COUNCIL_ENABLE_PYTHON_TOOL", "false").lower() == "true",
        "metrics_file": os.getenv("COUNCIL_METRICS_FILE", "council_metrics.jsonl"),
        "cors_origins": _allowed_origins(),
        "default_provider": "ollama",
        "default_mode": "free-local-open-weights",
        "auto_pull_local_models": auto_pull_enabled(),
        "token_budget_profiles": list(TOKEN_BUDGET_PROFILES.keys()),
        "default_token_budget_profile": DEFAULT_TOKEN_BUDGET_PROFILE,
    }


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _request_cloud_keys(request: Request | None) -> dict[str, str]:
    if request is None:
        return {}
    return extract_cloud_keys(getattr(request, "headers", {}) or {})


def _shutdown_event_payload() -> dict:
    return {"type": "shutdown", "message": "Server shutdown requested. Active stream is closing."}


_HEARTBEAT_DONE = object()

# High-volume streaming events that carry only model output (no roster/config
# secrets). Skipping redaction on these avoids deep-walking every token chunk.
_UNREDACTED_EVENT_TYPES = {"member_token", "chat_token"}


def _sse_payload(event: dict) -> dict:
    if event.get("type") in _UNREDACTED_EVENT_TYPES:
        return event
    return redact_config(event)


async def _with_heartbeat(source, interval: float = 20.0):
    """Wrap an SSE generator, emitting a keep-alive comment when the source is quiet.

    Prevents proxies and browsers from dropping the connection during long
    silent stretches (e.g. cold Ollama model load). The source is drained by a
    single task so contextvar scopes inside it stay in one context.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def _drain():
        try:
            async for chunk in source:
                await queue.put(chunk)
            await queue.put(_HEARTBEAT_DONE)
        except BaseException as exc:
            await queue.put(exc)

    drain_task = asyncio.create_task(_drain())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is _HEARTBEAT_DONE:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        drain_task.cancel()


def _metrics_run_for_export(run_id: str) -> dict:
    for run in metrics_store.list_runs(limit=500):
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
        (
            phase
            for phase in run.get("phases", [])
            if phase.get("phase") == 3 and phase.get("member_id") == "chairman"
        ),
        None,
    )
    if chairman_phase:
        lines.extend([
            "## Chairman Verdict",
            chairman_phase.get("output", ""),
            "",
        ])

    for phase in run.get("phases", []):
        seat = (run.get("roster") or {}).get(phase.get("member_id"), {})
        label = seat.get("label") or phase.get("member_id", "unknown")
        lines.extend([
            f"## Phase {phase.get('phase')} — {label}",
            "",
            phase.get("output", ""),
            "",
        ])

    if run.get("feedback"):
        lines.append("## Feedback")
        lines.append("")
        for item in run["feedback"]:
            lines.append(
                f"- Action {item.get('action_index')}: {item.get('rating')} {item.get('note', '').strip()}".rstrip()
            )
        lines.append("")

    if metrics:
        lines.extend([
            "## Metrics",
            "",
            json.dumps(metrics, indent=2),
            "",
        ])

    return "\n".join(lines)


_cors_origins = _allowed_origins()
if _cors_origins == ["*"]:
    logger.warning(
        "cors_wildcard_enabled",
        extra={"hint": "COUNCIL_CORS_ORIGINS='*' lets any website call this server. "
                        "Set it to your UI origin(s) if COUNCIL_API_KEY is configured."},
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/demo-samples", StaticFiles(directory=DEMO_SAMPLES_DIR), name="demo-samples")


@app.get("/", response_class=HTMLResponse)
async def root():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/council/stream")
async def council_stream(
    request: Request,
    topic_text: str = Form(""),
    council_config: str = Form(None),
    token_budget_profile: str = Form(DEFAULT_TOKEN_BUDGET_PROFILE),
    dynamic_swarm: bool = Form(False),
    deep_debate: bool = Form(False),
    attachments: Optional[list[UploadFile]] = File(None),
):
    """
    SSE endpoint — streams council events as they happen.
    """
    max_files = _int_env("COUNCIL_MAX_FILES", 10)
    max_upload_mb = _int_env("COUNCIL_MAX_UPLOAD_MB", 20)
    max_upload_bytes = max_upload_mb * 1024 * 1024
    max_total_upload_bytes = 50 * 1024 * 1024

    if len(attachments or []) > max_files:
        raise HTTPException(status_code=400, detail=f"Max {max_files} attachments per run")

    parsed_attachments: list[dict] = []
    total_upload_bytes = 0
    for upload in attachments or []:
        if not upload or not upload.filename:
            continue
        raw = await upload.read(max_upload_bytes + 1)
        if len(raw) > max_upload_bytes:
            raise HTTPException(status_code=400, detail=f"File {upload.filename} exceeds {max_upload_mb}MB limit")
        total_upload_bytes += len(raw)
        if total_upload_bytes > max_total_upload_bytes:
            raise HTTPException(status_code=400, detail="Total attachment size exceeds 50MB limit")
        parsed = parse_uploaded_file(upload.filename, upload.content_type or "application/octet-stream", raw)
        if parsed.get("kind") == "image":
            parsed["data"] = base64.b64encode(raw).decode()
        parsed_attachments.append(parsed)

    config_dict = None
    if council_config:
        try:
            config_dict = json.loads(council_config)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="council_config is not valid JSON. Fix the config or omit it to use the default roster.",
            )
        if not isinstance(config_dict, dict):
            raise HTTPException(
                status_code=400,
                detail="council_config must be a JSON object mapping seat ids to seat configs.",
            )

    async def event_generator():
        with track_active_stream():
            request_cloud_keys = _request_cloud_keys(request)
            resolved_budget_profile = normalize_token_budget_profile(token_budget_profile)
            cfg = copy.deepcopy(config_dict or get_default_council_config())
            run_id = metrics_store.start_run(
                "council",
                {
                    "deep_debate": deep_debate,
                    "dynamic_swarm": dynamic_swarm,
                    "attachment_count": len(parsed_attachments),
                    "token_budget_profile": resolved_budget_profile,
                },
            )
            with scoped_cloud_keys(request_cloud_keys):
                if is_shutdown_requested():
                    yield f"data: {json.dumps(_shutdown_event_payload())}\n\n"
                    return
                model_status = await asyncio.to_thread(ensure_models_for_config, cfg, auto_pull=auto_pull_enabled())
                yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
                yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
                if not model_status["ready"]:
                    reason = model_status.get("hint") or ("Missing Ollama models: " + ", ".join(model_status["missing"]))
                    metrics_store.finish_run(run_id, status="failed", error=reason)
                    yield f"data: {json.dumps({'type': 'error', 'message': reason})}\n\n"
                    return
                if dynamic_swarm:
                    from llm_council.router_agent import generate_swarm
                    yield f"data: {json.dumps({'type': 'phase_start', 'phase': 0, 'label': 'Dynamic Swarm Routing'})}\n\n"
                    base_model = cfg.get("chairman", {}).get("model", "ollama/qwen2.5:7b")
                    new_roster = await generate_swarm(topic_text, base_model)
                    if new_roster:
                        new_roster["chairman"] = cfg.get("chairman")
                        cfg = new_roster
                        model_status = await asyncio.to_thread(ensure_models_for_config, cfg, auto_pull=auto_pull_enabled())
                        yield f"data: {json.dumps({'type': 'swarm_routed', 'config': redact_config(cfg)})}\n\n"
                        yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
                        if not model_status["ready"]:
                            cfg = copy.deepcopy(config_dict or get_default_council_config())
                            model_status = await asyncio.to_thread(ensure_models_for_config, cfg, auto_pull=auto_pull_enabled())
                            yield f"data: {json.dumps({'type': 'warning', 'message': 'Dynamic Swarm selected models that are not installed. Falling back to the stable demo roster.'})}\n\n"
                            yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'warning', 'message': 'Dynamic Swarm failed. Falling back to the stable demo roster.'})}\n\n"

                orchestrator = CouncilOrchestrator()
                try:
                    async for event in orchestrator.run(
                        topic_text,
                        parsed_attachments,
                        cfg,
                        deep_debate,
                        run_id=run_id,
                        token_budget_profile=resolved_budget_profile,
                    ):
                        if event.get("type") == "shutdown":
                            yield f"data: {json.dumps(_shutdown_event_payload())}\n\n"
                            return
                        yield f"data: {json.dumps(_sse_payload(event))}\n\n"
                        await asyncio.sleep(0)  # yield to event loop
                except Exception as e:
                    metrics_store.finish_run(run_id, status="failed", error=str(e))
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        _with_heartbeat(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

from pydantic import BaseModel
from typing import List

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    member_id: str
    messages: List[ChatMessage]
    council_config: Optional[dict] = None
    token_budget_profile: str = DEFAULT_TOKEN_BUDGET_PROFILE


class ConfigCheckRequest(BaseModel):
    council_config: Optional[dict] = None
    attachment_names: List[str] = []


class FeedbackRequest(BaseModel):
    action_index: int
    rating: str
    note: str = ""

@app.post("/council/chat")
async def council_chat(req: ChatRequest, request: Request):
    """
    Interactive Debate Mode — stream a reply from a specific member
    """
    orchestrator = CouncilOrchestrator()
    run_id = metrics_store.start_run("chat", {"member_id": req.member_id})
    
    async def chat_stream():
        with track_active_stream():
            request_cloud_keys = _request_cloud_keys(request)
            resolved_budget_profile = normalize_token_budget_profile(req.token_budget_profile)
            with scoped_cloud_keys(request_cloud_keys):
                if is_shutdown_requested():
                    yield f"data: {json.dumps(_shutdown_event_payload())}\n\n"
                    return
                yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
                try:
                    async for chunk in orchestrator.chat_with_member(
                        req.member_id,
                        req.messages,
                        req.council_config,
                        run_id=run_id,
                        token_budget_profile=resolved_budget_profile,
                    ):
                        if is_shutdown_requested():
                            yield f"data: {json.dumps(_shutdown_event_payload())}\n\n"
                            return
                        yield f"data: {json.dumps({'type': 'chat_token', 'chunk': chunk})}\n\n"
                    yield f"data: {json.dumps({'type': 'chat_done'})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        _with_heartbeat(chat_stream()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

from llm_council.memory_store import memory_store as memory_engine

@app.get("/hardware/suggest")
async def hardware_suggest():
    return get_hardware_suggestion()


@app.get("/ollama/status")
async def ollama_status():
    return await asyncio.to_thread(ensure_models_for_config, get_default_council_config(), auto_pull=False)


@app.post("/ollama/check")
async def ollama_check(req: ConfigCheckRequest):
    cfg = copy.deepcopy(req.council_config or get_default_council_config())
    status = await asyncio.to_thread(ensure_models_for_config, cfg, auto_pull=False)
    has_image_input = any(name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) for name in req.attachment_names)
    image_seats = [seat.get("label", seat_id) for seat_id, seat in cfg.items() if supports_image_input(seat.get("model", ""))]
    warnings = []
    if has_image_input and not image_seats:
        warnings.append("Image attachments are selected, but no seat is using a known image-capable local model.")
    if len(req.attachment_names) > 5:
        warnings.append("Large attachment batches can slow the demo. Prefer 1-3 focused files.")
    return {
        **status,
        "warnings": warnings,
        "image_seats": image_seats,
    }


@app.post("/ollama/bootstrap")
async def ollama_bootstrap():
    return await asyncio.to_thread(ensure_models_for_config, get_default_council_config(), auto_pull=True)

@app.get("/council/memory")
async def get_memory():
    return memory_engine.get_graph_data()


def _pick_top_files(graph_data: dict, k: int = 8) -> list[str]:
    stats = graph_data.get("stats", {})
    seen: set[str] = set()
    result: list[str] = []
    for item in stats.get("top_inbound", []) + stats.get("top_outbound", []):
        path = item[0] if isinstance(item, (list, tuple)) else item.get("id", "")
        if path and path not in seen:
            seen.add(path)
            result.append(path)
        if len(result) >= k:
            break
    # pad with isolated files if we have room
    for iso in stats.get("isolated", []):
        if len(result) >= k:
            break
        if iso not in seen:
            seen.add(iso)
            result.append(iso)
    return result


def _read_files_as_attachments(root: str, rel_paths: list[str]) -> list[dict]:
    root_path = pathlib.Path(root).resolve()
    attachments = []
    for rel in rel_paths:
        full = root_path / rel
        try:
            text = full.read_text(encoding="utf-8", errors="replace")[:12000]
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


class ReviewProjectRequest(BaseModel):
    path: str = "."
    deep_debate: bool = False
    council_config: Optional[dict] = None
    token_budget_profile: str = DEFAULT_TOKEN_BUDGET_PROFILE


@app.post("/council/review-project")
async def review_project(req: ReviewProjectRequest, request: Request):
    root = os.path.abspath(req.path)
    if not os.path.isdir(root):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Not a directory: {root}")

    graph_data = await asyncio.to_thread(get_project_code_graph, root)
    top_files = _pick_top_files(graph_data)
    attachments = await asyncio.to_thread(_read_files_as_attachments, root, top_files)
    topic = graph_data.get("review_input", f"Review the project at: {root}")
    cfg = copy.deepcopy(req.council_config or get_default_council_config())

    async def event_generator():
        with track_active_stream():
            request_cloud_keys = _request_cloud_keys(request)
            resolved_budget_profile = normalize_token_budget_profile(req.token_budget_profile)
            run_id = metrics_store.start_run(
                "project_review",
                {
                    "path": root,
                    "files_selected": len(attachments),
                    "deep_debate": req.deep_debate,
                    "token_budget_profile": resolved_budget_profile,
                },
            )
            with scoped_cloud_keys(request_cloud_keys):
                if is_shutdown_requested():
                    yield f"data: {json.dumps(_shutdown_event_payload())}\n\n"
                    return
                yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
                yield f"data: {json.dumps({'type': 'project_info', 'path': root, 'files_selected': top_files, 'total_files': graph_data['stats']['files']})}\n\n"

                model_status = await asyncio.to_thread(ensure_models_for_config, cfg, auto_pull=auto_pull_enabled())
                yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
                if not model_status["ready"]:
                    reason = model_status.get("hint") or ("Missing models: " + ", ".join(model_status["missing"]))
                    yield f"data: {json.dumps({'type': 'error', 'message': reason})}\n\n"
                    return

                orchestrator = CouncilOrchestrator()
                try:
                    async for event in orchestrator.run(
                        topic,
                        attachments,
                        cfg,
                        req.deep_debate,
                        run_id=run_id,
                        token_budget_profile=resolved_budget_profile,
                    ):
                        if event.get("type") == "shutdown":
                            yield f"data: {json.dumps(_shutdown_event_payload())}\n\n"
                            return
                        yield f"data: {json.dumps(_sse_payload(event))}\n\n"
                        await asyncio.sleep(0)
                except Exception as e:
                    metrics_store.finish_run(run_id, status="failed", error=str(e))
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        _with_heartbeat(event_generator()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/project/code-graph")
async def project_code_graph(path: str = "."):
    return await asyncio.to_thread(get_project_code_graph, path)


@app.get("/demo/catalog")
async def demo_catalog():
    return get_demo_catalog()


@app.get("/config/presets")
async def config_presets():
    return load_presets()


@app.get("/runs")
async def list_persisted_runs(limit: int = 50, fingerprint_hash: Optional[str] = None):
    return {"runs": run_store.list_runs(limit=limit, fingerprint_hash=fingerprint_hash)}


@app.get("/skills")
async def list_skills(limit: int = 50, domain: Optional[str] = None):
    skills = await asyncio.to_thread(skill_registry.list_skills, limit, domain)
    return {"skills": skills, "total": len(skills)}


@app.get("/runs/{run_id}")
async def get_persisted_run(run_id: str):
    return run_store.get_run(run_id)


@app.get("/runs/{run_id}/export")
async def export_persisted_run(run_id: str, format: str = "md"):
    export_format = (format or "md").strip().lower()
    run = redact_config(run_store.get_run(run_id))
    metrics = _metrics_run_for_export(run_id)

    if not run:
        return Response(
            content=json.dumps({"error": "run_not_found", "run_id": run_id}),
            media_type="application/json",
            status_code=404,
        )

    markdown = _render_run_markdown(run, metrics)
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


@app.delete("/runs/{run_id}", dependencies=[Depends(require_api_key)])
async def delete_persisted_run(run_id: str):
    deleted = run_store.delete_run(run_id)
    return {"run_id": run_id, "deleted": deleted}


@app.post("/runs/{run_id}/feedback")
async def record_run_feedback(run_id: str, req: FeedbackRequest):
    run_store.record_feedback(run_id, req.action_index, req.rating, req.note)
    # Feedback loop: the rating adjusts the confidence of skills this run produced,
    # which changes their retrieval rank in future councils.
    skill_adjustment = await asyncio.to_thread(skill_registry.apply_feedback, run_id, req.rating)
    return {
        "run_id": run_id,
        "action_index": req.action_index,
        "rating": req.rating,
        "recorded": True,
        "skills_adjusted": skill_adjustment.get("adjusted", 0),
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    import httpx

    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{ollama_base_url()}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "status": "ready" if ollama_ok else "degraded",
        "ollama": ollama_ok,
    }


@app.get("/status", dependencies=[Depends(require_api_key)])
async def status():
    import httpx
    import sqlite3 as _sqlite3

    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{ollama_base_url()}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:
        pass

    db_ok = False
    try:
        conn = _sqlite3.connect(RUN_DB_PATH, timeout=1)
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
        "features": _feature_flags(),
    }


@app.get("/metrics/runs")
async def get_runs(limit: int = 20):
    return {"runs": metrics_store.list_runs(limit=max(1, min(limit, 100)))}


@app.get("/metrics/summary")
async def get_metrics_summary():
    return metrics_store.get_summary()


@app.get("/metrics/quality")
async def get_metrics_quality(limit: int = 100):
    return run_store.list_quality_metrics(limit=max(1, min(limit, 500)))


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("COUNCIL_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("COUNCIL_PORT", "8765"))
    api_key = os.getenv("COUNCIL_API_KEY", "").strip()

    if not _is_localhost(host) and not api_key:
        raise SystemExit(
            "ERROR: COUNCIL_API_KEY must be set when binding to non-localhost. "
            "Set COUNCIL_API_KEY or use COUNCIL_HOST=127.0.0.1"
        )

    reload_enabled = os.getenv("COUNCIL_DEV", "").strip().lower() in {"1", "true", "yes"}
    uvicorn.run("llm_council.main:app", host=host, port=port, reload=reload_enabled)
