import asyncio
import copy
import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from demo_catalog import get_demo_catalog, load_presets
from hardware_detect import get_default_council_config, get_hardware_suggestion, get_model_catalog
from ollama_manager import ensure_models_for_config, pull_model_stream
from provider_caps import MODELS as PROVIDER_MODELS, supports_image_input

router = APIRouter()

_OLLAMA_TAG_WHITELIST = {
    model_id.split("/", 1)[1]
    for model_id, caps in PROVIDER_MODELS.items()
    if caps.provider == "ollama"
}


class ConfigCheckRequest(BaseModel):
    council_config: Optional[dict] = None
    attachment_names: List[str] = []


class DemoLoadRequest(BaseModel):
    scenario_id: str


@router.get("/hardware/suggest")
async def hardware_suggest(strategy: str = "auto"):
    return get_hardware_suggestion(strategy=strategy)


@router.get("/ollama/status")
async def ollama_status():
    return ensure_models_for_config(get_default_council_config(), auto_pull=False)


@router.post("/ollama/check")
async def ollama_check(req: ConfigCheckRequest):
    cfg = copy.deepcopy(req.council_config or get_default_council_config())
    status = ensure_models_for_config(cfg, auto_pull=False)
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


@router.post("/ollama/bootstrap")
async def ollama_bootstrap():
    return ensure_models_for_config(get_default_council_config(), auto_pull=True)


@router.get("/models/catalog")
async def models_catalog():
    return await asyncio.to_thread(get_model_catalog)


@router.get("/models/pull/stream")
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


@router.get("/presets")
async def list_presets():
    return load_presets()


@router.get("/presets/{preset_id}")
async def get_preset(preset_id: str):
    presets = load_presets()
    if preset_id not in presets:
        raise HTTPException(status_code=404, detail=f"Preset not found: {preset_id}")
    return presets[preset_id]


@router.get("/demo/catalog")
async def demo_catalog():
    return get_demo_catalog()


@router.post("/demo/load")
async def demo_load(req: DemoLoadRequest):
    catalog = get_demo_catalog()
    scenarios = {s["id"]: s for s in catalog.get("scenarios", [])}
    if req.scenario_id not in scenarios:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {req.scenario_id}")
    scenario = scenarios[req.scenario_id]
    return {
        "ok": True,
        "scenario": scenario,
        "topic": scenario.get("topic", ""),
        "attachments": scenario.get("attachments", []),
    }
