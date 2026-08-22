import asyncio
import json
import os
import random
import sys
import time
from typing import AsyncIterator, Optional

import litellm
from cloud_keys import litellm_kwargs_for_model
from logging_utils import get_logger
from metrics_store import metrics_store
from provider_caps import caps_for
from run_store import run_store
from shutdown_state import is_shutdown_requested

logger = get_logger(__name__)

LLM_TIMEOUT_S = float(os.getenv("COUNCIL_LLM_TIMEOUT", "300"))
ANALYSIS_TEMPERATURE = float(os.getenv("COUNCIL_TEMPERATURE", "0.3"))
CHAIRMAN_TEMPERATURE = float(os.getenv("COUNCIL_CHAIRMAN_TEMPERATURE", "0.1"))
MAX_TOOL_DEPTH = 3

_RETRYABLE_ERROR_MARKERS = (
    "timeout", "timed out", "rate limit", "service unavailable",
    "503", "502", "429", "connection", "reset by peer",
)
_PERMANENT_ERROR_MARKERS = (
    "model not found", "not found", "invalid api key", "unauthorized",
    "401", "403", "no such model", "pull model",
)


def _get_litellm():
    orch = sys.modules.get("orchestrator")
    return getattr(orch, "litellm", litellm)


def _get_run_store():
    orch = sys.modules.get("orchestrator")
    return getattr(orch, "run_store", run_store)


def _temperature_for(cfg: dict, phase: int) -> float:
    """Per-seat override wins; otherwise phase 3 (JSON verdict) runs colder."""
    override = cfg.get("temperature")
    if override is not None:
        try:
            return max(0.0, min(float(override), 2.0))
        except (TypeError, ValueError):
            pass
    return CHAIRMAN_TEMPERATURE if phase == 3 else ANALYSIS_TEMPERATURE


def _top_p_for(cfg: dict) -> Optional[float]:
    """Per-seat top_p override, bounded to [0.0, 1.0]."""
    override = cfg.get("top_p")
    if override is not None:
        try:
            return max(0.0, min(float(override), 1.0))
        except (TypeError, ValueError):
            pass
    return None


def _classify_llm_error(error_msg: str) -> tuple[bool, bool]:
    """Return (is_retryable, is_permanent) for an LLM-call exception message."""
    low = error_msg.lower()
    return (
        any(marker in low for marker in _RETRYABLE_ERROR_MARKERS),
        any(marker in low for marker in _PERMANENT_ERROR_MARKERS),
    )


def _usage_to_dict(usage):
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "dict"):
        return usage.dict()
    if isinstance(usage, dict):
        return usage
    return None


def _python_tool_enabled_for_model(model: str) -> bool:
    if os.getenv("COUNCIL_ENABLE_PYTHON_TOOL", "false").lower() != "true":
        return False
    return caps_for(model)[0].tool_use


def _build_messages(model: str, system_prompt: str, user_content) -> list[dict]:
    if caps_for(model)[1].provider == "ollama":
        if isinstance(user_content, list):
            if any(item.get("type") == "image_url" for item in user_content):
                return [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ]
            text_parts = []
            for item in user_content:
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            user_text = "\n\n".join(part for part in text_parts if part)
        else:
            user_text = str(user_content)

        combined = f"{system_prompt}\n\nUSER INPUT:\n{user_text}".strip()
        return [{"role": "user", "content": combined}]

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def _build_stream_kwargs(cfg: dict, phase: int, messages: list, max_tokens: int, response_format, tool_depth: int):
    tools = None
    if phase == 1 and tool_depth < MAX_TOOL_DEPTH and _python_tool_enabled_for_model(cfg.get("model", "")):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_python",
                    "description": "Execute Python code in a secure sandbox and return the terminal output.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "The Python code to execute."
                            }
                        },
                        "required": ["code"]
                    }
                }
            }
        ]

    kwargs = {
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        "tools": tools,
        "response_format": response_format,
        "timeout": LLM_TIMEOUT_S,
        "temperature": _temperature_for(cfg, phase),
        **litellm_kwargs_for_model(cfg["model"]),
    }
    top_p_val = _top_p_for(cfg)
    if top_p_val is not None:
        kwargs["top_p"] = top_p_val
    return kwargs


