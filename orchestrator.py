"""
CouncilOrchestrator — Universal 3-phase async pipeline

Phase 1 │ Independent Analysis  — Members analyze in parallel
Phase 2 │ Cross-Review          — Each member critiques all OTHER analyses
Phase 3 │ Chairman Decision     — Synthesizes everything → final call
"""

import asyncio
from typing import AsyncIterator, Optional
import litellm
from memory_graph import memory_engine
from io_parser import parse_input
from search_engine import get_search_context
from smart_phase import check_unanimous_consensus
from mcp_client import query_mcp_server

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

DEFAULT_MEMBER_CONFIG = {
    "deepseek": {
        "label": "DeepSeek (Architecture)",
        "model": "openrouter/deepseek/deepseek-r1",
        "color": "#4D6BFE",
        "icon": "🐋",
        "persona": "You are the ruthless Principal Security & Architecture Engineer. Focus on scaling bottlenecks, security flaws, and systems architecture.",
    },
    "qwq": {
        "label": "QwQ (Logic)",
        "model": "openrouter/qwen/qwq-32b-preview",
        "color": "#A020F0",
        "icon": "🧠",
        "persona": "You are the Senior Data & Logic Scientist. Focus on edge cases, algorithm efficiency, and data flow correctness.",
    },
    "llama": {
        "label": "Llama 3 (Product)",
        "model": "openrouter/meta-llama/llama-3.3-70b-instruct",
        "color": "#043B72",
        "icon": "🦙",
        "persona": "You are the Product Manager. Focus on user impact, scoping, feature bloat, and whether these features actually matter to the business.",
    },
    "gemini": {
        "label": "Gemini Flash (Frontend)",
        "model": "gemini/gemini-2.0-flash",
        "color": "#7EC8A4",
        "icon": "✦",
        "persona": "You are the Lead Frontend & UX Engineer. Focus on UI performance, user experience, accessibility, and client-side state management.",
    },
    "gemma": {
        "label": "Gemma (QA)",
        "model": "openrouter/google/gemma-2-27b-it",
        "color": "#F4B400",
        "icon": "✨",
        "persona": "You are the QA Lead. Focus on missing test plans, deployment risks, regression testing, and CI/CD pipelines.",
    },
    "chairman": {
        "label": "Chairman (Llama 3 70B)",
        "model": "openrouter/meta-llama/llama-3.3-70b-instruct",
        "color": "#F5C842",
        "icon": "👑",
        "persona": "You are the Chairman.",
    },
}

