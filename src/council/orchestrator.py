"""
CouncilOrchestrator — Universal 3-phase async pipeline

Phase 1 │ Independent Analysis  — Members analyze in parallel
Phase 2 │ Cross-Review          — Each member critiques all OTHER analyses
Phase 3 │ Chairman Decision     — Synthesizes everything → final call
"""

import asyncio
import contextlib
import os
import sys
from pathlib import Path
from typing import AsyncIterator, List, Optional

import runtime_defaults  # noqa: F401  # configure LiteLLM before import
import litellm
from budget_profiles import token_budget_for
from hardware_detect import get_default_council_config
from io_parser import parse_input  # re-exported for tests
from logging_utils import get_logger
from memory_store import memory_store as memory_engine  # re-exported for tests
from metrics_store import metrics_store
from run_store import run_store  # re-exported for tests
from search_engine import get_search_context  # re-exported for tests
from skill_registry import skill_registry  # re-exported for tests
import smart_phase  # re-exported for tests
from summarizer import chunk_and_summarize  # re-exported for tests

from llm_stream import (
    ANALYSIS_TEMPERATURE,
    CHAIRMAN_TEMPERATURE,
    LLM_TIMEOUT_S,
    MAX_TOOL_DEPTH,
    _build_messages,
    _classify_llm_error,
    _python_tool_enabled_for_model,
    _temperature_for,
    _top_p_for,
    _usage_to_dict,
    stream_chat_with_member,
    stream_llm_to_queue,
)
from orchestrator_token_utils import (
    TOKEN_SAFETY_MARGIN,
    _MODEL_TOKEN_MULTIPLIERS,
    _count_tokens,
    _is_openai_model,
    _render_fair_sections,
    _token_multiplier_for,
    _truncate_to_token_budget,
)
from phase_analysis import execute_phase1, member_analyze
from phase_chairman import (
    ChairmanDecision,
    _build_council_brief,
    _normalize_parsed_dict,
    _regex_extract_list,
    chairman_decide,
    execute_phase3,
    parse_chairman_response,
)
from phase_review import execute_phase2, member_review
from run_prep import (
    MAX_COUNCIL_MEMBERS,
    _specificity_score,
    finalize_run,
    prepare_run,
)

logger = get_logger(__name__)

MAX_PARALLEL_MEMBERS = max(1, int(os.getenv("COUNCIL_MAX_PARALLEL_MEMBERS", "2")))
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
        return _python_tool_enabled_for_model(model)

    def _build_messages(self, model: str, system_prompt: str, user_content) -> list[dict]:
        return _build_messages(model, system_prompt, user_content)

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
        return await stream_llm_to_queue(
            self, member_id, cfg, phase, messages, queue, max_tokens,
            response_format=response_format, run_id=run_id, emit_done=emit_done, tool_depth=tool_depth,
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
        await member_analyze(
            self, member_id, cfg, text, attachments, queue, run_id, self._token_budget, PHASE1_PROMPT
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
        await member_review(
            self, member_id, cfg, members_config, analyses, queue, run_id, self._token_budget, PHASE2_PROMPT
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
        await chairman_decide(
            self, chairman_cfg, members_config, analyses, reviews, queue, run_id, phase2_note, self._token_budget, PHASE3_PROMPT
        )

    async def run(
        self,
        topic_text: str,
        attachments: Optional[list[dict]] = None,
        custom_config: Optional[dict] = None,
        deep_debate: bool = False,
        run_id: Optional[str] = None,
        token_budget_profile: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        self._member_semaphore = asyncio.Semaphore(MAX_PARALLEL_MEMBERS)
        config, council_members, chairman_cfg, run_id, full_topic, combined_topic, roster_capped, self._token_budget = await prepare_run(
            topic_text, attachments, custom_config, deep_debate, run_id, token_budget_profile, DEFAULT_MEMBER_CONFIG
        )

        errored_members: set[str] = set()
        spawned_tasks: list[asyncio.Task] = []
        run_finalized = False

        try:
            if roster_capped:
                yield {"type": "warning", "message": f"Roster exceeded the {MAX_COUNCIL_MEMBERS}-member cap; using the first {MAX_COUNCIL_MEMBERS} members."}

            analyses = {}
            queue = asyncio.Queue()
            async for evt in execute_phase1(
                self, council_members, config, full_topic, attachments, run_id, queue, spawned_tasks, errored_members, self._token_budget, PHASE1_PROMPT
            ):
                if "_internal_analyses" in evt:
                    analyses = evt["_internal_analyses"]
                else:
                    yield evt

            reviews = {}
            phase1_divergence = None
            phase2_note = None
            async for evt in execute_phase2(
                self, council_members, config, analyses, deep_debate, run_id, queue, spawned_tasks, errored_members
            ):
                if "_internal_reviews" in evt:
                    reviews, phase1_divergence, phase2_note = evt["_internal_reviews"]
                else:
                    yield evt

            chairman_decision_text = ""
            queue = asyncio.Queue()
            async for evt in execute_phase3(
                self, chairman_cfg, config, analyses, reviews, phase2_note, run_id, queue, spawned_tasks, errored_members
            ):
                if "_internal_decision" in evt:
                    chairman_decision_text = evt["_internal_decision"]
                else:
                    yield evt

            chairman_result = parse_chairman_response(chairman_decision_text)
            final_status, _ = await finalize_run(
                run_id, chairman_result, chairman_decision_text, phase1_divergence, errored_members, combined_topic, chairman_cfg
            )
            run_finalized = True
            yield {"type": "done", "status": final_status, "errored_members": sorted(errored_members)}
        except Exception as exc:
            active_store = getattr(sys.modules.get("orchestrator"), "run_store", run_store)
            metrics_store.finish_run(run_id, status="failed", error=str(exc))
            await asyncio.to_thread(active_store.finish_run, run_id, "failed", str(exc))
            run_finalized = True
            raise
        finally:
            active_store = getattr(sys.modules.get("orchestrator"), "run_store", run_store)
            for t in spawned_tasks:
                if not t.done():
                    t.cancel()
            if not run_finalized:
                with contextlib.suppress(Exception):
                    metrics_store.finish_run(run_id, status="cancelled", error="Run interrupted before completion")
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(active_store.finish_run, run_id, "cancelled", "Run interrupted before completion")

    async def chat_with_member(
        self,
        member_id: str,
        messages: list,
        custom_config: Optional[dict] = None,
        run_id: Optional[str] = None,
        token_budget_profile: Optional[str] = None,
    ) -> AsyncIterator[str]:
        async for chunk in stream_chat_with_member(
            self, member_id, messages, custom_config=custom_config, run_id=run_id,
            token_budget_profile=token_budget_profile, default_config=DEFAULT_MEMBER_CONFIG
        ):
            yield chunk
