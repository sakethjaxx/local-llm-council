"""
CouncilOrchestrator — Universal 3-phase async pipeline

Phase 1 │ Independent Analysis  — Members analyze in parallel
Phase 2 │ Cross-Review          — Each member critiques all OTHER analyses
Phase 3 │ Chairman Decision     — Synthesizes everything → final call
"""

import asyncio
import json
import os
import random
import re
import time
import contextlib
from pathlib import Path
from typing import AsyncIterator, Optional
import litellm
import tiktoken
from budget_profiles import token_budget_for
from hardware_detect import get_default_council_config
from cloud_keys import litellm_kwargs_for_model
from logging_utils import get_logger
from memory_store import memory_store as memory_engine
from io_parser import format_attachments_for_prompt, parse_input
from search_engine import get_search_context
from metrics_store import metrics_store
from provider_caps import caps_for, supports_image_input
from project_fingerprint import fingerprint
from run_store import run_store
from skill_registry import skill_registry
from shutdown_state import is_shutdown_requested
import smart_phase
from summarizer import chunk_and_summarize
from pydantic import BaseModel
from typing import List


logger = get_logger(__name__)
_TOKEN_ENCODINGS: dict[str, object] = {}

# Per-call wall-clock ceiling for every LLM request. Without this a hung
# provider connection stalls a member/phase indefinitely (only interruptible if
# chunks keep arriving). Configurable via env for slow local hardware.
LLM_TIMEOUT_S = float(os.getenv("COUNCIL_LLM_TIMEOUT", "180"))

# Upper bound on how many council members may call an LLM concurrently. Roster
# size is client/dynamic-swarm controlled, so this is the backpressure valve
# that stops an unbounded stampede against Ollama/cloud providers.
MAX_PARALLEL_MEMBERS = max(1, int(os.getenv("COUNCIL_MAX_PARALLEL_MEMBERS", "4")))

# Hard ceiling on roster size regardless of what a client config or the dynamic
# swarm produces — caps total task/queue creation per run.
MAX_COUNCIL_MEMBERS = 8

# Max execute_python tool-call recursion depth per member (S2 hardening).
MAX_TOOL_DEPTH = 3


# tiktoken/cl100k_base is only the tokenizer for OpenAI models. For everything
# else (the primary local Ollama fleet — Qwen/Llama/Mistral/Gemma/DeepSeek — plus
# Anthropic/Gemini) it is a proxy that typically UNDER-counts, which would let the
# budget math overflow the real context window. We inflate non-OpenAI estimates by
# a safety margin so truncation stays conservative.
_OPENAI_MODEL_PREFIXES = ("gpt-", "gpt3", "gpt4", "o1", "o3", "o4", "chatgpt", "text-embedding", "davinci", "curie")
TOKEN_SAFETY_MARGIN = 1.15


def _is_openai_model(model: str) -> bool:
    base = (model or "").replace("ollama/", "").split("/")[-1].lower()
    return any(base.startswith(prefix) for prefix in _OPENAI_MODEL_PREFIXES)


def _count_tokens(model: str, text: str) -> int:
    text = text or ""
    try:
        encoding_key = model or "default"
        if encoding_key not in _TOKEN_ENCODINGS:
            try:
                _TOKEN_ENCODINGS[encoding_key] = tiktoken.encoding_for_model(model.replace("ollama/", ""))
            except KeyError:
                _TOKEN_ENCODINGS[encoding_key] = tiktoken.get_encoding("cl100k_base")
        count = len(_TOKEN_ENCODINGS[encoding_key].encode(text))
    except Exception:
        try:
            count = litellm.token_counter(model=model, text=text)
        except Exception:
            count = len(text) // 4
    if not _is_openai_model(model):
        count = int(count * TOKEN_SAFETY_MARGIN)
    return count


def _truncate_to_token_budget(model: str, text: str, max_tokens: int) -> str:
    marker = "\n[truncated]"
    if max_tokens <= 0:
        return ""
    if _count_tokens(model, text) <= max_tokens:
        return text

    # If even the bare marker doesn't fit, return nothing.
    if _count_tokens(model, marker) > max_tokens:
        return ""

    # Binary-search on the MARKER-INCLUDED candidate so the returned string is
    # guaranteed <= max_tokens. (The token safety margin makes _count_tokens
    # non-additive, so measuring text and marker separately can overshoot.)
    low = 0
    high = len(text)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid]
        if _count_tokens(model, candidate + marker) <= max_tokens:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best + marker


