import asyncio
from typing import AsyncIterator, Optional
from provider_caps import supports_image_input


async def member_analyze(
    orchestrator,
    member_id: str,
    cfg: dict,
    text: str,
    attachments: Optional[list[dict]],
    queue: asyncio.Queue,
    run_id: Optional[str],
    token_budget: dict,
    phase1_prompt: str,
):
    system_prompt = phase1_prompt.format(persona=cfg.get("persona", ""))

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

    messages = orchestrator._build_messages(cfg.get("model", ""), system_prompt, content)
    async with orchestrator._member_slot():
        await orchestrator._stream_llm_to_queue(
            member_id,
            cfg,
            1,
            messages,
            queue,
            token_budget["phase1"],
            run_id=run_id,
        )


async def execute_phase1(
    orchestrator,
    council_members: list[str],
    config: dict,
    full_topic: str,
    attachments: Optional[list[dict]],
    run_id: Optional[str],
    queue: asyncio.Queue,
    spawned_tasks: list[asyncio.Task],
    errored_members: set[str],
    token_budget: dict,
    phase1_prompt: str,
) -> AsyncIterator[dict]:
    yield {"type": "phase_start", "phase": 1, "label": "Independent Analysis"}
    for member in council_members:
        yield {"type": "member_thinking", "member": member, "meta": config[member]}

    for member in council_members:
        spawned_tasks.append(asyncio.create_task(
            orchestrator._member_analyze(member, config[member], full_topic, attachments, queue, run_id=run_id)
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

    yield {"_internal_analyses": analyses}
