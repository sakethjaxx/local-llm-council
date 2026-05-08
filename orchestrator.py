"""
CouncilOrchestrator — Universal 3-phase async pipeline

Phase 1 │ Independent Analysis  — Members analyze in parallel
Phase 2 │ Cross-Review          — Each member critiques all OTHER analyses
Phase 3 │ Chairman Decision     — Synthesizes everything → final call
"""

import asyncio
import os
import time
from typing import AsyncIterator, Optional
import litellm
from hardware_detect import get_default_council_config
from memory_graph import memory_engine
from io_parser import format_attachments_for_prompt, parse_input
from search_engine import get_search_context
from metrics_store import metrics_store
from smart_phase import check_unanimous_consensus
from summarizer import chunk_and_summarize
import json
from pydantic import BaseModel
from typing import List

class ChairmanDecision(BaseModel):
    verdict: str
    risk_score: int
    action_items: List[str]
    consensus: List[str] = []
    disputes: List[str] = []

# Make litellm not spam the console
litellm.suppress_debug_info = True

SYSTEM_COUNCIL_BASE = """You are a senior council member reviewing a topic or proposal.
Be direct, opinionated, and constructive. Structure your analysis as:
1. STRENGTHS — what looks solid
2. RISKS — blockers, unknowns, or major concerns
3. RECOMMENDATIONS — concrete actions or changes
Keep it under 300 words. Be specific, not generic.

YOUR PERSONA:
{persona}"""

SYSTEM_REVIEWER_BASE = """You are a critical peer reviewer on a council.
You've been given analyses from other AI models reviewing the same topic.
Your job: identify where they agree, where they diverge, and what they MISSED based on your persona.
Be blunt. Under 200 words.

YOUR PERSONA:
{persona}"""

SYSTEM_CHAIRMAN = """You are the Chairman of this AI council.
You've received independent analyses and peer reviews from the council members on a specific topic.
Your job: synthesize ALL inputs and deliver a FINAL DECISION with:
- CONSENSUS POINTS (where all members agree)
- KEY DISPUTES (real disagreements worth noting)
- CHAIRMAN'S VERDICT (your authoritative recommendation — be decisive)
- TOP ACTION ITEMS (numbered, specific, assigned if possible)
Be the tie-breaker. Under 400 words."""

DEFAULT_MEMBER_CONFIG = get_default_council_config()

