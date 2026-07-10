import asyncio
from pathlib import Path
from typing import Optional

from llm_council.chairman_result import ChairmanDecision
from llm_council.llm_streamer import count_tokens, truncate_to_token_budget
from llm_council.logging_utils import get_logger
from llm_council.provider_caps import caps_for, supports_image_input
from llm_council.search_engine import get_search_context


logger = get_logger(__name__)


def load_prompt(name: str) -> str:
    path = Path(__file__).resolve().parent / "resources" / "agent_prompts" / "phase_prompts" / name
    return path.read_text(encoding="utf-8")


PHASE1_PROMPT = load_prompt("phase1_analyze.txt")
PHASE2_PROMPT = load_prompt("phase2_review.txt")
PHASE2_REBUTTAL_PROMPT = load_prompt("phase2_rebuttal.txt")
PHASE3_PROMPT = load_prompt("phase3_chairman.txt")


class SeatExecutor:
    def __init__(self, build_messages, search_context=get_search_context):
        self.build_messages = build_messages
        self.get_search_context = search_context

    async def analyze(
        self,
        member_id: str,
        cfg: dict,
        text: str,
        attachments: Optional[list[dict]],
        queue: asyncio.Queue,
        token_budget: dict,
        stream_llm,
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
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{attachment.get('content_type', 'image/png')};base64,{attachment['data']}"
                        },
                    }
                )
        if text:
            content.append({"type": "text", "text": f"Topic / Context:\n{text}"})
        if not content:
            content.append({"type": "text", "text": "No context provided - analyze the request based on your persona."})

        messages = self.build_messages(cfg.get("model", ""), system_prompt, content)
        await stream_llm(
            member_id,
            cfg,
            1,
            messages,
            queue,
            token_budget["phase1"],
            run_id=run_id,
        )

    async def review(
        self,
        member_id: str,
        cfg: dict,
        members_config: dict,
        analyses: dict[str, str],
        queue: asyncio.Queue,
        token_budget: dict,
        stream_llm,
        run_id: Optional[str] = None,
    ):
        system_prompt = PHASE2_PROMPT.format(persona=cfg.get("persona", ""))

        prompt_parts = ["You are reviewing analyses from your peers:\n"]
        model_id = cfg.get("model", "")
        context_window = caps_for(model_id)[0].context_window or 4096
        max_total_input_tokens = context_window - token_budget["phase2"] - 800
        max_total_input_tokens = max(125, max_total_input_tokens)
        peers = [(peer_id, analysis) for peer_id, analysis in analyses.items() if peer_id != member_id]

        for peer_id, analysis in peers:
            peer_label = members_config[peer_id].get("label", peer_id)
            prompt_parts.append(f"--- {peer_label} ---\n{analysis}\n")

        prompt = "\n".join(prompt_parts)
        original_tokens = count_tokens(model_id, prompt)
        if original_tokens > max_total_input_tokens:
            original_len = len(prompt)
            prompt = truncate_to_token_budget(model_id, prompt, max_total_input_tokens)
            logger.info(
                "phase2_input_truncated",
                extra={"model": cfg.get("model", ""), "original_chars": original_len, "truncated_chars": len(prompt)},
            )
        messages = self.build_messages(cfg.get("model", ""), system_prompt, prompt)
        await stream_llm(
            member_id,
            cfg,
            2,
            messages,
            queue,
            token_budget["phase2"],
            run_id=run_id,
        )

    async def rebuttal(
        self,
        member_id: str,
        cfg: dict,
        members_config: dict,
        own_analysis: str,
        reviews: dict[str, str],
        queue: asyncio.Queue,
        token_budget: dict,
        stream_llm,
    ):
        system_prompt = PHASE2_REBUTTAL_PROMPT.format(persona=cfg.get("persona", ""))

        prompt_parts = [f"YOUR ORIGINAL ANALYSIS:\n{own_analysis}\n", "\nPEER CRITIQUES:\n"]
        for reviewer_id, review in reviews.items():
            if reviewer_id == member_id:
                continue
            reviewer_label = members_config.get(reviewer_id, {}).get("label", reviewer_id)
            prompt_parts.append(f"--- {reviewer_label} ---\n{review}\n")

        prompt = "\n".join(prompt_parts)
        model_id = cfg.get("model", "")
        context_window = caps_for(model_id)[0].context_window or 4096
        max_tokens = min(token_budget["phase2"], 300)
        max_input_tokens = max(125, context_window - max_tokens - 800)
        if count_tokens(model_id, prompt) > max_input_tokens:
            prompt = truncate_to_token_budget(model_id, prompt, max_input_tokens)

        await queue.put({"type": "member_token", "member": member_id, "chunk": "\n\n---\n**REBUTTAL** - "})
        messages = self.build_messages(model_id, system_prompt, prompt)
        await stream_llm(
            member_id,
            cfg,
            2,
            messages,
            queue,
            max_tokens,
        )

    async def chairman_decide(
        self,
        chairman_cfg: dict,
        members_config: dict,
        analyses: dict[str, str],
        reviews: dict[str, str],
        queue: asyncio.Queue,
        token_budget: dict,
        stream_llm,
        run_id: Optional[str] = None,
    ):
        search_results = await self.get_search_context(reviews, chairman_cfg["model"])

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

        chairman_model = chairman_cfg.get("model", "")
        context_window = caps_for(chairman_model)[0].context_window or 4096
        max_input_tokens = context_window - token_budget["phase3"] - 500
        max_input_tokens = max(1, max_input_tokens)
        original_len = len(council_brief)
        original_tokens = count_tokens(chairman_model, council_brief)
        if original_tokens > max_input_tokens:
            rebuilt_parts = []
            used_tokens = 0
            truncated = False

            def add_section(section: str) -> bool:
                nonlocal used_tokens, truncated
                section_tokens = count_tokens(chairman_model, section)
                if used_tokens + section_tokens > max_input_tokens:
                    truncated = True
                    return False
                rebuilt_parts.append(section)
                used_tokens += section_tokens
                return True

            if search_results:
                add_section(search_results + "\n\n")

            if not truncated:
                for member, analysis in analyses.items():
                    cfg = members_config.get(member, {})
                    section = f"=== {cfg.get('label', member)} ANALYSIS ===\n{analysis}\n\n"
                    if not add_section(section):
                        break

            if not truncated:
                review_header = "\n--- PEER REVIEWS ---\n\n"
                for reviewer, review in reviews.items():
                    cfg = members_config.get(reviewer, {})
                    prefix = review_header if reviewer == next(iter(reviews), None) else ""
                    section = f"{prefix}=== {cfg.get('label', reviewer)} REVIEW ===\n{review}\n\n"
                    if not add_section(section):
                        break

            council_brief = "".join(rebuilt_parts)
            marker = "\n[truncated]"
            marker_tokens = count_tokens(chairman_model, marker)
            if truncated and used_tokens + marker_tokens <= max_input_tokens:
                council_brief += marker

            if count_tokens(chairman_model, council_brief) > max_input_tokens:
                council_brief = truncate_to_token_budget(chairman_model, council_brief, max_input_tokens)

            logger.info(
                "phase3_input_truncated",
                extra={"model": chairman_cfg.get("model"), "original_chars": original_len, "truncated_chars": len(council_brief)},
            )

        messages = self.build_messages(
            chairman_cfg.get("model", ""),
            PHASE3_PROMPT,
            council_brief,
        )

        await stream_llm(
            "chairman",
            chairman_cfg,
            3,
            messages,
            queue,
            token_budget["phase3"],
            response_format=ChairmanDecision if caps_for(chairman_cfg.get("model", ""))[1].response_format else None,
            run_id=run_id,
        )
