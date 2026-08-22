import asyncio
import copy
import json
import sys
from typing import Optional
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from budget_profiles import DEFAULT_TOKEN_BUDGET_PROFILE, normalize_token_budget_profile
from cloud_keys import scoped_cloud_keys
from hardware_detect import get_default_council_config
from logging_utils import get_logger
from metrics_store import metrics_store
from ollama_manager import auto_pull_enabled, ensure_models_for_config
from orchestrator import CouncilOrchestrator
from provider_caps import redact_config
from shutdown_state import is_shutdown_requested, track_active_stream

logger = get_logger(__name__)


def _main_attr(name: str, default):
    main_mod = sys.modules.get("main")
    if main_mod is not None and hasattr(main_mod, name):
        return getattr(main_mod, name)
    return default


async def handle_dynamic_swarm(cfg: dict, topic_text: str, attachments: list[dict]):
    from router_agent import apply_personas_to_roster, generate_swarm
    base_model = cfg.get("chairman", {}).get("model", "ollama/qwen2.5:7b")
    attachment_hints = "\n".join(
        f"- {item.get('filename', 'attachment')}: {str(item.get('summary') or item.get('text') or '')[:240]}"
        for item in attachments
    )
    routing_context = topic_text
    if attachment_hints:
        routing_context += f"\n\nAttached-context summaries:\n{attachment_hints}"
    new_personas = await generate_swarm(routing_context, base_model)
    if new_personas:
        return apply_personas_to_roster(cfg, new_personas), True
    return cfg, False


async def stream_council_lifecycle(
    topic_text: str,
    parsed_attachments: list[dict],
    config_dict: Optional[dict],
    config_parse_error: Optional[str],
    resolved_budget_profile: str,
    deep_debate: bool,
    dynamic_swarm: bool,
    request_cloud_keys: dict,
    shutdown_event_payload: dict,
):
    with track_active_stream():
        m_store = _main_attr("metrics_store", metrics_store)
        cfg = copy.deepcopy(config_dict or get_default_council_config())
        run_id = m_store.start_run(
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
                yield f"data: {json.dumps(shutdown_event_payload)}\n\n"
                return
            fn_ensure = _main_attr("ensure_models_for_config", ensure_models_for_config)
            model_status = await asyncio.to_thread(fn_ensure, cfg, auto_pull_enabled())
            yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
            if config_parse_error:
                yield f"data: {json.dumps({'type': 'warning', 'message': 'Invalid council_config JSON — using default roster. (' + config_parse_error + ')'})}\n\n"
            yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
            if not model_status["ready"]:
                m_store.finish_run(
                    run_id, status="failed", error="Missing Ollama models: " + ", ".join(model_status["missing"])
                )
                yield f"data: {json.dumps({'type': 'error', 'message': 'Missing Ollama models: ' + ', '.join(model_status['missing'])})}\n\n"
                return
            if dynamic_swarm:
                yield f"data: {json.dumps({'type': 'phase_start', 'phase': 0, 'label': 'Dynamic Swarm Routing'})}\n\n"
                cfg, routed = await handle_dynamic_swarm(cfg, topic_text, parsed_attachments)
                if routed:
                    yield f"data: {json.dumps({'type': 'swarm_routed', 'config': redact_config(cfg)})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'warning', 'message': 'Dynamic Swarm failed. Keeping the selected roster and personas.'})}\n\n"

            orchestrator_cls = _main_attr("CouncilOrchestrator", CouncilOrchestrator)
            orchestrator = orchestrator_cls()
            try:
                async for event in orchestrator.run(
                    topic_text, parsed_attachments, cfg, deep_debate,
                    run_id=run_id, token_budget_profile=resolved_budget_profile,
                ):
                    if event.get("type") == "shutdown":
                        yield f"data: {json.dumps(shutdown_event_payload)}\n\n"
                        return
                    yield f"data: {json.dumps(redact_config(event))}\n\n"
                    await asyncio.sleep(0)
            except Exception as e:
                m_store.finish_run(run_id, status="failed", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


async def stream_review_project_lifecycle(
    root: str,
    top_files: list[str],
    attachments: list[dict],
    topic: str,
    cfg: dict,
    req_deep_debate: bool,
    resolved_budget_profile: str,
    total_files: int,
    request_cloud_keys: dict,
    shutdown_event_payload: dict,
):
    with track_active_stream():
        m_store = _main_attr("metrics_store", metrics_store)
        run_id = m_store.start_run(
            "project_review",
            {
                "path": root,
                "files_selected": len(attachments),
                "deep_debate": req_deep_debate,
                "token_budget_profile": resolved_budget_profile,
            },
        )
        with scoped_cloud_keys(request_cloud_keys):
            if is_shutdown_requested():
                yield f"data: {json.dumps(shutdown_event_payload)}\n\n"
                return
            yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
            yield f"data: {json.dumps({'type': 'project_info', 'path': root, 'files_selected': top_files, 'total_files': total_files})}\n\n"

            fn_ensure = _main_attr("ensure_models_for_config", ensure_models_for_config)
            model_status = await asyncio.to_thread(fn_ensure, cfg, auto_pull_enabled())
            yield f"data: {json.dumps({'type': 'model_status', **model_status})}\n\n"
            if not model_status["ready"]:
                m_store.finish_run(
                    run_id, status="failed", error="Missing Ollama models: " + ", ".join(model_status["missing"])
                )
                yield f"data: {json.dumps({'type': 'error', 'message': 'Missing models: ' + ', '.join(model_status['missing'])})}\n\n"
                return

            orchestrator_cls = _main_attr("CouncilOrchestrator", CouncilOrchestrator)
            orchestrator = orchestrator_cls()
            try:
                async for event in orchestrator.run(
                    topic, attachments, cfg, req_deep_debate,
                    run_id=run_id, token_budget_profile=resolved_budget_profile,
                ):
                    if event.get("type") == "shutdown":
                        yield f"data: {json.dumps(shutdown_event_payload)}\n\n"
                        return
                    yield f"data: {json.dumps(redact_config(event))}\n\n"
                    await asyncio.sleep(0)
            except Exception as e:
                m_store.finish_run(run_id, status="failed", error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


async def stream_chat_lifecycle(
    req,
    request_cloud_keys: dict,
    resolved_budget_profile: str,
    run_id: str,
    shutdown_event_payload: dict,
):
    with track_active_stream():
        with scoped_cloud_keys(request_cloud_keys):
            if is_shutdown_requested():
                yield f"data: {json.dumps(shutdown_event_payload)}\n\n"
                return
            yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
            orchestrator_cls = _main_attr("CouncilOrchestrator", CouncilOrchestrator)
            orchestrator = orchestrator_cls()
            try:
                async for chunk in orchestrator.chat_with_member(
                    req.member_id,
                    req.messages,
                    req.council_config,
                    run_id=run_id,
                    token_budget_profile=resolved_budget_profile,
                ):
                    if is_shutdown_requested():
                        yield f"data: {json.dumps(shutdown_event_payload)}\n\n"
                        return
                    yield f"data: {json.dumps({'type': 'chat_token', 'chunk': chunk})}\n\n"
                yield f"data: {json.dumps({'type': 'chat_done'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