class CouncilOrchestrator:
    def __init__(self, **kwargs):
        pass

    def _is_ollama_model(self, model: str) -> bool:
        return model.startswith("ollama/")

    def _supports_vision_for_model(self, model: str) -> bool:
        normalized = model.lower()
        vision_markers = ("llava", "vision", "gpt-4o", "claude-3", "gemini")
        return any(marker in normalized for marker in vision_markers)

    def _python_tool_enabled_for_model(self, model: str) -> bool:
        if os.getenv("COUNCIL_ENABLE_PYTHON_TOOL", "true").lower() != "true":
            return False
        # Ollama local models are the default free path; keep them on the
        # simpler chat-only request format unless explicitly reworked.
        return not self._is_ollama_model(model)

    def _supports_response_format(self, model: str) -> bool:
        return not self._is_ollama_model(model)

    def _build_messages(self, model: str, system_prompt: str, user_content) -> list[dict]:
        if self._is_ollama_model(model):
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
    ) -> str:
        print(f"\n[🚀 API REQUEST Phase {phase}] -> Routing to {cfg['model']} ({cfg['label']})")

        full_text = ""
        max_retries = 3

        tools = None
        if phase == 1 and self._python_tool_enabled_for_model(cfg.get("model", "")):
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

        for attempt in range(max_retries):
            started_at = time.perf_counter()
            try:
                resp = await litellm.acompletion(
                    model=cfg["model"],
                    messages=messages,
                    max_tokens=max_tokens,
                    stream=True,
                    tools=tools,
                    response_format=response_format
                )

                tool_calls = []
                usage = None
                async for chunk in resp:
                    delta = chunk.choices[0].delta
                    text_chunk = delta.content or ""
                    if text_chunk:
                        full_text += text_chunk
                        await queue.put({"type": "member_token", "member": member_id, "chunk": text_chunk})

                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        if hasattr(chunk_usage, "model_dump"):
                            usage = chunk_usage.model_dump()
                        elif hasattr(chunk_usage, "dict"):
                            usage = chunk_usage.dict()
                        elif isinstance(chunk_usage, dict):
                            usage = chunk_usage

                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tc_chunk in delta.tool_calls:
                            if len(tool_calls) <= tc_chunk.index:
                                tool_calls.append({"id": tc_chunk.id, "type": "function", "function": {"name": tc_chunk.function.name, "arguments": ""}})
                            if tc_chunk.function.arguments:
                                tool_calls[tc_chunk.index]["function"]["arguments"] += tc_chunk.function.arguments

                print(f"[✅ API RESPONSE Phase {phase}] <- {cfg['label']} completed!")
                metrics_store.record_llm_call(
                    run_id=run_id,
                    member_id=member_id,
                    phase=phase,
                    model=cfg.get("model"),
                    label=cfg.get("label"),
                    attempt=attempt + 1,
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                    success=True,
                    usage=usage,
                    output_chars=len(full_text),
                    tool_calls=len(tool_calls),
                )

                # Check for Tool execution
                if phase == 1 and tool_calls:
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
                                run_id=run_id,
                            )
                            full_text += sys_msg + additional_text
                            return full_text
                break
            except Exception as e:
                error_msg = str(e)
                print(f"[⚠️ API WARNING Phase {phase}] <- {cfg['label']} attempt {attempt+1} failed: {error_msg}")
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
                if attempt < max_retries - 1:
                    print(f"   Retrying {cfg['label']} in 2 seconds...")
                    await asyncio.sleep(2)
                else:
                    print(f"[❌ API ERROR Phase {phase}] <- {cfg['label']} failed after {max_retries} attempts.")
                    final_err = f"\n[Error connecting to {cfg['label']}: {error_msg}]"
                    full_text += final_err
                    await queue.put({"type": "member_token", "member": member_id, "chunk": final_err})
        
        await queue.put({"type": "member_done", "member": member_id, "full_text": full_text})
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
        system_prompt = SYSTEM_COUNCIL_BASE.format(persona=cfg.get("persona", ""))

        content = []
        for attachment in attachments or []:
            if (
                attachment.get("kind") == "image"
                and attachment.get("data")
                and self._supports_vision_for_model(cfg.get("model", ""))
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
        await self._stream_llm_to_queue(member_id, cfg, 1, messages, queue, 600, run_id=run_id)

    async def _member_review(
        self,
        member_id: str,
        cfg: dict,
        members_config: dict,
        analyses: dict[str, str],
        queue: asyncio.Queue,
        run_id: Optional[str] = None,
    ):
        system_prompt = SYSTEM_REVIEWER_BASE.format(persona=cfg.get("persona", ""))

        prompt_parts = ["You are reviewing analyses from your peers:\n"]
        for peer_id, analysis in analyses.items():
            if peer_id == member_id:
                continue
            peer_label = members_config[peer_id].get("label", peer_id)
            prompt_parts.append(f"--- {peer_label} ---\n{analysis}\n")
        
        prompt = "\n".join(prompt_parts)
        messages = self._build_messages(cfg.get("model", ""), system_prompt, prompt)
        await self._stream_llm_to_queue(member_id, cfg, 2, messages, queue, 400, run_id=run_id)

    async def _chairman_decide(
        self,
        chairman_cfg: dict,
        members_config: dict,
        analyses: dict[str, str],
        reviews: dict[str, str],
        queue: asyncio.Queue,
        run_id: Optional[str] = None,
    ):
        # 1. Chairman Web Search (Optional)
        search_results = await get_search_context(reviews, chairman_cfg["model"])

        council_brief = ""
        if search_results:
            council_brief += search_results + "\n\n"
            
        for member, analysis in analyses.items():
            cfg = members_config.get(member, {})
            council_brief += f"=== {cfg.get('label', member)} ANALYSIS ===\n{analysis}\n\n"
        council_brief += "\n--- PEER REVIEWS ---\n\n"
        for reviewer, review in reviews.items():
            cfg = members_config.get(reviewer, {})
            council_brief += f"=== {cfg.get('label', reviewer)} REVIEW ===\n{review}\n\n"

        messages = self._build_messages(
            chairman_cfg.get("model", ""),
            SYSTEM_CHAIRMAN + "\n\nCRITICAL INSTRUCTION: You MUST follow the provided JSON schema. DO NOT wrap the output in markdown ticks.",
            council_brief,
        )

        # Stream the JSON directly
        await self._stream_llm_to_queue(
            "chairman",
            chairman_cfg,
            3,
            messages,
            queue,
            1200,
            response_format=ChairmanDecision if self._supports_response_format(chairman_cfg.get("model", "")) else None,
            run_id=run_id,
        )

    async def run(
        self,
        topic_text: str,
        attachments: Optional[list[dict]],
        custom_config: Optional[dict] = None,
        deep_debate: bool = False,
        run_id: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        config = custom_config if custom_config else DEFAULT_MEMBER_CONFIG
        council_members = [k for k in config.keys() if k != "chairman"]
        chairman_cfg = config.get("chairman", DEFAULT_MEMBER_CONFIG["chairman"])
        run_id = run_id or metrics_store.start_run(
            "council",
            {
                "member_count": len(council_members),
                "deep_debate": deep_debate,
                "attachment_count": len(attachments or []),
            },
        )

        try:
            attachment_context = format_attachments_for_prompt(attachments or [])
            combined_topic = topic_text
            if attachment_context:
                combined_topic = (topic_text + "\n\n" + attachment_context).strip()

            scraped_topic = await parse_input(combined_topic)
            past_context = await memory_engine.get_context(scraped_topic, chairman_cfg["model"])
            full_topic = await chunk_and_summarize(past_context + scraped_topic, chairman_cfg["model"])

            yield {"type": "phase_start", "phase": 1, "label": "Independent Analysis"}
            for member in council_members:
                yield {"type": "member_thinking", "member": member, "meta": config[member]}

            queue = asyncio.Queue()
            for member in council_members:
                asyncio.create_task(
                    self._member_analyze(member, config[member], full_topic, attachments, queue, run_id=run_id)
                )

            analyses = {}
            completed = 0
            while completed < len(council_members):
                event = await queue.get()
                if event["type"] == "member_done":
                    completed += 1
                    analyses[event["member"]] = event["full_text"]
                else:
                    yield event

            reviews = {}

            if not deep_debate:
                yield {"type": "phase_start", "phase": 2, "label": "Cross-Review (Bypassed - Fast Mode)"}
                for member in council_members:
                    reviews[member] = "SKIPPED - Fast Code Review mode enabled. Bypassing debate for latency."
                    yield {"type": "member_done", "member": member, "full_text": reviews[member]}
                await asyncio.sleep(0.5)
            else:
                is_unanimous = await check_unanimous_consensus(analyses)

                if is_unanimous:
                    yield {"type": "phase_start", "phase": 2, "label": "Cross-Review (SKIPPED - Unanimous Consensus!)"}
                    for member in council_members:
                        reviews[member] = "SKIPPED - The council was in unanimous agreement during Phase 1. No factual disputes detected."
                        yield {"type": "member_done", "member": member, "full_text": reviews[member]}
                    await asyncio.sleep(1)
                else:
                    yield {"type": "phase_start", "phase": 2, "label": "Cross-Review"}
                    for member in council_members:
                        yield {"type": "member_thinking", "member": member, "phase": 2, "meta": config[member]}

                    queue = asyncio.Queue()
                    for member in council_members:
                        asyncio.create_task(
                            self._member_review(member, config[member], config, analyses, queue, run_id=run_id)
                        )

                    completed = 0
                    while completed < len(council_members):
                        event = await queue.get()
                        if event["type"] == "member_done":
                            completed += 1
                            reviews[event["member"]] = event["full_text"]
                        else:
                            yield event

            yield {"type": "phase_start", "phase": 3, "label": "Chairman's Verdict"}
            yield {"type": "member_thinking", "member": "chairman", "phase": 3, "meta": chairman_cfg}

            queue = asyncio.Queue()
            asyncio.create_task(
                self._chairman_decide(chairman_cfg, config, analyses, reviews, queue, run_id=run_id)
            )

            completed = 0
            chairman_decision_text = ""
            while completed < 1:
                event = await queue.get()
                if event["type"] == "member_done":
                    completed += 1
                    chairman_decision_text = event["full_text"]
                else:
                    yield event

            asyncio.create_task(memory_engine.extract_memory(combined_topic, chairman_decision_text, chairman_cfg["model"]))
            metrics_store.finish_run(run_id, status="completed")
            yield {"type": "done"}
        except Exception as exc:
            metrics_store.finish_run(run_id, status="failed", error=str(exc))
            raise

    async def chat_with_member(
        self,
        member_id: str,
        messages: list,
        custom_config: Optional[dict] = None,
        run_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        config = custom_config if custom_config else DEFAULT_MEMBER_CONFIG
        cfg = config.get(member_id, DEFAULT_MEMBER_CONFIG.get(member_id, DEFAULT_MEMBER_CONFIG["chairman"]))
        run_id = run_id or metrics_store.start_run("chat", {"member_id": member_id})
        system_prompt = f"You are a council member engaged in a direct chat. Stay completely in character. YOUR PERSONA: {cfg.get('persona', '')}"

        if self._is_ollama_model(cfg.get("model", "")):
            merged = []
            for m in messages:
                merged.append(f"{m.role.upper()}:\n{m.content}")
            formatted_messages = [{"role": "user", "content": f"{system_prompt}\n\n" + "\n\n".join(merged)}]
        else:
            formatted_messages = [{"role": "system", "content": system_prompt}]
            for m in messages:
                formatted_messages.append({"role": m.role, "content": m.content})

        print(f"\n[💬 CHAT REQUEST] -> Routing to {cfg['model']} ({cfg['label']})")

        started_at = time.perf_counter()
        try:
            resp = await litellm.acompletion(
                model=cfg["model"],
                messages=formatted_messages,
                max_tokens=600,
                stream=True
            )
            output_chars = 0
            async for chunk in resp:
                text_chunk = chunk.choices[0].delta.content or ""
                if text_chunk:
                    output_chars += len(text_chunk)
                    yield text_chunk
            metrics_store.record_llm_call(
                run_id=run_id,
                member_id=member_id,
                phase=None,
                model=cfg.get("model"),
                label=cfg.get("label"),
                attempt=1,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                success=True,
                output_chars=output_chars,
            )
            metrics_store.finish_run(run_id, status="completed")
        except Exception as e:
            print(f"[❌ CHAT ERROR] <- {cfg['label']}: {str(e)}")
            metrics_store.record_llm_call(
                run_id=run_id,
                member_id=member_id,
                phase=None,
                model=cfg.get("model"),
                label=cfg.get("label"),
                attempt=1,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                success=False,
                error=str(e),
            )
            metrics_store.finish_run(run_id, status="failed", error=str(e))
            yield f"\n[Error connecting to {cfg['label']}: {str(e)}]"
