import asyncio
import json
import re
import sys
from typing import AsyncIterator, List, Optional
from pydantic import BaseModel

from logging_utils import get_logger
from orchestrator_token_utils import _count_tokens, _render_fair_sections, _truncate_to_token_budget
from provider_caps import caps_for
from search_engine import get_search_context as default_get_search_context

logger = get_logger(__name__)


def _get_module_attr(attr_name: str, default):
    orch = sys.modules.get("orchestrator")
    return getattr(orch, attr_name, default)


class ChairmanDecision(BaseModel):
    verdict: str
    risk_score: int
    confidence: int = 5
    action_items: List[str]
    consensus: List[str] = []
    disputes: List[str] = []


def _regex_extract_list(key: str, raw: str) -> list[str]:
    pattern = r'(?:["\']?' + re.escape(key) + r'["\']?)\s*:\s*\[([^\]]*)\]'
    match = re.search(pattern, raw, re.IGNORECASE)
    if not match:
        return []
    items_content = match.group(1)
    items = re.findall(r'["\']([^"\']*)["\']', items_content)
    return [item.strip() for item in items if item.strip()]


def _normalize_parsed_dict(result: dict, tier: str) -> dict:
    consensus = result.get("consensus")
    if isinstance(consensus, str):
        consensus = [consensus] if consensus else []
    elif not isinstance(consensus, list):
        consensus = []
    return {
        "verdict": result.get("verdict", "parse_failed"),
        "risk_score": result.get("risk_score", -1),
        "confidence": result.get("confidence", -1),
        "action_items": result.get("action_items", []),
        "consensus": consensus,
        "disputes": result.get("disputes", []),
        "_parse_tier": result.get("_parse_tier", tier),
    }


def parse_chairman_response(raw: str) -> dict:
    try:
        return _normalize_parsed_dict(json.loads(raw), "json")
    except Exception:
        pass

    try:
        stripped = re.sub(r"^```(?:json)?\n?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        return _normalize_parsed_dict(json.loads(stripped), "fenced_json")
    except Exception:
        pass

    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            candidate = raw[start:end + 1]
            candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
            return _normalize_parsed_dict(json.loads(candidate), "json_repaired")
    except Exception:
        pass

    verdict_match = re.search(r'(?:["\']?verdict["\']?)\s*:\s*["\']([^"\']+)["\']', raw, re.IGNORECASE)
    risk_match = re.search(r'(?:["\']?risk_score["\']?)\s*:\s*(\d+(?:\.\d+)?)', raw, re.IGNORECASE)
    confidence_match = re.search(r'(?:["\']?confidence["\']?)\s*:\s*(\d+(?:\.\d+)?)', raw, re.IGNORECASE)
    if verdict_match or risk_match:
        return {
            "verdict": verdict_match.group(1) if verdict_match else "parse_failed",
            "risk_score": float(risk_match.group(1)) if risk_match else -1,
            "confidence": int(float(confidence_match.group(1))) if confidence_match else -1,
            "action_items": _regex_extract_list("action_items", raw),
            "consensus": _regex_extract_list("consensus", raw),
            "disputes": _regex_extract_list("disputes", raw),
            "_parse_tier": "regex_extracted",
        }

    return {
        "verdict": "parse_failed",
        "risk_score": -1,
        "confidence": -1,
        "action_items": [],
        "consensus": [],
        "disputes": [],
        "_parse_tier": "parse_failed",
    }


def _build_council_brief(
    chairman_model: str,
    members_config: dict,
    analyses: dict[str, str],
    reviews: dict[str, str],
    phase2_note: Optional[str],
    max_input_tokens: int,
    search_results: str,
) -> str:
    phase2_skipped = phase2_note is not None
    header = (search_results + "\n\n") if search_results else ""
    analysis_items = [(members_config.get(m, {}).get("label", m), text) for m, text in analyses.items()]
    budget_after_header = max(1, max_input_tokens - _count_tokens(chairman_model, header))

    if phase2_skipped:
        peer_block = (
            "\n--- PEER REVIEWS ---\n"
            f"[Phase 2 cross-review was SKIPPED: {phase2_note}. No peer critiques "
            "were produced — derive consensus and disputes yourself from the "
            "Phase 1 analyses below.]\n\n"
        )
        analyses_budget = max(1, budget_after_header - _count_tokens(chairman_model, peer_block))
        analyses_block = _render_fair_sections(
            chairman_model, analysis_items, analyses_budget, "=== {label} ANALYSIS ===\n"
        )
    else:
        review_items = [(members_config.get(r, {}).get("label", r), text) for r, text in reviews.items()]
        analyses_budget = max(1, int(budget_after_header * 0.6))
        reviews_budget = max(1, budget_after_header - analyses_budget)
        analyses_block = _render_fair_sections(
            chairman_model, analysis_items, analyses_budget, "=== {label} ANALYSIS ===\n"
        )
        peer_block = "\n--- PEER REVIEWS ---\n\n" + _render_fair_sections(
            chairman_model, review_items, reviews_budget, "=== {label} REVIEW ===\n"
        )

    council_brief = header + analyses_block + peer_block
    if _count_tokens(chairman_model, council_brief) > max_input_tokens:
        council_brief = _truncate_to_token_budget(chairman_model, council_brief, max_input_tokens)
        logger.info(
            "phase3_input_truncated",
            extra={"model": chairman_model, "truncated_chars": len(council_brief)},
        )
    return council_brief


async def chairman_decide(
    orchestrator,
    chairman_cfg: dict,
    members_config: dict,
    analyses: dict[str, str],
    reviews: dict[str, str],
    queue: asyncio.Queue,
    run_id: Optional[str],
    phase2_note: Optional[str],
    token_budget: dict,
    phase3_prompt: str,
):
    phase2_skipped = phase2_note is not None
    chairman_model = chairman_cfg.get("model", "")
    active_search = _get_module_attr("get_search_context", default_get_search_context)
    search_results = await active_search(
        analyses if phase2_skipped else reviews, chairman_cfg["model"]
    )
    context_window = caps_for(chairman_model)[0].context_window or 4096
    max_input_tokens = max(1, context_window - token_budget["phase3"] - 500)
    council_brief = _build_council_brief(
        chairman_model, members_config, analyses, reviews, phase2_note, max_input_tokens, search_results
    )
    messages = orchestrator._build_messages(
        chairman_cfg.get("model", ""),
        phase3_prompt,
        council_brief,
    )
    await orchestrator._stream_llm_to_queue(
        "chairman",
        chairman_cfg,
        3,
        messages,
        queue,
        token_budget["phase3"],
        response_format=ChairmanDecision if caps_for(chairman_cfg.get("model", ""))[1].response_format else None,
        run_id=run_id,
    )


async def execute_phase3(
    orchestrator,
    chairman_cfg: dict,
    config: dict,
    analyses: dict[str, str],
    reviews: dict[str, str],
    phase2_note: Optional[str],
    run_id: Optional[str],
    queue: asyncio.Queue,
    spawned_tasks: list[asyncio.Task],
    errored_members: set[str],
) -> AsyncIterator[dict]:
    yield {"type": "phase_start", "phase": 3, "label": "Chairman's Verdict"}
    yield {"type": "member_thinking", "member": "chairman", "phase": 3, "meta": chairman_cfg}

    spawned_tasks.append(asyncio.create_task(
        orchestrator._chairman_decide(chairman_cfg, config, analyses, reviews, queue, run_id=run_id, phase2_note=phase2_note)
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

    yield {"_internal_decision": chairman_decision_text}
