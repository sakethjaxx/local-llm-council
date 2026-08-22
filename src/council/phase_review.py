import asyncio
import sys
from typing import AsyncIterator, Optional

from orchestrator_token_utils import _count_tokens, _render_fair_sections
from provider_caps import caps_for
from run_store import run_store as default_run_store
import smart_phase as default_smart_phase


def _get_module_attr(attr_name: str, default):
    orch = sys.modules.get("orchestrator")
    return getattr(orch, attr_name, default)


async def member_review(
    orchestrator,
    member_id: str,
    cfg: dict,
    members_config: dict,
    analyses: dict[str, str],
    queue: asyncio.Queue,
    run_id: Optional[str],
    token_budget: dict,
    phase2_prompt: str,
):
    system_prompt = phase2_prompt.format(persona=cfg.get("persona", ""))

    model_id = cfg.get("model", "")
    context_window = caps_for(model_id)[0].context_window or 4096
    header = "You are reviewing analyses from your peers:\n\n"
    max_total_input_tokens = max(125, context_window - token_budget["phase2"] - 800)
    peers_budget = max(1, max_total_input_tokens - _count_tokens(model_id, header))
    peer_items = [
        (members_config[peer_id].get("label", peer_id), analysis)
        for peer_id, analysis in analyses.items()
        if peer_id != member_id
    ]
    prompt = header + _render_fair_sections(model_id, peer_items, peers_budget, "--- {label} ---\n")
    messages = orchestrator._build_messages(cfg.get("model", ""), system_prompt, prompt)
    async with orchestrator._member_slot():
        await orchestrator._stream_llm_to_queue(
            member_id,
            cfg,
            2,
            messages,
            queue,
            token_budget["phase2"],
            run_id=run_id,
        )


async def _execute_fast_mode_bypass(council_members: list[str], run_id: Optional[str]) -> AsyncIterator[dict]:
    yield {"type": "phase_start", "phase": 2, "label": "Cross-Review (Bypassed - Fast Mode)"}
    reviews = {}
    active_run_store = _get_module_attr("run_store", default_run_store)
    for member in council_members:
        reviews[member] = "SKIPPED - Fast Code Review mode enabled. Bypassing debate for latency."
        await asyncio.to_thread(active_run_store.record_phase_output, run_id, 2, member, reviews[member])
        yield {"type": "member_done", "member": member, "full_text": reviews[member]}
    await asyncio.sleep(0.5)
    yield {"_internal_reviews": (reviews, None, "Fast mode was enabled (cross-review bypassed for latency)")}


async def _execute_unanimous_skip(council_members: list[str], run_id: Optional[str], smart_score: float, phase1_divergence: float) -> AsyncIterator[dict]:
    active_smart_phase = _get_module_attr("smart_phase", default_smart_phase)
    active_run_store = _get_module_attr("run_store", default_run_store)
    phase2_note = f"high inter-analysis agreement (min pairwise similarity {round(smart_score, 3)} > threshold {active_smart_phase.SKIP_THRESHOLD})"
    yield {"type": "phase_start", "phase": 2, "label": "Cross-Review (SKIPPED - Unanimous Consensus!)"}
    reviews = {}
    for member in council_members:
        reviews[member] = "SKIPPED - The council was in unanimous agreement during Phase 1. No factual disputes detected."
        await asyncio.to_thread(active_run_store.record_phase_output, run_id, 2, member, reviews[member])
        yield {"type": "member_done", "member": member, "full_text": reviews[member]}
    await asyncio.sleep(1)
    yield {"_internal_reviews": (reviews, phase1_divergence, phase2_note)}


async def _execute_peer_reviews(
    orchestrator,
    council_members: list[str],
    config: dict,
    analyses: dict[str, str],
    run_id: Optional[str],
    queue: asyncio.Queue,
    spawned_tasks: list[asyncio.Task],
    errored_members: set[str],
    phase1_divergence: float,
) -> AsyncIterator[dict]:
    yield {"type": "phase_start", "phase": 2, "label": "Cross-Review"}
    for member in council_members:
        yield {"type": "member_thinking", "member": member, "phase": 2, "meta": config[member]}

    for member in council_members:
        spawned_tasks.append(asyncio.create_task(
            orchestrator._member_review(member, config[member], config, analyses, queue, run_id=run_id)
        ))

    reviews = {}
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

    yield {"_internal_reviews": (reviews, phase1_divergence, None)}


async def execute_phase2(
    orchestrator,
    council_members: list[str],
    config: dict,
    analyses: dict[str, str],
    deep_debate: bool,
    run_id: Optional[str],
    queue: asyncio.Queue,
    spawned_tasks: list[asyncio.Task],
    errored_members: set[str],
) -> AsyncIterator[dict]:
    if not deep_debate:
        async for evt in _execute_fast_mode_bypass(council_members, run_id):
            yield evt
        return

    active_smart_phase = _get_module_attr("smart_phase", default_smart_phase)
    active_run_store = _get_module_attr("run_store", default_run_store)
    is_unanimous, smart_score = await active_smart_phase.should_skip(analyses)
    phase1_divergence = round(max(0.0, min(1.0, 1.0 - smart_score)), 4)
    await asyncio.to_thread(active_run_store.update_smart_phase_score, run_id, smart_score)

    if is_unanimous:
        async for evt in _execute_unanimous_skip(council_members, run_id, smart_score, phase1_divergence):
            yield evt
    else:
        async for evt in _execute_peer_reviews(
            orchestrator, council_members, config, analyses, run_id, queue, spawned_tasks, errored_members, phase1_divergence
        ):
            yield evt
