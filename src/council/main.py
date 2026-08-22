"""
LLM Council - Local multi-model decision engine
FastAPI backend with SSE streaming for real-time council progress
"""

import asyncio
import copy
import json
import os
import pathlib
import signal
import sys
from contextlib import asynccontextmanager
from typing import List, Literal, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from budget_profiles import DEFAULT_TOKEN_BUDGET_PROFILE, normalize_token_budget_profile
from demo_catalog import get_demo_catalog, load_presets
from graph_exporter import export_to_graph_json
from hardware_detect import get_default_council_config, get_hardware_suggestion, get_model_catalog
from logging_utils import get_logger
from main_routes_helper import (
    DEFAULT_REVIEW_FILE_BUDGET,
    MAX_REVIEW_FILE_BUDGET,
    REVIEW_CHAR_BUDGET,
    _allowed_origins,
    _confine_to_project_root,
    _feature_flags,
    _handle_dynamic_swarm,
    _int_env,
    _metrics_run_for_export,
    _parse_config_json,
    _parse_uploads,
    _pick_top_files,
    _read_files_as_attachments,
    _reject_if_overloaded,
    _render_run_markdown,
    _request_cloud_keys,
    _shutdown_event_payload,
    execute_export_run,
    execute_ollama_check,
    execute_status_check,
    format_attachments_for_prompt,
    ingest_folder,
    start_server,
    stream_chat_lifecycle,
    stream_council_lifecycle,
    stream_review_project_lifecycle,
)
from memory_store import memory_store
from metrics_store import metrics_store
from ollama_manager import auto_pull_enabled, ensure_models_for_config, pull_model_stream
from orchestrator import CouncilOrchestrator
from project_graph import get_project_code_graph
from provider_caps import MODELS as PROVIDER_MODELS, redact_config
from run_store import DB_PATH as RUN_DB_PATH, run_store
from schemas import (
    ChatMessage,
    ChatRequest,
    ConfigCheckRequest,
    DemoLoadRequest,
    FeedbackRequest,
    FolderIngestRequest,
    ReviewProjectRequest,
)
from shutdown_state import (
    active_stream_count,
    clear_shutdown_request,
    is_shutdown_requested,
    request_shutdown,
    track_active_stream,
    wait_for_active_streams,
)
from skill_registry import skill_registry

load_dotenv()
logger = get_logger(__name__)
APP_DIR = pathlib.Path(__file__).resolve().parent

MAX_CONCURRENT_STREAMS = max(1, int(os.getenv("COUNCIL_MAX_CONCURRENT_RUNS", "4")))
_OLLAMA_TAG_WHITELIST = {
    model_id.split("/", 1)[1] for model_id, caps in PROVIDER_MODELS.items() if caps.provider == "ollama"
}