class CouncilOrchestrator:
    def __init__(self, **kwargs):
        pass

    async def _stream_llm_to_queue(self, member_id: str, cfg: dict, phase: int, messages: list, queue: asyncio.Queue, max_tokens: int) -> str:
        print(f"\n[🚀 API REQUEST Phase {phase}] -> Routing to {cfg['model']} ({cfg['label']})")
        
        full_text = ""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                resp = await litellm.acompletion(
                    model=cfg["model"],
                    messages=messages,
                    max_tokens=max_tokens,
                    stream=True
                )
                async for chunk in resp:
                    text_chunk = chunk.choices[0].delta.content or ""
                    if text_chunk:
                        full_text += text_chunk
                        await queue.put({"type": "member_token", "member": member_id, "chunk": text_chunk})
                
                print(f"[✅ API RESPONSE Phase {phase}] <- {cfg['label']} completed!")
                break
            except Exception as e:
                error_msg = str(e)
                print(f"[⚠️ API WARNING Phase {phase}] <- {cfg['label']} attempt {attempt+1} failed: {error_msg}")
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

    async def _member_analyze(self, member_id: str, cfg: dict, text: str, image_b64: Optional[str], mime: Optional[str], queue: asyncio.Queue):
        system_prompt = SYSTEM_COUNCIL_BASE.format(persona=cfg.get("persona", ""))

        content = []
        if image_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_b64}"},
            })
        if text:
            content.append({"type": "text", "text": f"Topic / Context:\n{text}"})
        if not content:
            content.append({"type": "text", "text": "No context provided — analyze the request based on your persona."})

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]
        await self._stream_llm_to_queue(member_id, 1, messages, queue, 600)

    async def _member_review(self, member_id: str, cfg: dict, members_config: dict, analyses: dict[str, str], queue: asyncio.Queue):
        system_prompt = SYSTEM_REVIEWER_BASE.format(persona=cfg.get("persona", ""))

        prompt_parts = ["You are reviewing analyses from your peers:\n"]
        for peer_id, analysis in analyses.items():
            if peer_id == member_id:
                continue
            peer_label = members_config[peer_id].get("label", peer_id)
            prompt_parts.append(f"--- {peer_label} ---\n{analysis}\n")
        
        prompt = "\n".join(prompt_parts)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        await self._stream_llm_to_queue(member_id, 2, messages, queue, 400)

    async def _chairman_decide(self, chairman_cfg: dict, members_config: dict, analyses: dict[str, str], reviews: dict[str, str], queue: asyncio.Queue):
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

        messages = [
            {"role": "system", "content": SYSTEM_CHAIRMAN},
            {"role": "user", "content": council_brief},
        ]
        await self._stream_llm_to_queue("chairman", chairman_cfg, 3, messages, queue, 1200)

    async def run(self, topic_text: str, image_b64: Optional[str], image_mime: Optional[str], custom_config: Optional[dict] = None) -> AsyncIterator[dict]:
        config = custom_config if custom_config else DEFAULT_MEMBER_CONFIG
        council_members = [k for k in config.keys() if k != "chairman"]
        chairman_cfg = config.get("chairman", DEFAULT_MEMBER_CONFIG["chairman"])

        # Zero-Cost Scraper I/O
        scraped_topic = await parse_input(topic_text)

        # Retrieve past context from Graph Memory
        past_context = await memory_engine.get_context(scraped_topic, chairman_cfg["model"])
        
        # Pull MCP Context if needed
        mcp_context = await query_mcp_server(scraped_topic)

        full_topic = mcp_context + past_context + scraped_topic

        # ── Phase 1 ──────────────────────────────────────────────────
        yield {"type": "phase_start", "phase": 1, "label": "Independent Analysis"}
        for member in council_members:
            yield {"type": "member_thinking", "member": member, "meta": config[member]}

        queue = asyncio.Queue()
        tasks = [asyncio.create_task(self._member_analyze(member, config[member], full_topic, image_b64, image_mime, queue)) for member in council_members]
        
        analyses = {}
        completed = 0
        while completed < len(council_members):
            event = await queue.get()
            if event["type"] == "member_done":
                completed += 1
                analyses[event["member"]] = event["full_text"]
            else:
                yield event

        # Smart Phase 2 (Similarity Check)
        is_unanimous = await check_unanimous_consensus(analyses)
        reviews = {}

        if is_unanimous:
            yield {"type": "phase_start", "phase": 2, "label": "Cross-Review (SKIPPED - Unanimous Consensus!)"}
            for member in council_members:
                reviews[member] = "SKIPPED - The council was in unanimous agreement during Phase 1. No factual disputes detected."
                yield {"type": "member_done", "member": member, "full_text": reviews[member]}
            await asyncio.sleep(1) # Brief pause for UI fluidity
        else:
            # ── Phase 2 ──────────────────────────────────────────────────
            yield {"type": "phase_start", "phase": 2, "label": "Cross-Review"}
            for member in council_members:
                yield {"type": "member_thinking", "member": member, "phase": 2, "meta": config[member]}

            queue = asyncio.Queue()
            tasks = [asyncio.create_task(self._member_review(member, config[member], config, analyses, queue)) for member in council_members]
            
            completed = 0
            while completed < len(council_members):
                event = await queue.get()
                if event["type"] == "member_done":
                    completed += 1
                    reviews[event["member"]] = event["full_text"]
                else:
                    yield event

        # ── Phase 3 ──────────────────────────────────────────────────
        chairman_cfg = config.get("chairman", DEFAULT_MEMBER_CONFIG["chairman"])
        yield {"type": "phase_start", "phase": 3, "label": "Chairman's Verdict"}
        yield {"type": "member_thinking", "member": "chairman", "phase": 3, "meta": chairman_cfg}

        queue = asyncio.Queue()
        asyncio.create_task(self._chairman_decide(chairman_cfg, config, analyses, reviews, queue))
        
        completed = 0
        chairman_decision_text = ""
        while completed < 1:
            event = await queue.get()
            if event["type"] == "member_done":
                completed += 1
                chairman_decision_text = event["full_text"]
            else:
                yield event

        # Trigger background memory extraction
        asyncio.create_task(memory_engine.extract_memory(topic_text, chairman_decision_text, chairman_cfg["model"]))

        yield {"type": "done"}

    async def chat_with_member(self, member_id: str, messages: list, custom_config: Optional[dict] = None) -> AsyncIterator[str]:
        config = custom_config if custom_config else DEFAULT_MEMBER_CONFIG
        cfg = config.get(member_id, DEFAULT_MEMBER_CONFIG.get(member_id, DEFAULT_MEMBER_CONFIG["chairman"]))
        
        system_prompt = f"You are a council member engaged in a direct chat. Stay completely in character. YOUR PERSONA: {cfg.get('persona', '')}"
        
        formatted_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            formatted_messages.append({"role": m.role, "content": m.content})
            
        print(f"\n[💬 CHAT REQUEST] -> Routing to {cfg['model']} ({cfg['label']})")
        
        try:
            resp = await litellm.acompletion(
                model=cfg["model"],
                messages=formatted_messages,
                max_tokens=600,
                stream=True
            )
            async for chunk in resp:
                text_chunk = chunk.choices[0].delta.content or ""
                if text_chunk:
                    yield text_chunk
        except Exception as e:
            print(f"[❌ CHAT ERROR] <- {cfg['label']}: {str(e)}")
            yield f"\n[Error connecting to {cfg['label']}: {str(e)}]"
