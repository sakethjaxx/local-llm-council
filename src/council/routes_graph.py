import asyncio
import copy
import json
import os
import pathlib
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from budget_profiles import DEFAULT_TOKEN_BUDGET_PROFILE, normalize_token_budget_profile
from cloud_keys import scoped_cloud_keys
from graph_exporter import export_to_graph_json
from hardware_detect import get_default_council_config
from io_parser import format_attachments_for_prompt, ingest_folder
from memory_store import memory_store
from metrics_store import metrics_store
from ollama_manager import auto_pull_enabled, ensure_models_for_config
from orchestrator import CouncilOrchestrator
from project_graph import get_project_code_graph
from provider_caps import redact_config
from shutdown_state import is_shutdown_requested, track_active_stream
from skill_registry import skill_registry

router = APIRouter()

_BLOCKED_PATH_PREFIXES = (
    "/etc", "/private/etc", "/var", "/var/root", "/root", "/dev", "/usr",
    "/System", "/Library", "/proc", "/sys",
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/.aws"),
    os.path.expanduser("~/.kube"),
    os.path.expanduser("~/.docker"),
    os.path.expanduser("~/.gnupg"),
)

DEFAULT_REVIEW_FILE_BUDGET = 25
MAX_REVIEW_FILE_BUDGET = 120
REVIEW_CHAR_BUDGET = 120_000


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


class FolderIngestRequest(BaseModel):
    folder_path: str
    max_files: Optional[int] = 50


class ReviewProjectRequest(BaseModel):
    path: str = "."
    deep_debate: bool = False
    council_config: Optional[dict] = None
    token_budget_profile: str = DEFAULT_TOKEN_BUDGET_PROFILE
    max_files: int = DEFAULT_REVIEW_FILE_BUDGET


@router.post("/ingest/folder")
async def ingest_local_folder(payload: FolderIngestRequest):
    if not payload.folder_path:
        raise HTTPException(status_code=400, detail="folder_path is required")
    root = _confine_to_project_root(payload.folder_path)
    if not os.path.exists(root) or not os.path.isdir(root):
        raise HTTPException(status_code=404, detail=f"Folder not found or is not a directory: {payload.folder_path}")
    max_files = max(1, min(payload.max_files or 50, 200))
    attachments = await asyncio.to_thread(ingest_folder, root, max_files)
    formatted = format_attachments_for_prompt(attachments)
    return {
        "file_count": len(attachments),
        "attachments": attachments,
        "formatted_prompt_text": formatted,
    }


@router.get("/council/memory")
async def get_memory():
    return memory_store.get_graph_data()


@router.get("/memory-graph/export")
async def export_memory_graph(project_name: str = "local-llm-council"):
    triples = await asyncio.to_thread(memory_store.all_triples)
    formatted_triples = [
        {"subject": t.subject, "predicate": t.predicate, "object": t.object, "confidence": t.confidence}
        for t in triples
    ]
    return export_to_graph_json(formatted_triples, corpus_name=project_name)


@router.get("/project/code-graph")
async def project_code_graph(path: str = "."):
    return await asyncio.to_thread(get_project_code_graph, _confine_to_project_root(path))


@router.get("/skills")
async def list_skills(limit: int = 50, domain: Optional[str] = None):
    skills = await asyncio.to_thread(skill_registry.list_skills, limit, domain)
    return {"skills": skills, "total": len(skills)}


@router.post("/council/review-project")
async def review_project(req: ReviewProjectRequest, request: Request):
    root = _confine_to_project_root(req.path)
    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail=f"Not a directory: {root}")

    file_budget = max(1, min(req.max_files or DEFAULT_REVIEW_FILE_BUDGET, MAX_REVIEW_FILE_BUDGET))
    graph_data = await asyncio.to_thread(get_project_code_graph, root)
    top_files = _pick_top_files(graph_data, file_budget)
    attachments = await asyncio.to_thread(_read_files_as_attachments, root, top_files)
    if not attachments:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No readable source files found under {root}. "
                "Check the path, or confirm the project contains supported source files."
            ),
        )
    topic = graph_data.get("review_input", f"Review the project at: {root}")
    cfg = copy.deepcopy(req.council_config or get_default_council_config())

    async def event_generator():
        with track_active_stream():
            from cloud_keys import extract_cloud_keys
            request_cloud_keys = extract_cloud_keys(dict(request.headers))
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
                    yield f"data: {json.dumps({'type': 'shutdown', 'message': 'Server shutdown requested.'})}\n\n"
                    return
                yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
                yield f"data: {json.dumps({'type': 'project_info', 'path': root, 'files_selected': top_files, 'total_files': graph_data['stats']['files']})}\n\n"

                model_status = await asyncio.to_thread(ensure_models_for_config, cfg, auto_pull_enabled())
                yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
                if not model_status["ready"]:
                    metrics_store.finish_run(
                        run_id, status="failed", error="Missing Ollama models: " + ", ".join(model_status["missing"])
                    )
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Missing models: ' + ', '.join(model_status['missing'])})}\n\n"
                    return

                orchestrator = CouncilOrchestrator()
                try:
                    async for event in orchestrator.run(
                        topic, attachments, cfg, req.deep_debate,
                        run_id=run_id, token_budget_profile=resolved_budget_profile,
                    ):
                        if event.get("type") == "shutdown":
                            yield f"data: {json.dumps({'type': 'shutdown', 'message': 'Server shutdown requested.'})}\n\n"
                            return
                        yield f"data: {json.dumps(redact_config(event))}\n\n"
                        await asyncio.sleep(0)
                except Exception as e:
                    metrics_store.finish_run(run_id, status="failed", error=str(e))
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