def _is_localhost(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost"}


def verify_api_key(x_api_key: str = Header(None)) -> None:
    expected = os.getenv("COUNCIL_API_KEY", "").strip()
    if expected and x_api_key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


def require_api_key(x_api_key: str = Header(None)) -> None:
    expected = os.getenv("COUNCIL_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=403, detail="COUNCIL_API_KEY is required for this endpoint")
    if x_api_key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


def _handle_sigterm(signum, frame):
    del signum, frame
    request_shutdown()


try:
    signal.signal(signal.SIGTERM, _handle_sigterm)
except (ValueError, AttributeError):
    pass


def _consume_background_task(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        return


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    clear_shutdown_request()
    for coro in (
        asyncio.to_thread(memory_store.rebuild_embeddings),
        asyncio.to_thread(memory_store.prune_memory),
        asyncio.to_thread(skill_registry.deduplicate_skills),
    ):
        t = asyncio.create_task(coro)
        t.add_done_callback(_consume_background_task)
    yield
    request_shutdown()
    try:
        await asyncio.wait_for(wait_for_active_streams(), timeout=15.0)
    except asyncio.TimeoutError:
        logger.warning("shutdown_timed_out", extra={"active_streams": active_stream_count()})


app = FastAPI(title="Local LLM Council", lifespan=lifespan, dependencies=[Depends(verify_api_key)])
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins(), allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
app.mount("/demo-samples", StaticFiles(directory=APP_DIR / "demo_samples"), name="demo-samples")


@app.get("/", response_class=HTMLResponse)
async def root():
    return (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/config/default")
async def default_config():
    return get_default_council_config()


@app.get("/config/presets")
@app.get("/presets")
async def list_presets():
    return load_presets()


config_presets = list_presets


@app.get("/presets/{preset_id}")
async def get_preset(preset_id: str):
    presets = load_presets()
    if preset_id not in presets:
        raise HTTPException(status_code=404, detail=f"Preset not found: {preset_id}")
    return presets[preset_id]


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
    _reject_if_overloaded()
    parsed = await _parse_uploads(attachments, _int_env("COUNCIL_MAX_FILES", 10), _int_env("COUNCIL_MAX_UPLOAD_MB", 20), 50 * 1024 * 1024)
    cfg_dict, cfg_err = _parse_config_json(council_config)
    budget = normalize_token_budget_profile(token_budget_profile)
    keys = _request_cloud_keys(request)
    return StreamingResponse(
        stream_council_lifecycle(topic_text, parsed, cfg_dict, cfg_err, budget, deep_debate, dynamic_swarm, keys, _shutdown_event_payload()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/council/chat")
async def council_chat(req: ChatRequest, request: Request):
    _reject_if_overloaded()
    keys = _request_cloud_keys(request)
    budget = normalize_token_budget_profile(req.token_budget_profile)
    run_id = metrics_store.start_run("chat", {"member_id": req.member_id})
    return StreamingResponse(
        stream_chat_lifecycle(req, keys, budget, run_id, _shutdown_event_payload()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/hardware/suggest")
async def hardware_suggest(strategy: str = "auto"):
    return get_hardware_suggestion(strategy=strategy)


@app.get("/ollama/status")
async def ollama_status():
    return ensure_models_for_config(get_default_council_config(), auto_pull=False)


@app.post("/ollama/check")
async def ollama_check(req: ConfigCheckRequest):
    return execute_ollama_check(req.council_config, req.attachment_names)


@app.post("/ollama/bootstrap")
async def ollama_bootstrap():
    return ensure_models_for_config(get_default_council_config(), auto_pull=True)


@app.get("/models/catalog")
async def models_catalog():
    return await asyncio.to_thread(get_model_catalog)


@app.get("/models/pull/stream")
async def models_pull_stream(tag: str):
    if tag not in _OLLAMA_TAG_WHITELIST:
        raise HTTPException(status_code=400, detail=f"Unknown model tag: {tag}")

    async def event_generator():
        async for event in pull_model_stream(tag):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/council/memory")
async def get_memory():
    return memory_store.get_graph_data()


@app.get("/memory-graph/export")
async def export_memory_graph(project_name: str = "local-llm-council"):
    triples = await asyncio.to_thread(memory_store.all_triples)
    formatted = [{"subject": t.subject, "predicate": t.predicate, "object": t.object, "confidence": t.confidence} for t in triples]
    return export_to_graph_json(formatted, corpus_name=project_name)


@app.post("/council/review-project")
async def review_project(req: ReviewProjectRequest, request: Request):
    _reject_if_overloaded()
    root = _confine_to_project_root(req.path)
    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail=f"Not a directory: {root}")
    file_budget = max(1, min(req.max_files or DEFAULT_REVIEW_FILE_BUDGET, MAX_REVIEW_FILE_BUDGET))
    fn_graph = getattr(sys.modules.get("main"), "get_project_code_graph", get_project_code_graph)
    graph_data = await asyncio.to_thread(fn_graph, root)
    fn_top = getattr(sys.modules.get("main"), "_pick_top_files", _pick_top_files)
    top_files = fn_top(graph_data, file_budget)
    fn_read = getattr(sys.modules.get("main"), "_read_files_as_attachments", _read_files_as_attachments)
    attachments = await asyncio.to_thread(fn_read, root, top_files)
    if not attachments:
        raise HTTPException(status_code=400, detail=f"No readable source files found under {root}.")
    topic = graph_data.get("review_input", f"Review the project at: {root}")
    cfg = copy.deepcopy(req.council_config or get_default_council_config())
    keys = _request_cloud_keys(request)
    budget = normalize_token_budget_profile(req.token_budget_profile)
    return StreamingResponse(
        stream_review_project_lifecycle(root, top_files, attachments, topic, cfg, req.deep_debate, budget, graph_data["stats"]["files"], keys, _shutdown_event_payload()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/project/code-graph")
async def project_code_graph(path: str = "."):
    return await asyncio.to_thread(get_project_code_graph, _confine_to_project_root(path))


@app.get("/skills")
async def list_skills(limit: int = 50, domain: Optional[str] = None):
    skills = await asyncio.to_thread(skill_registry.list_skills, limit, domain)
    return {"skills": skills, "total": len(skills)}


@app.get("/demo/catalog")
async def demo_catalog():
    return get_demo_catalog()


@app.post("/demo/load")
async def demo_load(req: DemoLoadRequest):
    catalog = get_demo_catalog()
    scenarios = {s["id"]: s for s in catalog.get("scenarios", [])}
    if req.scenario_id not in scenarios:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {req.scenario_id}")
    scenario = scenarios[req.scenario_id]
    return {"ok": True, "scenario": scenario, "topic": scenario.get("topic", ""), "attachments": scenario.get("attachments", [])}


@app.get("/runs")
async def list_runs(limit: int = 50, fingerprint_hash: Optional[str] = None):
    runs = await asyncio.to_thread(run_store.list_runs, limit, fingerprint_hash)
    return {"runs": runs}


list_persisted_runs = list_runs


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = await asyncio.to_thread(run_store.get_run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


get_persisted_run = get_run


@app.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    deleted = await asyncio.to_thread(run_store.delete_run, run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, "deleted": deleted}


delete_persisted_run = delete_run


@app.delete("/runs")
async def delete_all_runs():
    deleted_count = await asyncio.to_thread(run_store.delete_all_runs)
    return {"deleted_count": deleted_count, "deleted": True}


delete_all_persisted_runs = delete_all_runs


@app.post("/runs/{run_id}/feedback")
async def record_feedback(run_id: str, req: FeedbackRequest):
    if not await asyncio.to_thread(run_store.run_exists, run_id):
        raise HTTPException(status_code=404, detail="run not found")
    await asyncio.to_thread(run_store.record_feedback, run_id, req.action_index, req.rating, req.note)
    return {"run_id": run_id, "action_index": req.action_index, "rating": req.rating, "recorded": True}


record_run_feedback = record_feedback


@app.get("/runs/{run_id}/export")
async def export_run(run_id: str, format: str = "md"):
    return await execute_export_run(run_store, run_id, format)


export_persisted_run = export_run


@app.get("/quality-metrics")
async def get_quality_metrics(limit: int = 100):
    return await asyncio.to_thread(run_store.list_quality_metrics, limit)


@app.get("/metrics")
async def list_metrics(limit: int = 20):
    return metrics_store.list_runs(limit=limit)


@app.get("/metrics/runs")
async def get_runs(limit: int = 20):
    return {"runs": metrics_store.list_runs(limit=max(1, min(limit, 100)))}


get_runs_metrics = get_runs


@app.get("/metrics/summary")
async def get_metrics_summary():
    return metrics_store.get_summary()


@app.get("/metrics/quality")
async def get_metrics_quality(limit: int = 100):
    return await asyncio.to_thread(run_store.list_quality_metrics, max(1, min(limit, 500)))


@app.post("/ingest/folder")
async def ingest_local_folder(payload: FolderIngestRequest):
    if not payload.folder_path:
        raise HTTPException(status_code=400, detail="folder_path is required")
    root = _confine_to_project_root(payload.folder_path)
    if not os.path.exists(root) or not os.path.isdir(root):
        raise HTTPException(status_code=404, detail=f"Folder not found or is not a directory: {payload.folder_path}")
    max_files = max(1, min(payload.max_files or 50, 200))
    fn_ingest = getattr(sys.modules.get("main"), "ingest_folder", ingest_folder)
    attachments = await asyncio.to_thread(fn_ingest, root, max_files)
    formatted = format_attachments_for_prompt(attachments)
    return {"file_count": len(attachments), "attachments": attachments, "formatted_prompt_text": formatted}


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _ollama_ok() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            return r.status_code == 200
    except Exception:
        return False


@app.get("/health/ready")
async def health_ready():
    ollama_ok = await _ollama_ok()
    return {"status": "ready" if ollama_ok else "degraded", "ollama": ollama_ok}


@app.get("/status", dependencies=[Depends(require_api_key)])
async def status():
    return execute_status_check(RUN_DB_PATH, await _ollama_ok(), _feature_flags())


start = start_server

if __name__ == "__main__":
    start()
