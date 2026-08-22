import asyncio
import re
import sys
from typing import Optional

from budget_profiles import token_budget_for
from io_parser import format_attachments_for_prompt, parse_input
from logging_utils import get_logger
from memory_store import memory_store as default_memory_engine
from metrics_store import metrics_store
from project_fingerprint import fingerprint
from run_store import run_store as default_run_store
from shutdown_state import is_shutdown_requested
from skill_registry import skill_registry as default_skill_registry
from summarizer import chunk_and_summarize as default_chunk_and_summarize

logger = get_logger(__name__)

MAX_COUNCIL_MEMBERS = 8


def _get_module_attr(attr_name: str, default):
    orch = sys.modules.get("orchestrator")
    return getattr(orch, attr_name, default)


def _specificity_score(chairman_result: dict, raw_text: str) -> float:
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


async def prepare_run(
    topic_text: str,
    attachments: Optional[list[dict]],
    custom_config: Optional[dict],
    deep_debate: bool,
    run_id: Optional[str],
    token_budget_profile: Optional[str],
    default_config: dict,
) -> tuple[dict, list[str], dict, str, str, str, bool, dict]:
    token_budget = token_budget_for(token_budget_profile)
    config = custom_config if custom_config else default_config
    council_members = [k for k in config.keys() if k != "chairman"]
    roster_capped = False
    if len(council_members) > MAX_COUNCIL_MEMBERS:
        logger.warning(
            "roster_capped",
            extra={"requested": len(council_members), "cap": MAX_COUNCIL_MEMBERS},
        )
        council_members = council_members[:MAX_COUNCIL_MEMBERS]
        roster_capped = True
    chairman_cfg = config.get("chairman", default_config["chairman"])

    run_id = run_id or metrics_store.start_run(
        "council",
        {
            "member_count": len(council_members),
            "deep_debate": deep_debate,
            "attachment_count": len(attachments or []),
        },
    )
    active_run_store = _get_module_attr("run_store", default_run_store)
    project_fp = await asyncio.to_thread(fingerprint, ".")
    await asyncio.to_thread(
        active_run_store.begin_run,
        run_id,
        topic_text,
        config,
        deep_debate,
        project_fp["hash"],
    )

    attachment_context = format_attachments_for_prompt(attachments or [])
    combined_topic = topic_text
    if attachment_context:
        combined_topic = (topic_text + "\n\n" + attachment_context).strip()

    active_parse_input = _get_module_attr("parse_input", parse_input)
    active_memory_engine = _get_module_attr("memory_engine", default_memory_engine)
    active_skill_registry = _get_module_attr("skill_registry", default_skill_registry)
    active_chunk_and_summarize = _get_module_attr("chunk_and_summarize", default_chunk_and_summarize)

    scraped_topic = await active_parse_input(combined_topic)
    past_context = await active_memory_engine.get_context(scraped_topic, chairman_cfg["model"])
    skills = await active_skill_registry.get_skills_for_topic(scraped_topic, top_k=3)
    skills_block = active_skill_registry.format_skills_block(skills)
    topic_context = await active_chunk_and_summarize(scraped_topic, chairman_cfg["model"])
    full_topic = f"{past_context}{skills_block}{topic_context}"

    return config, council_members, chairman_cfg, run_id, full_topic, combined_topic, roster_capped, token_budget


async def finalize_run(
    run_id: str,
    chairman_result: dict,
    chairman_decision_text: str,
    phase1_divergence: Optional[float],
    errored_members: set[str],
    combined_topic: str,
    chairman_cfg: dict,
) -> tuple[str, Optional[str]]:
    specificity_score = _specificity_score(chairman_result, chairman_decision_text)
    active_run_store = _get_module_attr("run_store", default_run_store)
    await asyncio.to_thread(
        active_run_store.record_phase_output,
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
        active_run_store.update_quality_metrics,
        run_id,
        chairman_result.get("_parse_tier"),
        phase1_divergence,
        specificity_score,
    )
    final_status = "partial" if errored_members else "completed"
    final_error = "Members failed: " + ", ".join(sorted(errored_members)) if errored_members else None
    metrics_store.finish_run(run_id, status=final_status, error=final_error)
    await asyncio.to_thread(active_run_store.finish_run, run_id, final_status, final_error)

    async def _background_post_run(r_id: str, t_topic: str, v_verdict: str, m_model: str):
        await asyncio.sleep(0.05)
        if is_shutdown_requested():
            return
        active_memory = _get_module_attr("memory_engine", default_memory_engine)
        active_skills = _get_module_attr("skill_registry", default_skill_registry)
        try:
            await active_memory.extract_memory(t_topic, v_verdict, m_model, run_id=r_id)
        except Exception as b_exc:
            logger.warning("background_memory_extraction_failed", extra={"run_id": r_id, "error": str(b_exc)})
        if is_shutdown_requested():
            return
        try:
            await active_skills.extract_skills(r_id, t_topic, m_model)
        except Exception as b_exc:
            logger.warning("background_skill_extraction_failed", extra={"run_id": r_id, "error": str(b_exc)})

    task = asyncio.create_task(
        _background_post_run(run_id, combined_topic, chairman_decision_text, chairman_cfg["model"])
    )
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return final_status, final_error
