"""
LLM Council - Local multi-model decision engine
FastAPI backend with SSE streaming for real-time council progress
"""

import asyncio
import base64
import copy
import json
import os
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from demo_catalog import get_demo_catalog
from hardware_detect import get_default_council_config, get_hardware_suggestion
from io_parser import parse_uploaded_file
from metrics_store import metrics_store
from ollama_manager import auto_pull_enabled, ensure_models_for_config
from orchestrator import CouncilOrchestrator, DEFAULT_MEMBER_CONFIG
from project_graph import get_project_code_graph

load_dotenv()

app = FastAPI(title="LLM Council", version="1.0.0")


def _allowed_origins() -> list[str]:
    configured = os.getenv("COUNCIL_CORS_ORIGINS", "").strip()
    if not configured:
        return ["http://localhost:8765", "http://127.0.0.1:8765"]
    if configured == "*":
        return ["*"]
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _feature_flags() -> dict:
    return {
        "python_tool_enabled": os.getenv("COUNCIL_ENABLE_PYTHON_TOOL", "true").lower() == "true",
        "metrics_file": os.getenv("COUNCIL_METRICS_FILE", "council_metrics.jsonl"),
        "cors_origins": _allowed_origins(),
        "default_provider": "ollama",
        "default_mode": "free-local-open-weights",
        "auto_pull_local_models": auto_pull_enabled(),
    }


def _vision_capable(model: str) -> bool:
    normalized = (model or "").lower()
    return any(marker in normalized for marker in ("llava", "vision", "gemma3", "qwen2.5vl", "qwen3-vl", "minicpm-v", "moondream"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/demo-samples", StaticFiles(directory="demo_samples"), name="demo-samples")


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html") as f:
        return f.read()


@app.post("/council/stream")
async def council_stream(
    topic_text: str = Form(""),
    council_config: str = Form(None),
    dynamic_swarm: bool = Form(False),
    deep_debate: bool = Form(False),
    attachments: Optional[list[UploadFile]] = File(None),
):
    """
    SSE endpoint — streams council events as they happen.
    """
    parsed_attachments: list[dict] = []
    for upload in attachments or []:
        if not upload or not upload.filename:
            continue
        raw = await upload.read()
        parsed = parse_uploaded_file(upload.filename, upload.content_type or "application/octet-stream", raw)
        if parsed.get("kind") == "image":
            parsed["data"] = base64.b64encode(raw).decode()
        parsed_attachments.append(parsed)

    config_dict = None
    if council_config:
        try:
            config_dict = json.loads(council_config)
        except:
            pass

    async def event_generator():
        cfg = copy.deepcopy(config_dict or get_default_council_config())
        run_id = metrics_store.start_run(
            "council",
            {
                "deep_debate": deep_debate,
                "dynamic_swarm": dynamic_swarm,
                "attachment_count": len(parsed_attachments),
            },
        )
        model_status = ensure_models_for_config(cfg, auto_pull=auto_pull_enabled())
        yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
        yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
        if not model_status["ready"]:
            metrics_store.finish_run(
                run_id,
                status="failed",
                error="Missing Ollama models: " + ", ".join(model_status["missing"]),
            )
            yield f"data: {json.dumps({'type': 'error', 'message': 'Missing Ollama models: ' + ', '.join(model_status['missing'])})}\n\n"
            return
        if dynamic_swarm:
            from router_agent import generate_swarm
            yield f"data: {json.dumps({'type': 'phase_start', 'phase': 0, 'label': 'Dynamic Swarm Routing'})}\n\n"
            base_model = cfg.get("chairman", {}).get("model", "ollama/qwen2.5:7b")
            new_roster = await generate_swarm(topic_text, base_model)
            if new_roster:
                new_roster["chairman"] = cfg.get("chairman")
                cfg = new_roster
                model_status = ensure_models_for_config(cfg, auto_pull=auto_pull_enabled())
                yield f"data: {json.dumps({'type': 'swarm_routed', 'config': cfg})}\n\n"
                yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
                if not model_status["ready"]:
                    cfg = copy.deepcopy(config_dict or get_default_council_config())
                    model_status = ensure_models_for_config(cfg, auto_pull=auto_pull_enabled())
                    yield f"data: {json.dumps({'type': 'warning', 'message': 'Dynamic Swarm selected models that are not installed. Falling back to the stable demo roster.'})}\n\n"
                    yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'warning', 'message': 'Dynamic Swarm failed. Falling back to the stable demo roster.'})}\n\n"

        orchestrator = CouncilOrchestrator()
        try:
            async for event in orchestrator.run(topic_text, parsed_attachments, cfg, deep_debate, run_id=run_id):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)  # yield to event loop
        except Exception as e:
            metrics_store.finish_run(run_id, status="failed", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
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


class ConfigCheckRequest(BaseModel):
    council_config: Optional[dict] = None
    attachment_names: List[str] = []

@app.post("/council/chat")
async def council_chat(req: ChatRequest):
    """
    Interactive Debate Mode — stream a reply from a specific member
    """
    orchestrator = CouncilOrchestrator()
    run_id = metrics_store.start_run("chat", {"member_id": req.member_id})
    
    async def chat_stream():
        yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
        try:
            async for chunk in orchestrator.chat_with_member(req.member_id, req.messages, req.council_config, run_id=run_id):
                yield f"data: {json.dumps({'type': 'chat_token', 'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'type': 'chat_done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        chat_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

from memory_graph import memory_engine

@app.get("/hardware/suggest")
async def hardware_suggest():
    return get_hardware_suggestion()


@app.get("/ollama/status")
async def ollama_status():
    return ensure_models_for_config(get_default_council_config(), auto_pull=False)


@app.post("/ollama/check")
async def ollama_check(req: ConfigCheckRequest):
    cfg = copy.deepcopy(req.council_config or get_default_council_config())
    status = ensure_models_for_config(cfg, auto_pull=False)
    has_image_input = any(name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) for name in req.attachment_names)
    vision_seats = [seat.get("label", seat_id) for seat_id, seat in cfg.items() if _vision_capable(seat.get("model", ""))]
    warnings = []
    if has_image_input and not vision_seats:
        warnings.append("Image attachments are selected, but no seat is using a known vision-capable local model.")
    if len(req.attachment_names) > 5:
        warnings.append("Large attachment batches can slow the demo. Prefer 1-3 focused files.")
    return {
        **status,
        "warnings": warnings,
        "vision_seats": vision_seats,
    }


@app.post("/ollama/bootstrap")
async def ollama_bootstrap():
    return ensure_models_for_config(get_default_council_config(), auto_pull=True)

@app.get("/council/memory")
async def get_memory():
    return memory_engine.get_graph_data()


@app.get("/project/code-graph")
async def project_code_graph():
    return get_project_code_graph()


@app.get("/demo/catalog")
async def demo_catalog():
    return get_demo_catalog()

@app.get("/health")
async def health():
    keys = {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
        "groq": bool(os.getenv("GROQ_API_KEY")),
    }
    return {"status": "ok", "keys_configured": keys, "features": _feature_flags()}


@app.get("/metrics/runs")
async def get_runs(limit: int = 20):
    return {"runs": metrics_store.list_runs(limit=max(1, min(limit, 100)))}


@app.get("/metrics/summary")
async def get_metrics_summary():
    return metrics_store.get_summary()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)
