"""
CouncilOrchestrator - Universal 3-phase async pipeline.

Phase 1: Independent analysis
Phase 2: Cross-review and optional rebuttal
Phase 3: Chairman decision
"""

import asyncio
import random
import time
from typing import AsyncIterator, Optional

import litellm

import llm_council.smart_phase as smart_phase
from llm_council.budget_profiles import token_budget_for
from llm_council.chairman_result import ChairmanDecision, parse_chairman_response, specificity_score as _specificity_score
from llm_council.cloud_keys import litellm_kwargs_for_model
from llm_council.confidence import agreement_state, council_confidence, enforce_grounding, roster_diversity
from llm_council.hardware_detect import get_default_council_config
from llm_council.io_parser import format_attachments_for_prompt, parse_input
from llm_council.llm_streamer import LLMStreamer, _count_tokens, _truncate_to_token_budget
from llm_council.logging_utils import get_logger
from llm_council.memory_store import memory_store as memory_engine
from llm_council.metrics_store import metrics_store
from llm_council.ollama_manager import ollama_base_url
from llm_council.post_run import PostRunFinalizer
from llm_council.project_fingerprint import fingerprint
from llm_council.provider_caps import caps_for
from llm_council.run_store import run_store
from llm_council.search_engine import get_search_context
from llm_council.seat_executor import PHASE1_PROMPT, PHASE2_PROMPT, PHASE2_REBUTTAL_PROMPT, PHASE3_PROMPT, SeatExecutor
from llm_council.skill_registry import skill_registry
from llm_council.summarizer import chunk_and_summarize


logger = get_logger(__name__)
DEFAULT_MEMBER_CONFIG = get_default_council_config()
LLM_CONNECTION_ERROR_MARKER = "[Error connecting to "


def _looks_like_llm_connection_error(text: str) -> bool:
    return LLM_CONNECTION_ERROR_MARKER in (text or "")


def _member_ok(event: dict) -> bool:
    """A member_done event succeeded unless it says otherwise.

    Prefer the structured `ok` flag emitted by the streamer. Fall back to the
    legacy connection-error marker only when the flag is absent (older callers,
    hand-built test events)."""
    ok = event.get("ok")
    if ok is None:
        return not _looks_like_llm_connection_error(event.get("full_text", ""))
    return bool(ok)


def _seat_failure_message(stage: str, failed_members: list[str], config: dict) -> str:
    labels = [config.get(member, {}).get("label") or member for member in failed_members]
    ollama_failed = any(
        caps_for(config.get(member, {}).get("model", ""))[1].provider == "ollama"
        for member in failed_members
    )
    message = (
        f"{stage} failed for {', '.join(labels)}. "
        "The run stopped before using failed model output as council evidence."
    )
    if ollama_failed:
        message += (
            f" Ollama calls use {ollama_base_url()}; make sure the Ollama app/service is running, "
            "the selected models are pulled, and try fewer experts if local memory is tight."
        )
    return message