async def _consume_chunks(resp, queue: asyncio.Queue, member_id: str):
    full_text = ""
    tool_calls = []
    usage = None
    finish_reason = None

    async for chunk in resp:
        if is_shutdown_requested():
            finish_reason = "shutdown_requested"
            await queue.put({"type": "shutdown", "message": "Server shutdown requested. Ending stream."})
            break
        choice = chunk.choices[0]
        delta = choice.delta
        text_chunk = delta.content or ""
        if text_chunk:
            full_text += text_chunk
            await queue.put({"type": "member_token", "member": member_id, "chunk": text_chunk})

        chunk_finish_reason = getattr(choice, "finish_reason", None)
        if chunk_finish_reason is not None:
            finish_reason = chunk_finish_reason

        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            usage = _usage_to_dict(chunk_usage)

        if hasattr(delta, 'tool_calls') and delta.tool_calls:
            for tc_chunk in delta.tool_calls:
                if len(tool_calls) <= tc_chunk.index:
                    tool_calls.append({"id": tc_chunk.id, "type": "function", "function": {"name": tc_chunk.function.name, "arguments": ""}})
                if tc_chunk.function.arguments:
                    tool_calls[tc_chunk.index]["function"]["arguments"] += tc_chunk.function.arguments

    response_choices = getattr(resp, "choices", None)
    if response_choices:
        response_finish_reason = getattr(response_choices[0], "finish_reason", None)
        if response_finish_reason is not None:
            finish_reason = response_finish_reason

    return full_text, tool_calls, usage, finish_reason


async def _handle_tool_execution(
    orchestrator,
    member_id: str,
    cfg: dict,
    phase: int,
    messages: list,
    queue: asyncio.Queue,
    full_text: str,
    tool_calls: list,
    response_format,
    tool_depth: int,
) -> tuple[str, bool]:
    from tool_repl import execute_python
    for tc in tool_calls:
        if tc["function"]["name"] == "execute_python":
            try:
                args = json.loads(tc["function"]["arguments"])
                code = args.get("code", "")
            except json.JSONDecodeError:
                code = ""

            output = execute_python(code)
            sys_msg = f"\n\n> [Sandbox Execution Result]\n> {output}\n\nContinuing analysis...\n"
            await queue.put({"type": "member_token", "member": member_id, "chunk": sys_msg})

            messages.append({"role": "assistant", "content": full_text or None, "tool_calls": tool_calls})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "name": "execute_python", "content": output})

            additional_text = await orchestrator._stream_llm_to_queue(
                member_id,
                cfg,
                phase,
                messages,
                queue,
                1000,
                response_format=response_format,
                run_id=None,
                emit_done=False,
                tool_depth=tool_depth + 1,
            )
            return full_text + sys_msg + additional_text, True
    return full_text, False


def _handle_stream_error(
    e: Exception,
    cfg: dict,
    phase: int,
    member_id: str,
    run_id: Optional[str],
    attempt: int,
    max_retries: int,
    started_at: float,
) -> tuple[str, bool, bool]:
    deadline_hit = isinstance(e, TimeoutError)
    error_msg = (
        f"Timed out after {LLM_TIMEOUT_S:.0f}s. The model is too slow for this "
        f"hardware — try a smaller model, the Economy token profile, or raise "
        f"COUNCIL_LLM_TIMEOUT."
        if deadline_hit else str(e)
    )
    logger.warning(
        "llm_call_attempt_failed",
        extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label"), "attempt": attempt + 1, "error": error_msg},
    )
    is_retryable, is_permanent = (False, True) if deadline_hit else _classify_llm_error(error_msg)
    metrics_store.record_llm_call(
        run_id=run_id,
        member_id=member_id,
        phase=phase,
        model=cfg.get("model"),
        label=cfg.get("label"),
        attempt=attempt + 1,
        duration_ms=int((time.perf_counter() - started_at) * 1000),
        success=False,
        error=error_msg,
    )
    should_terminate = is_permanent or (not is_retryable and attempt > 0) or attempt >= max_retries - 1
    return error_msg, is_retryable, should_terminate