def _render_fair_sections(model: str, items: list[tuple[str, str]], budget: int, head_fmt: str) -> str:
    """Render labelled sections so each item gets an EQUAL share of the token
    budget and is individually truncated. Prevents the tail-drop bias where the
    last members are always the ones cut under context pressure."""
    if not items or budget <= 0:
        return ""
    per_item = max(1, budget // len(items))
    out = ""
    for label, text in items:
        head = head_fmt.format(label=label)
        body_budget = max(1, per_item - _count_tokens(model, head) - 2)
        out += head + _truncate_to_token_budget(model, text, body_budget) + "\n\n"
    return out


class ChairmanDecision(BaseModel):
    verdict: str
    risk_score: int
    action_items: List[str]
    consensus: List[str] = []
    disputes: List[str] = []


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


def parse_chairman_response(raw: str) -> dict:
    def normalize(result: dict, tier: str) -> dict:
        consensus = result.get("consensus")
        if isinstance(consensus, str):
            consensus = [consensus] if consensus else []
        elif not isinstance(consensus, list):
            consensus = []
        return {
            "verdict": result.get("verdict", "parse_failed"),
            "risk_score": result.get("risk_score", -1),
            "action_items": result.get("action_items", []),
            "consensus": consensus,
            "disputes": result.get("disputes", []),
            "_parse_tier": result.get("_parse_tier", tier),
        }

    try:
        return normalize(json.loads(raw), "json")
    except Exception:
        pass

    try:
        stripped = re.sub(r"^```(?:json)?\n?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        return normalize(json.loads(stripped), "fenced_json")
    except Exception:
        pass

    # Tolerant repair: grab the outermost {...} (handles leading/trailing prose
    # and inline fences) and drop trailing commas before the closing brace/bracket.
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            candidate = raw[start:end + 1]
            candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
            return normalize(json.loads(candidate), "json_repaired")
    except Exception:
        pass

    verdict_match = re.search(r'"verdict"\s*:\s*"([^"]+)"', raw)
    risk_match = re.search(r'"risk_score"\s*:\s*(\d+(?:\.\d+)?)', raw)
    if verdict_match or risk_match:
        return {
            "verdict": verdict_match.group(1) if verdict_match else "parse_failed",
            "risk_score": float(risk_match.group(1)) if risk_match else -1,
            "action_items": [],
            "consensus": [],
            "disputes": [],
            "_parse_tier": "regex_extracted",
        }

    return {
        "verdict": "parse_failed",
        "risk_score": -1,
        "action_items": [],
        "consensus": [],
        "disputes": [],
        "_parse_tier": "parse_failed",
    }


def _specificity_score(chairman_result: dict, raw_text: str) -> float:
    # Distinguish "unparseable output" (-1.0 sentinel) from "parsed but vague"
    # (0.0) so quality metrics don't conflate a broken response with a weak one.
    if chairman_result.get("_parse_tier") == "parse_failed":
        return -1.0
    action_items = chairman_result.get("action_items") or []
    if not action_items:
        return 0.0

    scored_items = 0.0
    for item in action_items:
        text = str(item)
        signals = 0
        if len(text.split()) >= 6:
            signals += 1
        if re.search(r"\b[\w./-]+\.(py|js|ts|html|css|md|json|yml|yaml)(?::\d+)?\b", text):
            signals += 1
        if re.search(r"\b(add|remove|replace|validate|test|document|limit|sanitize|retry|measure)\b", text, re.IGNORECASE):
            signals += 1
        if re.search(r"\d", text):
            signals += 1
        scored_items += min(signals, 3) / 3

    structure_bonus = 0.1 if any(label in raw_text.lower() for label in ("risk", "action", "because", "owner")) else 0.0
    return round(min(1.0, (scored_items / len(action_items)) + structure_bonus), 3)


# Make litellm not spam the console
litellm.suppress_debug_info = True

def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "agent_prompts" / "phase_prompts" / name
    return path.read_text()


PHASE1_PROMPT = _load_prompt("phase1_analyze.txt")
PHASE2_PROMPT = _load_prompt("phase2_review.txt")
PHASE3_PROMPT = _load_prompt("phase3_chairman.txt")

DEFAULT_MEMBER_CONFIG = get_default_council_config()

class CouncilOrchestrator:
    def __init__(self, **kwargs):
        self._token_budget = token_budget_for(kwargs.get("token_budget_profile"))
        self._member_semaphore = None

    def _member_slot(self):
        """Concurrency gate for member LLM calls. Falls back to a no-op context
        if a caller invokes a worker outside of run() (e.g. in unit tests)."""
        if self._member_semaphore is None:
            return contextlib.nullcontext()
        return self._member_semaphore

    def _python_tool_enabled_for_model(self, model: str) -> bool:
        if os.getenv("COUNCIL_ENABLE_PYTHON_TOOL", "false").lower() != "true":
            return False
        return caps_for(model)[0].tool_use

    def _build_messages(self, model: str, system_prompt: str, user_content) -> list[dict]:
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

    async def _stream_llm_to_queue(
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

        # Cap tool-call recursion: each iteration spawns a fresh sandbox container,
        # and an injected model could otherwise loop execute_python indefinitely
        # (DoS + cloud-cost amplification). Stop offering the tool past the limit.
        tools = None
        if phase == 1 and tool_depth < MAX_TOOL_DEPTH and self._python_tool_enabled_for_model(cfg.get("model", "")):
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

        async def record_success_once():
            if not run_id:
                return
            normalized_usage = _usage_to_dict(final_usage) or {}
            await asyncio.to_thread(
                run_store.record_phase_output,
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
                    timeout=LLM_TIMEOUT_S,
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

                final_attempt = attempt + 1
                final_latency_ms = int((time.perf_counter() - started_at) * 1000)
                final_usage = usage
                success = True
                logger.info("llm_call_completed", extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label")})
                metrics_store.record_llm_call(
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

                # Check for Tool execution
                if phase == 1 and tool_calls:
                    from tool_repl import execute_python
                    followup_completed = False
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
                            
                            # Build the messages list appropriately
                            # Add assistant's message with tool calls
                            messages.append({"role": "assistant", "content": full_text or None, "tool_calls": tool_calls})
                            # Add tool response
                            messages.append({"role": "tool", "tool_call_id": tc["id"], "name": "execute_python", "content": output})

                            # Recursive call to finish analysis
                            additional_text = await self._stream_llm_to_queue(
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
                    extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label"), "attempt": attempt + 1, "error": error_msg},
                )
                error_lower = error_msg.lower()
                is_retryable = any(marker in error_lower for marker in [
                    "timeout", "timed out", "rate limit", "service unavailable",
                    "503", "502", "429", "connection", "reset by peer"
                ])
                is_permanent = any(marker in error_lower for marker in [
                    "model not found", "not found", "invalid api key", "unauthorized",
                    "401", "403", "no such model", "pull model"
                ])
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
                if is_permanent or (not is_retryable and attempt > 0) or attempt >= max_retries - 1:
                    logger.error(
                        "llm_call_failed",
                        extra={"phase": phase, "model": cfg.get("model"), "label": cfg.get("label"), "attempts": max_retries},
                    )
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

        if success:
            await record_success_once()
        elif errored and run_id:
            # Persist the errored phase output so the DB matches what was streamed
            # to the client, instead of silently dropping it.
            await asyncio.to_thread(
                run_store.record_phase_output,
                run_id, phase, member_id, full_text,
                None, None, final_latency_ms, "error", final_attempt,
            )
        if emit_done:
            done_event = {"type": "member_done", "member": member_id, "full_text": full_text, "errored": errored}
            if errored:
                done_event["error"] = last_error
            await queue.put(done_event)
        return full_text

    async def _member_analyze(
        self,
        member_id: str,
        cfg: dict,
        text: str,
        attachments: Optional[list[dict]],
        queue: asyncio.Queue,
        run_id: Optional[str] = None,
    ):
        system_prompt = PHASE1_PROMPT.format(persona=cfg.get("persona", ""))

        content = []
        for attachment in attachments or []:
            if (
                attachment.get("kind") == "image"
                and attachment.get("data")
                and supports_image_input(cfg.get("model", ""))
            ):
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{attachment.get('content_type', 'image/png')};base64,{attachment['data']}"},
                })
        if text:
            content.append({"type": "text", "text": f"Topic / Context:\n{text}"})
        if not content:
            content.append({"type": "text", "text": "No context provided — analyze the request based on your persona."})

        messages = self._build_messages(cfg.get("model", ""), system_prompt, content)
        async with self._member_slot():
            await self._stream_llm_to_queue(
                member_id,
                cfg,
                1,
                messages,
                queue,
                self._token_budget["phase1"],
                run_id=run_id,
            )

    async def _member_review(
        self,
        member_id: str,
        cfg: dict,
        members_config: dict,
        analyses: dict[str, str],
        queue: asyncio.Queue,
        run_id: Optional[str] = None,
    ):
        system_prompt = PHASE2_PROMPT.format(persona=cfg.get("persona", ""))

        model_id = cfg.get("model", "")
        context_window = caps_for(model_id)[0].context_window or 4096
        header = "You are reviewing analyses from your peers:\n\n"
        max_total_input_tokens = max(125, context_window - self._token_budget["phase2"] - 800)
        peers_budget = max(1, max_total_input_tokens - _count_tokens(model_id, header))
        peer_items = [
            (members_config[peer_id].get("label", peer_id), analysis)
            for peer_id, analysis in analyses.items()
            if peer_id != member_id
        ]
        # Fair-share the budget across peers so every peer's analysis survives
        # under context pressure, rather than truncating the concatenated blob
        # (which dropped later peers wholesale).
        prompt = header + _render_fair_sections(model_id, peer_items, peers_budget, "--- {label} ---\n")
        messages = self._build_messages(cfg.get("model", ""), system_prompt, prompt)
        async with self._member_slot():
            await self._stream_llm_to_queue(
                member_id,
                cfg,
                2,
                messages,
                queue,
                self._token_budget["phase2"],
                run_id=run_id,
            )

    async def _chairman_decide(
        self,
        chairman_cfg: dict,
        members_config: dict,
        analyses: dict[str, str],
        reviews: dict[str, str],
        queue: asyncio.Queue,
        run_id: Optional[str] = None,
        phase2_note: Optional[str] = None,
    ):
        phase2_skipped = phase2_note is not None
        chairman_model = chairman_cfg.get("model", "")

        # 1. Chairman Web Search (Optional). Detect disputes over REAL content —
        # when Phase 2 was skipped the "reviews" are stubs, so use the analyses.
        search_results = await get_search_context(
            analyses if phase2_skipped else reviews, chairman_cfg["model"]
        )

        context_window = caps_for(chairman_model)[0].context_window or 4096
        max_input_tokens = max(1, context_window - self._token_budget["phase3"] - 500)

        header = ""
        if search_results:
            header += search_results + "\n\n"

        # Peer-review block. On the skip path, tell the chairman honestly that
        # Phase 2 did not run (and why) instead of feeding it fabricated
        # "unanimous agreement" stubs as if they were real cross-review.
        if phase2_skipped:
            peer_block = (
                "\n--- PEER REVIEWS ---\n"
                f"[Phase 2 cross-review was SKIPPED: {phase2_note}. No peer critiques "
                "were produced — derive consensus and disputes yourself from the "
                "Phase 1 analyses below.]\n\n"
            )
        else:
            review_items = [
                (members_config.get(r, {}).get("label", r), text) for r, text in reviews.items()
            ]

        analysis_items = [
            (members_config.get(m, {}).get("label", m), text) for m, text in analyses.items()
        ]

        budget_after_header = max(1, max_input_tokens - _count_tokens(chairman_model, header))
        if phase2_skipped:
            analyses_budget = max(1, budget_after_header - _count_tokens(chairman_model, peer_block))
            analyses_block = _render_fair_sections(
                chairman_model, analysis_items, analyses_budget, "=== {label} ANALYSIS ===\n"
            )
        else:
            # Split remaining budget 60/40 between analyses and peer reviews, each
            # fair-shared internally so every member is represented.
            analyses_budget = max(1, int(budget_after_header * 0.6))
            reviews_budget = max(1, budget_after_header - analyses_budget)
            analyses_block = _render_fair_sections(
                chairman_model, analysis_items, analyses_budget, "=== {label} ANALYSIS ===\n"
            )
            peer_block = "\n--- PEER REVIEWS ---\n\n" + _render_fair_sections(
                chairman_model, review_items, reviews_budget, "=== {label} REVIEW ===\n"
            )

        council_brief = header + analyses_block + peer_block

        # Final safety net in case the fair-share estimate still overshoots.
        if _count_tokens(chairman_model, council_brief) > max_input_tokens:
            council_brief = _truncate_to_token_budget(chairman_model, council_brief, max_input_tokens)
            logger.info(
                "phase3_input_truncated",
                extra={"model": chairman_model, "truncated_chars": len(council_brief)},
            )

        messages = self._build_messages(
            chairman_cfg.get("model", ""),
            PHASE3_PROMPT,
            council_brief,
        )

        # Stream the JSON directly
        await self._stream_llm_to_queue(
            "chairman",
            chairman_cfg,
            3,
            messages,
            queue,
            self._token_budget["phase3"],
            response_format=ChairmanDecision if caps_for(chairman_cfg.get("model", ""))[1].response_format else None,
            run_id=run_id,
        )

    async def run(
        self,
        topic_text: str,
        attachments: Optional[list[dict]],
        custom_config: Optional[dict] = None,
        deep_debate: bool = False,
        run_id: Optional[str] = None,
        token_budget_profile: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        self._token_budget = token_budget_for(token_budget_profile)
        self._member_semaphore = asyncio.Semaphore(MAX_PARALLEL_MEMBERS)
        config = custom_config if custom_config else DEFAULT_MEMBER_CONFIG
        council_members = [k for k in config.keys() if k != "chairman"]
        roster_capped = False
        if len(council_members) > MAX_COUNCIL_MEMBERS:
            logger.warning(
                "roster_capped",
                extra={"requested": len(council_members), "cap": MAX_COUNCIL_MEMBERS},
            )
            council_members = council_members[:MAX_COUNCIL_MEMBERS]
            roster_capped = True
        chairman_cfg = config.get("chairman", DEFAULT_MEMBER_CONFIG["chairman"])
        errored_members: set[str] = set()
        spawned_tasks: list[asyncio.Task] = []
        run_finalized = False
        run_id = run_id or metrics_store.start_run(
            "council",
            {
                "member_count": len(council_members),
                "deep_debate": deep_debate,
                "attachment_count": len(attachments or []),
            },
        )
        project_fp = await asyncio.to_thread(fingerprint, ".")
        await asyncio.to_thread(
            run_store.begin_run,
            run_id,
            topic_text,
            config,
            deep_debate,
            project_fp["hash"],
        )

        try:
            attachment_context = format_attachments_for_prompt(attachments or [])
            combined_topic = topic_text
            if attachment_context:
                combined_topic = (topic_text + "\n\n" + attachment_context).strip()

            scraped_topic = await parse_input(combined_topic)
            past_context = await memory_engine.get_context(scraped_topic, chairman_cfg["model"])
            skills = await skill_registry.get_skills_for_topic(scraped_topic, top_k=3)
            skills_block = skill_registry.format_skills_block(skills)
            topic_context = await chunk_and_summarize(scraped_topic, chairman_cfg["model"])
            full_topic = f"{past_context}{skills_block}{topic_context}"

            if roster_capped:
                yield {"type": "warning", "message": f"Roster exceeded the {MAX_COUNCIL_MEMBERS}-member cap; using the first {MAX_COUNCIL_MEMBERS} members."}

            yield {"type": "phase_start", "phase": 1, "label": "Independent Analysis"}
            for member in council_members:
                yield {"type": "member_thinking", "member": member, "meta": config[member]}

            queue = asyncio.Queue()
            for member in council_members:
                spawned_tasks.append(asyncio.create_task(
                    self._member_analyze(member, config[member], full_topic, attachments, queue, run_id=run_id)
                ))

            analyses = {}
            completed = 0
            while completed < len(council_members):
                event = await queue.get()
                if event["type"] == "member_done":
                    completed += 1
                    analyses[event["member"]] = event["full_text"]
                    if event.get("errored"):
                        errored_members.add(event["member"])
                else:
                    yield event

            reviews = {}
            phase1_divergence = None
            phase2_note = None

            if not deep_debate:
                phase2_note = "Fast mode was enabled (cross-review bypassed for latency)"
                yield {"type": "phase_start", "phase": 2, "label": "Cross-Review (Bypassed - Fast Mode)"}
                for member in council_members:
                    reviews[member] = "SKIPPED - Fast Code Review mode enabled. Bypassing debate for latency."
                    await asyncio.to_thread(run_store.record_phase_output, run_id, 2, member, reviews[member])
                    yield {"type": "member_done", "member": member, "full_text": reviews[member]}
                await asyncio.sleep(0.5)
            else:
                is_unanimous, smart_score = await smart_phase.should_skip(analyses)
                phase1_divergence = round(max(0.0, min(1.0, 1.0 - smart_score)), 4)
                await asyncio.to_thread(run_store.update_smart_phase_score, run_id, smart_score)

                if is_unanimous:
                    phase2_note = f"high inter-analysis agreement (min pairwise similarity {round(smart_score, 3)} > threshold {smart_phase.SKIP_THRESHOLD})"
                    yield {"type": "phase_start", "phase": 2, "label": "Cross-Review (SKIPPED - Unanimous Consensus!)"}
                    for member in council_members:
                        reviews[member] = "SKIPPED - The council was in unanimous agreement during Phase 1. No factual disputes detected."
                        await asyncio.to_thread(run_store.record_phase_output, run_id, 2, member, reviews[member])
                        yield {"type": "member_done", "member": member, "full_text": reviews[member]}
                    await asyncio.sleep(1)
                else:
                    yield {"type": "phase_start", "phase": 2, "label": "Cross-Review"}
                    for member in council_members:
                        yield {"type": "member_thinking", "member": member, "phase": 2, "meta": config[member]}

                    queue = asyncio.Queue()
                    for member in council_members:
                        spawned_tasks.append(asyncio.create_task(
                            self._member_review(member, config[member], config, analyses, queue, run_id=run_id)
                        ))

                    completed = 0
                    while completed < len(council_members):
                        event = await queue.get()
                        if event["type"] == "member_done":
                            completed += 1
                            reviews[event["member"]] = event["full_text"]
                            if event.get("errored"):
                                errored_members.add(event["member"])
                        else:
                            yield event

            yield {"type": "phase_start", "phase": 3, "label": "Chairman's Verdict"}
            yield {"type": "member_thinking", "member": "chairman", "phase": 3, "meta": chairman_cfg}

            queue = asyncio.Queue()
            spawned_tasks.append(asyncio.create_task(
                self._chairman_decide(chairman_cfg, config, analyses, reviews, queue, run_id=run_id, phase2_note=phase2_note)
            ))

            completed = 0
            chairman_decision_text = ""
            while completed < 1:
                event = await queue.get()
                if event["type"] == "member_done":
                    completed += 1
                    chairman_decision_text = event["full_text"]
                    if event.get("errored"):
                        errored_members.add("chairman")
                else:
                    yield event

            chairman_result = parse_chairman_response(chairman_decision_text)
            specificity_score = _specificity_score(chairman_result, chairman_decision_text)
            await asyncio.to_thread(
                run_store.record_phase_output,
                run_id,
                3,
                "chairman",
                chairman_decision_text,
                None,
                None,
                None,
                finish_reason=chairman_result.get("_parse_tier"),
                attempt_number=None,
            )
            await asyncio.to_thread(
                run_store.update_quality_metrics,
                run_id,
                chairman_result.get("_parse_tier"),
                phase1_divergence,
                specificity_score,
            )
            task = asyncio.create_task(
                memory_engine.extract_memory(
                    combined_topic,
                    chairman_decision_text,
                    chairman_cfg["model"],
                    run_id=run_id,
                )
            )
            with contextlib.suppress(Exception):
                task.add_done_callback(lambda t: t.exception())
            final_status = "partial" if errored_members else "completed"
            final_error = (
                "Members failed: " + ", ".join(sorted(errored_members)) if errored_members else None
            )
            metrics_store.finish_run(run_id, status=final_status, error=final_error)
            await asyncio.to_thread(run_store.finish_run, run_id, final_status, final_error)
            run_finalized = True
            task = asyncio.create_task(
                skill_registry.extract_skills(run_id, combined_topic, chairman_cfg["model"])
            )
            with contextlib.suppress(Exception):
                task.add_done_callback(lambda t: t.exception())
            yield {"type": "done", "status": final_status, "errored_members": sorted(errored_members)}
        except Exception as exc:
            metrics_store.finish_run(run_id, status="failed", error=str(exc))
            await asyncio.to_thread(run_store.finish_run, run_id, "failed", str(exc))
            run_finalized = True
            raise
        finally:
            # Cancel any still-running member/chairman tasks (e.g. on client
            # disconnect, which throws GeneratorExit here) so they stop hitting
            # providers and writing to a queue no one drains.
            for t in spawned_tasks:
                if not t.done():
                    t.cancel()
            # If the generator was closed before normal completion, the run is
            # still marked "running" in both stores — finalize it as cancelled.
            if not run_finalized:
                with contextlib.suppress(Exception):
                    metrics_store.finish_run(run_id, status="cancelled", error="Run interrupted before completion")
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(run_store.finish_run, run_id, "cancelled", "Run interrupted before completion")

    async def chat_with_member(
        self,
        member_id: str,
        messages: list,
        custom_config: Optional[dict] = None,
        run_id: Optional[str] = None,
        token_budget_profile: Optional[str] = None,
    ) -> AsyncIterator[str]:
        self._token_budget = token_budget_for(token_budget_profile)
        config = custom_config if custom_config else DEFAULT_MEMBER_CONFIG
        cfg = config.get(member_id, DEFAULT_MEMBER_CONFIG.get(member_id, DEFAULT_MEMBER_CONFIG["chairman"]))
        run_id = run_id or metrics_store.start_run("chat", {"member_id": member_id})
        system_prompt = f"You are a council member engaged in a direct chat. Stay completely in character. YOUR PERSONA: {cfg.get('persona', '')}"

        if caps_for(cfg.get("model", ""))[1].provider == "ollama":
            merged = []
            for m in messages:
                merged.append(f"{m.role.upper()}:\n{m.content}")
            formatted_messages = [{"role": "user", "content": f"{system_prompt}\n\n" + "\n\n".join(merged)}]
        else:
            formatted_messages = [{"role": "system", "content": system_prompt}]
            for m in messages:
                formatted_messages.append({"role": m.role, "content": m.content})

        logger.info("chat_call_started", extra={"model": cfg.get("model"), "label": cfg.get("label"), "member_id": member_id})

        max_retries = 3
        full_text = ""
        output_chars = 0

        for attempt in range(max_retries):
            started_at = time.perf_counter()
            try:
                resp = await litellm.acompletion(
                    model=cfg["model"],
                    messages=formatted_messages,
                    max_tokens=self._token_budget["chat"],
                    stream=True,
                    timeout=LLM_TIMEOUT_S,
                    **litellm_kwargs_for_model(cfg["model"]),
                )
                async for chunk in resp:
                    text_chunk = chunk.choices[0].delta.content or ""
                    if text_chunk:
                        full_text += text_chunk
                        output_chars += len(text_chunk)
                        yield text_chunk
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                metrics_store.record_llm_call(
                    run_id=run_id,
                    member_id=member_id,
                    phase=None,
                    model=cfg.get("model"),
                    label=cfg.get("label"),
                    attempt=attempt + 1,
                    duration_ms=duration_ms,
                    success=True,
                    output_chars=output_chars,
                )
                await asyncio.to_thread(
                    run_store.record_phase_output,
                    run_id, 0, member_id, full_text,
                    None, None,
                    duration_ms,
                )
                metrics_store.finish_run(run_id, status="completed")
                return
            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    "chat_call_attempt_failed",
                    extra={"model": cfg.get("model"), "label": cfg.get("label"), "member_id": member_id, "attempt": attempt + 1, "error": error_msg},
                )
                error_lower = error_msg.lower()
                is_retryable = any(marker in error_lower for marker in [
                    "timeout", "timed out", "rate limit", "service unavailable",
                    "503", "502", "429", "connection", "reset by peer"
                ])
                is_permanent = any(marker in error_lower for marker in [
                    "model not found", "not found", "invalid api key", "unauthorized",
                    "401", "403", "no such model", "pull model"
                ])
                metrics_store.record_llm_call(
                    run_id=run_id,
                    member_id=member_id,
                    phase=None,
                    model=cfg.get("model"),
                    label=cfg.get("label"),
                    attempt=attempt + 1,
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                    success=False,
                    error=error_msg,
                )
                if is_permanent or (not is_retryable and attempt > 0) or attempt >= max_retries - 1:
                    logger.error(
                        "chat_call_failed",
                        extra={"model": cfg.get("model"), "label": cfg.get("label"), "member_id": member_id, "error": error_msg},
                    )
                    metrics_store.finish_run(run_id, status="failed", error=error_msg)
                    yield f"\n[Error connecting to {cfg['label']}: {error_msg}]"
                    return
                if is_retryable and attempt < max_retries - 1:
                    backoff = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(backoff)