class CouncilOrchestrator:
    def __init__(self, **kwargs):
        self._token_budget = token_budget_for(kwargs.get("token_budget_profile"))
        self._streamer = LLMStreamer(run_store, metrics_store)
        self._seat_executor = SeatExecutor(self._build_messages, search_context=get_search_context)
        self._post_run = PostRunFinalizer(run_store, metrics_store, memory_engine, skill_registry)

    def _refresh_services(self) -> None:
        """Rebind injectable services so tests that patch module globals still work."""
        self._streamer.run_store = run_store
        self._streamer.metrics_store = metrics_store
        self._seat_executor.get_search_context = get_search_context
        self._post_run.run_store = run_store
        self._post_run.metrics_store = metrics_store
        self._post_run.memory_engine = memory_engine
        self._post_run.skill_registry = skill_registry

    def _python_tool_enabled_for_model(self, model: str) -> bool:
        return self._streamer.python_tool_enabled_for_model(model)

    def _build_messages(self, model: str, system_prompt: str, user_content) -> list[dict]:
        return self._streamer.build_messages(model, system_prompt, user_content)

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
    ) -> str:
        self._refresh_services()
        return await self._streamer.stream(
            member_id,
            cfg,
            phase,
            messages,
            queue,
            max_tokens,
            response_format=response_format,
            run_id=run_id,
            emit_done=emit_done,
        )

    async def _member_analyze(
        self,
        member_id: str,
        cfg: dict,
        text: str,
        attachments: Optional[list[dict]],
        queue: asyncio.Queue,
        run_id: Optional[str] = None,
    ):
        return await self._seat_executor.analyze(
            member_id,
            cfg,
            text,
            attachments,
            queue,
            self._token_budget,
            self._stream_llm_to_queue,
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
        return await self._seat_executor.review(
            member_id,
            cfg,
            members_config,
            analyses,
            queue,
            self._token_budget,
            self._stream_llm_to_queue,
            run_id=run_id,
        )

    async def _member_rebuttal(
        self,
        member_id: str,
        cfg: dict,
        members_config: dict,
        own_analysis: str,
        reviews: dict[str, str],
        queue: asyncio.Queue,
    ):
        return await self._seat_executor.rebuttal(
            member_id,
            cfg,
            members_config,
            own_analysis,
            reviews,
            queue,
            self._token_budget,
            self._stream_llm_to_queue,
        )

    async def _chairman_decide(
        self,
        chairman_cfg: dict,
        members_config: dict,
        analyses: dict[str, str],
        reviews: dict[str, str],
        queue: asyncio.Queue,
        run_id: Optional[str] = None,
    ):
        self._seat_executor.get_search_context = get_search_context
        return await self._seat_executor.chairman_decide(
            chairman_cfg,
            members_config,
            analyses,
            reviews,
            queue,
            self._token_budget,
            self._stream_llm_to_queue,
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
        self._refresh_services()
        self._token_budget = token_budget_for(token_budget_profile)
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

            member_models = [config[m].get("model", "") for m in council_members]
            diversity_info = roster_diversity(member_models, [config[m] for m in council_members])
            if diversity_info["exact_clones"]:
                only_model = member_models[0]
                yield {
                    "type": "warning",
                    "message": (
                        f"All {len(council_members)} seats use the same model and behavior ({only_model}). "
                        "Their blind spots are correlated - consensus from identical seats is weaker evidence. "
                        "Change a persona, generation parameter, or model for genuine diversity."
                    ),
                }

            yield {"type": "phase_start", "phase": 1, "label": "Independent Analysis"}
            for member in council_members:
                yield {"type": "member_thinking", "member": member, "meta": config[member]}

            queue = asyncio.Queue()
            for member in council_members:
                asyncio.create_task(
                    self._member_analyze(member, config[member], full_topic, attachments, queue, run_id=run_id)
                )

            analyses = {}
            member_ok: dict = {}
            completed = 0
            while completed < len(council_members):
                event = await queue.get()
                if event["type"] == "member_done":
                    completed += 1
                    analyses[event["member"]] = event["full_text"]
                    member_ok[event["member"]] = _member_ok(event)
                yield event

            failed_members = [m for m in council_members if not member_ok.get(m, False)]
            live_members = [m for m in council_members if member_ok.get(m, False)]
            if not live_members:
                raise RuntimeError(_seat_failure_message("Phase 1 analysis", failed_members, config))
            if failed_members:
                dropped_labels = [config[m].get("label", m) for m in failed_members]
                for m in failed_members:
                    analyses.pop(m, None)
                yield {
                    "type": "warning",
                    "message": (
                        f"{', '.join(dropped_labels)} failed to respond and "
                        f"{'was' if len(dropped_labels) == 1 else 'were'} dropped from the council. "
                        f"Continuing with {len(live_members)} seat(s); confidence is reduced accordingly."
                    ),
                }
                council_members = live_members

            reviews = {}
            phase1_divergence = None
            gate_info: dict = {"stances": {}, "stance_sources": {}, "split": False}
            converged_after_rebuttal = None
            member_models_map = {m: config[m].get("model", "") for m in council_members}

            if not deep_debate:
                gate_info["stances"], gate_info["stance_sources"] = await smart_phase.resolve_stances(analyses, member_models_map)
                yield {
                    "type": "phase_start",
                    "phase": 2,
                    "label": "Cross-Review (Skipped — Fast mode: no debate. Enable Deep Debate for cross-examination.)",
                }
                for member in council_members:
                    reviews[member] = "SKIPPED - Fast Code Review mode enabled. Bypassing debate for latency."
                    await asyncio.to_thread(run_store.record_phase_output, run_id, 2, member, reviews[member])
                    yield {"type": "member_done", "member": member, "full_text": reviews[member]}
                await asyncio.sleep(0.5)
            else:
                is_unanimous, smart_score, gate_info = await smart_phase.should_skip(analyses, member_models_map)
                phase1_divergence = round(max(0.0, min(1.0, 1.0 - smart_score)), 4)
                await asyncio.to_thread(run_store.update_smart_phase_score, run_id, smart_score)
                yield {
                    "type": "smart_phase_decision",
                    "skip": is_unanimous,
                    "score": round(smart_score, 4),
                    "reason": gate_info.get("reason", ""),
                    "stances": {m: dict(s) for m, s in gate_info.get("stances", {}).items()},
                    "stance_sources": dict(gate_info.get("stance_sources", {})),
                    "split": gate_info.get("split", False),
                }

                if is_unanimous:
                    yield {
                        "type": "phase_start",
                        "phase": 2,
                        "label": f"Cross-Review (SKIPPED — {gate_info.get('reason', 'unanimous consensus')})",
                    }
                    for member in council_members:
                        reviews[member] = (
                            "SKIPPED - Unanimous agreement in Phase 1: "
                            + gate_info.get("reason", "no disputes detected.")
                        )
                        await asyncio.to_thread(run_store.record_phase_output, run_id, 2, member, reviews[member])
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
                            if _member_ok(event):
                                reviews[event["member"]] = event["full_text"]
                        yield event
                    # A failed cross-review is non-fatal: it is simply excluded as
                    # evidence rather than aborting the run built on healthy analyses.

                    if gate_info.get("split"):
                        yield {"type": "rebuttal_start", "label": "Rebuttal Round — members concede or defend"}

                        queue = asyncio.Queue()
                        for member in council_members:
                            asyncio.create_task(
                                self._member_rebuttal(
                                    member, config[member], config, analyses[member], reviews, queue
                                )
                            )

                        rebuttals = {}
                        completed = 0
                        while completed < len(council_members):
                            event = await queue.get()
                            if event["type"] == "member_done":
                                completed += 1
                                if _member_ok(event):
                                    rebuttals[event["member"]] = event["full_text"]
                            yield event
                        # Failed rebuttals are dropped, not fatal — the debate still
                        # rests on Phase 1 analyses and any surviving reviews.

                        for member, rebuttal_text in rebuttals.items():
                            if not rebuttal_text.strip():
                                continue
                            label = config[member].get("label", member)
                            base_review = reviews.get(member, "")
                            reviews[member] = f"{base_review}\n\n[{label} REBUTTAL]\n{rebuttal_text}".strip()
                            await asyncio.to_thread(
                                run_store.record_phase_output,
                                run_id,
                                2,
                                f"{member}:rebuttal",
                                rebuttal_text,
                            )

                        updated = {m: smart_phase.extract_stance(t) for m, t in rebuttals.items()}
                        final_stances = dict(gate_info.get("stances", {}))
                        for member, stance in updated.items():
                            if stance is not None:
                                final_stances[member] = stance
                                gate_info["stances"][member] = stance
                                gate_info["stance_sources"][member] = "rebuttal"
                        final_verdicts = {s["verdict"] for s in final_stances.values()}
                        converged_after_rebuttal = (
                            len(final_stances) == len(council_members)
                            and len(final_verdicts) == 1
                            and "MIXED" not in final_verdicts
                        )
                        yield {
                            "type": "rebuttal_result",
                            "converged": converged_after_rebuttal,
                            "stances": {m: dict(s) for m, s in final_stances.items()},
                        }

            yield {"type": "phase_start", "phase": 3, "label": "Chairman's Verdict"}
            yield {"type": "member_thinking", "member": "chairman", "phase": 3, "meta": chairman_cfg}

            queue = asyncio.Queue()
            asyncio.create_task(
                self._chairman_decide(chairman_cfg, config, analyses, reviews, queue, run_id=run_id)
            )

            completed = 0
            chairman_decision_text = ""
            chairman_ok = True
            while completed < 1:
                event = await queue.get()
                if event["type"] == "member_done":
                    completed += 1
                    chairman_decision_text = event["full_text"]
                    chairman_ok = _member_ok(event)
                yield event
            if not chairman_ok:
                # Never parse an error string as a verdict — fail the run instead.
                raise RuntimeError(_seat_failure_message("Chairman synthesis", ["chairman"], config))

            chairman_result = parse_chairman_response(chairman_decision_text)
            specificity = _specificity_score(chairman_result, chairman_decision_text)
            member_labels = [config[m].get("label", m) for m in council_members]

            enforced_result, grounding_report = enforce_grounding(chairman_result, member_labels)
            grounding = grounding_report["ratio"]
            if grounding is not None:
                logger.info("chairman_grounding", extra=dict(grounding_report))
            yield {"type": "chairman_grounding", **grounding_report}
            yield {
                "type": "chairman_verdict",
                "verdict": enforced_result.get("verdict"),
                "risk_score": enforced_result.get("risk_score"),
                "action_items": enforced_result.get("action_items", []),
                "consensus": enforced_result.get("consensus", []),
                "disputes": enforced_result.get("disputes", []),
                "parse_tier": enforced_result.get("_parse_tier"),
                "removed_points": grounding_report["removed"],
            }

            agreement = agreement_state(
                deliberated=deep_debate,
                stances=gate_info.get("stances", {}),
                member_count=len(council_members),
                split=gate_info.get("split", False),
                converged_after_rebuttal=converged_after_rebuttal,
            )
            confidence = council_confidence(
                member_models=[member_models_map[m] for m in council_members],
                agreement=agreement,
                grounding_ratio=grounding,
                parse_tier=chairman_result.get("_parse_tier"),
                member_configs=[config[m] for m in council_members],
            )
            yield {
                "type": "council_confidence",
                **confidence,
                "stances": gate_info.get("stances", {}),
                "stance_sources": gate_info.get("stance_sources", {}),
            }

            await self._post_run.finalize_success(
                run_id=run_id,
                combined_topic=combined_topic,
                chairman_text=chairman_decision_text,
                chairman_model=chairman_cfg["model"],
                parse_tier=chairman_result.get("_parse_tier"),
                phase1_divergence=phase1_divergence,
                specificity_score=specificity,
                grounding=grounding,
                confidence_score=confidence["score"],
                stances=gate_info.get("stances", {}),
                stance_sources=gate_info.get("stance_sources", {}),
                agreement=agreement,
            )
            yield {"type": "done"}
        except Exception as exc:
            await self._post_run.finalize_failure(run_id, exc)
            raise

    async def chat_with_member(
        self,
        member_id: str,
        messages: list,
        custom_config: Optional[dict] = None,
        run_id: Optional[str] = None,
        token_budget_profile: Optional[str] = None,
    ) -> AsyncIterator[str]:
        self._refresh_services()
        self._token_budget = token_budget_for(token_budget_profile)
        config = custom_config if custom_config else DEFAULT_MEMBER_CONFIG
        cfg = config.get(member_id, DEFAULT_MEMBER_CONFIG.get(member_id, DEFAULT_MEMBER_CONFIG["chairman"]))
        run_id = run_id or metrics_store.start_run("chat", {"member_id": member_id})
        system_prompt = (
            "You are a council member engaged in a direct chat. Stay completely in character. "
            f"YOUR PERSONA: {cfg.get('persona', '')}"
        )

        if caps_for(cfg.get("model", ""))[1].provider == "ollama":
            merged = []
            for m in messages:
                merged.append(f"{m.role.upper()}:\n{m.content}")
            formatted_messages = [{"role": "user", "content": f"{system_prompt}\n\n" + "\n\n".join(merged)}]
        else:
            formatted_messages = [{"role": "system", "content": system_prompt}]
            for m in messages:
                formatted_messages.append({"role": m.role, "content": m.content})

        logger.info(
            "chat_call_started",
            extra={"model": cfg.get("model"), "label": cfg.get("label"), "member_id": member_id},
        )

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
                    run_id,
                    0,
                    member_id,
                    full_text,
                    None,
                    None,
                    duration_ms,
                )
                metrics_store.finish_run(run_id, status="completed")
                return
            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    "chat_call_attempt_failed",
                    extra={
                        "model": cfg.get("model"),
                        "label": cfg.get("label"),
                        "member_id": member_id,
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
                    backoff = (2**attempt) + random.uniform(0, 1)
                    await asyncio.sleep(backoff)