async def _record_final_stream_output(
    run_id: Optional[str],
    phase: int,
    member_id: str,
    full_text: str,
    success: bool,
    errored: bool,
    final_usage,
    final_latency_ms: Optional[int],
    finish_reason: Optional[str],
    final_attempt: int,
):
    if not run_id:
        return
    active_store = _get_run_store()
    if success:
        normalized_usage = _usage_to_dict(final_usage) or {}
        await asyncio.to_thread(
            active_store.record_phase_output,
            run_id, phase, member_id, full_text,
            normalized_usage.get("prompt_tokens"),
            normalized_usage.get("completion_tokens"),
            final_latency_ms, finish_reason, final_attempt,
        )
    elif errored:
        await asyncio.to_thread(
            active_store.record_phase_output,
            run_id, phase, member_id, full_text,
            None, None, final_latency_ms, "error", final_attempt,
        )


async def stream_llm_to_queue(
    orchestrator,
    member_id: str,
    cfg: dict,
    phase: int,
    messages: list,
    queue: asyncio.Queue,
    max_tokens: int,
    response_format=None,
    run_id: Optional[str] = None,
    emit_done: bool = True,
    tool_depth: int = 0,
) -> str:
    logger.info("llm_call_started", extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label")})

    full_text = ""
    max_retries = 3
    final_usage = None
    finish_reason = None
    final_attempt = 1
    final_latency_ms = None
    success = False
    errored = False
    last_error = None
    active_litellm = _get_litellm()

    for attempt in range(max_retries):
        started_at = time.perf_counter()
        try:
            kwargs = _build_stream_kwargs(cfg, phase, messages, max_tokens, response_format, tool_depth)
            async with asyncio.timeout(LLM_TIMEOUT_S):
                resp = await active_litellm.acompletion(**kwargs)
                full_text, tool_calls, usage, finish_reason = await _consume_chunks(resp, queue, member_id)

            final_attempt = attempt + 1
            final_latency_ms = int((time.perf_counter() - started_at) * 1000)
            final_usage = usage
            success = True
            logger.info("llm_call_completed", extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label")})
            metrics_store.record_llm_call(
                run_id=run_id, member_id=member_id, phase=phase, model=cfg.get("model"),
                label=cfg.get("label"), attempt=final_attempt, duration_ms=final_latency_ms,
                success=True, usage=usage, output_chars=len(full_text), tool_calls=len(tool_calls),
            )

            if phase == 1 and tool_calls:
                full_text, followup_completed = await _handle_tool_execution(
                    orchestrator, member_id, cfg, phase, messages, queue, full_text, tool_calls, response_format, tool_depth
                )
                if followup_completed:
                    break
            break
        except Exception as e:
            error_msg, is_retryable, should_terminate = _handle_stream_error(
                e, cfg, phase, member_id, run_id, attempt, max_retries, started_at
            )
            if should_terminate:
                logger.error("llm_call_failed", extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label"), "attempts": max_retries})
                final_err = f"\n[Error connecting to {cfg['label']}: {error_msg}]"
                full_text += final_err
                errored = True
                last_error = error_msg
                finish_reason = "error"
                await queue.put({"type": "member_token", "member": member_id, "chunk": final_err})
                break
            if is_retryable and attempt < max_retries - 1:
                backoff = (2 ** attempt) + random.uniform(0, 1)
                logger.info("llm_call_retrying", extra={"label": cfg.get("label"), "backoff_s": round(backoff, 3)})
                await asyncio.sleep(backoff)

    await _record_final_stream_output(
        run_id, phase, member_id, full_text, success, errored, final_usage, final_latency_ms, finish_reason, final_attempt
    )

    if emit_done:
        done_event = {"type": "member_done", "member": member_id, "full_text": full_text, "errored": errored}
        if errored:
            done_event["error"] = last_error
        await queue.put(done_event)
    return full_text


async def stream_chat_with_member(
    orchestrator,
    member_id: str,
    messages: list,
    custom_config: Optional[dict] = None,
    run_id: Optional[str] = None,
    token_budget_profile: Optional[str] = None,
    default_config: Optional[dict] = None,
) -> AsyncIterator[str]:
    from budget_profiles import token_budget_for
    budget = token_budget_for(token_budget_profile)
    config = custom_config if custom_config else default_config
    cfg = config.get(member_id, default_config.get(member_id, default_config["chairman"]))
    run_id = run_id or metrics_store.start_run("chat", {"member_id": member_id})
    system_prompt = f"You are a council member engaged in a direct chat. Stay completely in character. YOUR PERSONA: {cfg.get('persona', '')}"

    if caps_for(cfg.get("model", ""))[1].provider == "ollama":
        merged = [f"{m.role.upper()}:\n{m.content}" for m in messages]
        formatted_messages = [{"role": "user", "content": f"{system_prompt}\n\n" + "\n\n".join(merged)}]
    else:
        formatted_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            formatted_messages.append({"role": m.role, "content": m.content})

    logger.info("chat_call_started", extra={"model": cfg.get("model"), "label": cfg.get("label"), "member_id": member_id})
    max_retries = 3
    full_text = ""
    output_chars = 0
    active_litellm = _get_litellm()
    active_store = _get_run_store()

    for attempt in range(max_retries):
        started_at = time.perf_counter()
        try:
            chat_kwargs = {
                "model": cfg["model"],
                "messages": formatted_messages,
                "max_tokens": budget["chat"],
                "stream": True,
                "timeout": LLM_TIMEOUT_S,
                "temperature": _temperature_for(cfg, 0),
                **litellm_kwargs_for_model(cfg["model"]),
            }
            top_p_val = _top_p_for(cfg)
            if top_p_val is not None:
                chat_kwargs["top_p"] = top_p_val

            resp = await active_litellm.acompletion(**chat_kwargs)
            async for chunk in resp:
                text_chunk = chunk.choices[0].delta.content or ""
                if text_chunk:
                    full_text += text_chunk
                    output_chars += len(text_chunk)
                    yield text_chunk
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            metrics_store.record_llm_call(
                run_id=run_id, member_id=member_id, phase=None, model=cfg.get("model"),
                label=cfg.get("label"), attempt=attempt + 1, duration_ms=duration_ms,
                success=True, output_chars=output_chars,
            )
            await asyncio.to_thread(active_store.record_phase_output, run_id, 0, member_id, full_text, None, None, duration_ms)
            metrics_store.finish_run(run_id, status="completed")
            return
        except Exception as e:
            error_msg = str(e)
            logger.warning(
                "chat_call_attempt_failed",
                extra={"model": cfg.get("model"), "label": cfg.get("label"), "member_id": member_id, "attempt": attempt + 1, "error": error_msg},
            )
            is_retryable, is_permanent = _classify_llm_error(error_msg)
            metrics_store.record_llm_call(
                run_id=run_id, member_id=member_id, phase=None, model=cfg.get("model"),
                label=cfg.get("label"), attempt=attempt + 1, duration_ms=int((time.perf_counter() - started_at) * 1000),
                success=False, error=error_msg,
            )
            if is_permanent or (not is_retryable and attempt > 0) or attempt >= max_retries - 1:
                logger.error("chat_call_failed", extra={"model": cfg.get("model"), "label": cfg.get("label"), "member_id": member_id, "error": error_msg})
                metrics_store.finish_run(run_id, status="failed", error=error_msg)
                yield f"\n[Error connecting to {cfg['label']}: {error_msg}]"
                return
            if is_retryable and attempt < max_retries - 1:
                backoff = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(backoff)
