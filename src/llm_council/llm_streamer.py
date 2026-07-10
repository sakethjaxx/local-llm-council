import asyncio
import json
import os
import random
import time
from typing import Optional

import litellm
import tiktoken

from llm_council.cloud_keys import litellm_kwargs_for_model
from llm_council.logging_utils import get_logger
from llm_council.provider_caps import caps_for
from llm_council.shutdown_state import is_shutdown_requested


logger = get_logger(__name__)
_TOKEN_ENCODINGS: dict[str, object] = {}

# Make litellm not spam the console.
litellm.suppress_debug_info = True


def _encoding_for(model: str):
    """Return a tiktoken encoding for the model, or None when unavailable.

    Local (Ollama) models are not covered by tiktoken; cl100k_base is a rough
    proxy but consistently over-counts code, which keeps us safely under real
    context limits rather than overflowing them.
    """
    encoding_key = model or "default"
    if encoding_key not in _TOKEN_ENCODINGS:
        try:
            _TOKEN_ENCODINGS[encoding_key] = tiktoken.encoding_for_model((model or "").replace("ollama/", ""))
        except Exception:
            try:
                _TOKEN_ENCODINGS[encoding_key] = tiktoken.get_encoding("cl100k_base")
            except Exception:
                _TOKEN_ENCODINGS[encoding_key] = None
    return _TOKEN_ENCODINGS[encoding_key]


def count_tokens(model: str, text: str) -> int:
    encoding = _encoding_for(model)
    if encoding is not None:
        try:
            return len(encoding.encode(text or ""))
        except Exception:
            pass
    try:
        return litellm.token_counter(model=model, text=text)
    except Exception:
        return len(text or "") // 4


def truncate_to_token_budget(model: str, text: str, max_tokens: int) -> str:
    marker = "\n[truncated]"
    if max_tokens <= 0:
        return ""
    if count_tokens(model, text) <= max_tokens:
        return text

    marker_tokens = count_tokens(model, marker)
    target_tokens = max_tokens - marker_tokens
    if target_tokens <= 0:
        return marker if marker_tokens <= max_tokens else ""

    # Fast path: encode once, slice the token list, decode. Avoids re-tokenizing
    # the whole prefix O(log n) times in a binary search.
    encoding = _encoding_for(model)
    if encoding is not None:
        try:
            tokens = encoding.encode(text or "")
            if len(tokens) <= target_tokens:
                return text
            return encoding.decode(tokens[:target_tokens]) + marker
        except Exception:
            pass

    # Fallback (no tiktoken encoding): binary search on character length.
    low, high, best = 0, len(text), ""
    while low <= high:
        mid = (low + high) // 2
        if count_tokens(model, text[:mid]) <= target_tokens:
            best = text[:mid]
            low = mid + 1
        else:
            high = mid - 1
    return best + marker


def usage_to_dict(usage):
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "dict"):
        return usage.dict()
    if isinstance(usage, dict):
        return usage
    return None


class LLMStreamer:
    def __init__(self, run_store, metrics_store):
        self.run_store = run_store
        self.metrics_store = metrics_store

    def python_tool_enabled_for_model(self, model: str) -> bool:
        if os.getenv("COUNCIL_ENABLE_PYTHON_TOOL", "false").lower() != "true":
            return False
        return caps_for(model)[0].tool_use

    def build_messages(self, model: str, system_prompt: str, user_content) -> list[dict]:
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

    async def stream(
        self,
        member_id: str,
        cfg: dict,
        phase: int,
        messages: list,
        queue: asyncio.Queue,
        max_tokens: int,
        response_format=None,
        run_id: Optional[str] = None,
        emit_done: bool = True,
    ) -> str:
        logger.info("llm_call_started", extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label")})

        full_text = ""
        max_retries = 3
        final_usage = None
        finish_reason = None
        final_attempt = 1
        final_latency_ms = None
        success = False

        tools = None
        if phase == 1 and self.python_tool_enabled_for_model(cfg.get("model", "")):
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
                                    "description": "The Python code to execute.",
                                }
                            },
                            "required": ["code"],
                        },
                    },
                }
            ]

        async def record_success_once():
            if not run_id:
                return
            normalized_usage = usage_to_dict(final_usage) or {}
            await asyncio.to_thread(
                self.run_store.record_phase_output,
                run_id,
                phase,
                member_id,
                full_text,
                normalized_usage.get("prompt_tokens"),
                normalized_usage.get("completion_tokens"),
                final_latency_ms,
                finish_reason,
                final_attempt,
            )

        for attempt in range(max_retries):
            started_at = time.perf_counter()
            try:
                resp = await litellm.acompletion(
                    model=cfg["model"],
                    messages=messages,
                    max_tokens=max_tokens,
                    stream=True,
                    tools=tools,
                    response_format=response_format,
                    **litellm_kwargs_for_model(cfg["model"]),
                )

                tool_calls = []
                usage = None
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
                        usage = usage_to_dict(chunk_usage)

                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        for tc_chunk in delta.tool_calls:
                            if len(tool_calls) <= tc_chunk.index:
                                tool_calls.append(
                                    {
                                        "id": tc_chunk.id,
                                        "type": "function",
                                        "function": {"name": tc_chunk.function.name, "arguments": ""},
                                    }
                                )
                            if tc_chunk.function.arguments:
                                tool_calls[tc_chunk.index]["function"]["arguments"] += tc_chunk.function.arguments

                response_choices = getattr(resp, "choices", None)
                if response_choices:
                    response_finish_reason = getattr(response_choices[0], "finish_reason", None)
                    if response_finish_reason is not None:
                        finish_reason = response_finish_reason

                final_attempt = attempt + 1
                final_latency_ms = int((time.perf_counter() - started_at) * 1000)
                final_usage = usage
                success = True
                logger.info("llm_call_completed", extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label")})
                self.metrics_store.record_llm_call(
                    run_id=run_id,
                    member_id=member_id,
                    phase=phase,
                    model=cfg.get("model"),
                    label=cfg.get("label"),
                    attempt=final_attempt,
                    duration_ms=final_latency_ms,
                    success=True,
                    usage=usage,
                    output_chars=len(full_text),
                    tool_calls=len(tool_calls),
                )

                if phase == 1 and tool_calls:
                    from llm_council.tool_repl import execute_python

                    followup_completed = False
                    for tc in tool_calls:
                        if tc["function"]["name"] != "execute_python":
                            continue
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

                        additional_text = await self.stream(
                            member_id,
                            cfg,
                            phase,
                            messages,
                            queue,
                            1000,
                            response_format=response_format,
                            run_id=None,
                            emit_done=False,
                        )
                        full_text += sys_msg + additional_text
                        followup_completed = True
                        break
                    if followup_completed:
                        break
                break
            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    "llm_call_attempt_failed",
                    extra={
                        "phase": phase,
                        "model": cfg.get("model"),
                        "label": cfg.get("label"),
                        "attempt": attempt + 1,
                        "error": error_msg,
                    },
                )
                error_lower = error_msg.lower()
                is_retryable = any(
                    marker in error_lower
                    for marker in [
                        "timeout",
                        "timed out",
                        "rate limit",
                        "service unavailable",
                        "503",
                        "502",
                        "429",
                        "connection",
                        "reset by peer",
                    ]
                )
                is_permanent = any(
                    marker in error_lower
                    for marker in [
                        "model not found",
                        "not found",
                        "invalid api key",
                        "unauthorized",
                        "401",
                        "403",
                        "no such model",
                        "pull model",
                    ]
                )
                self.metrics_store.record_llm_call(
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
                if is_permanent or (not is_retryable and attempt > 0) or attempt >= max_retries - 1:
                    logger.error(
                        "llm_call_failed",
                        extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label"), "attempts": max_retries},
                    )
                    final_err = f"\n[Error connecting to {cfg['label']}: {error_msg}]"
                    full_text += final_err
                    await queue.put({"type": "member_token", "member": member_id, "chunk": final_err})
                    break
                if is_retryable and attempt < max_retries - 1:
                    backoff = (2**attempt) + random.uniform(0, 1)
                    logger.info("llm_call_retrying", extra={"label": cfg.get("label"), "backoff_s": round(backoff, 3)})
                    await asyncio.sleep(backoff)

        if success:
            await record_success_once()
        if emit_done:
            await queue.put({"type": "member_done", "member": member_id, "full_text": full_text, "ok": success})
        return full_text


# Backward-compatible private names while callers migrate.
_count_tokens = count_tokens
_truncate_to_token_budget = truncate_to_token_budget
_usage_to_dict = usage_to_dict
