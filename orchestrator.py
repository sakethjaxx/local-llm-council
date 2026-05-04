"""
CouncilOrchestrator — 3-phase async pipeline

Phase 1 │ Independent Analysis  — Claude, GPT-4o, Gemini analyze in parallel
Phase 2 │ Cross-Review          — Each model critiques the OTHER TWO analyses
Phase 3 │ Chairman Decision     — GPT-4o-mini synthesizes everything → final call
"""

import asyncio
from typing import AsyncIterator, Optional
import anthropic
import openai
import google.generativeai as genai


SYSTEM_COUNCIL = """You are a senior technical council member reviewing a software sprint plan.
Be direct, opinionated, and constructive. Structure your analysis as:
1. STRENGTHS — what looks solid
2. RISKS — blockers, unknowns, or architectural concerns
3. RECOMMENDATIONS — concrete actions or changes
Keep it under 300 words. Be specific, not generic."""

SYSTEM_REVIEWER = """You are a critical peer reviewer on a technical council.
You've been given analyses from two other AI models reviewing the same sprint plan.
Your job: identify where they agree, where they diverge, and what they MISSED.
Be blunt. Under 200 words."""

SYSTEM_CHAIRMAN = """You are the Chairman of a technical AI council.
You've received independent analyses and peer reviews from three council members
(Claude, GPT-4o, Gemini) on a sprint plan.
Your job: synthesize ALL inputs and deliver a FINAL DECISION with:
- CONSENSUS POINTS (where all members agree)
- KEY DISPUTES (real disagreements worth noting)
- CHAIRMAN'S VERDICT (your authoritative recommendation — be decisive)
- TOP 3 ACTION ITEMS (numbered, specific, assigned if possible)
Be the tie-breaker. Under 400 words."""


MEMBER_CONFIG = {
    "claude": {
        "label": "Claude Sonnet",
        "model": "claude-sonnet-4-20250514",
        "color": "#E8845A",
        "icon": "⚡",
    },
    "gpt4o": {
        "label": "GPT-4o",
        "model": "gpt-4o",
        "color": "#74B3CE",
        "icon": "🔮",
    },
    "gemini": {
        "label": "Gemini Flash",
        "model": "gemini-2.0-flash",
        "color": "#7EC8A4",
        "icon": "✦",
    },
    "chairman": {
        "label": "Chairman (GPT-4o-mini)",
        "model": "gpt-4o-mini",
        "color": "#F5C842",
        "icon": "👑",
    },
}


class CouncilOrchestrator:
    def __init__(self, anthropic_key: str, openai_key: str, gemini_key: str):
        self.claude = anthropic.AsyncAnthropic(api_key=anthropic_key)
        self.openai = openai.AsyncOpenAI(api_key=openai_key)
        genai.configure(api_key=gemini_key)
        self.gemini_model = genai.GenerativeModel(MEMBER_CONFIG["gemini"]["model"])

    # ─────────────────────── Phase 1: Analysis ───────────────────────

    async def _claude_analyze(self, text: str, image_b64: Optional[str], mime: Optional[str]) -> str:
        content = []
        if image_b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": image_b64},
            })
        if text:
            content.append({"type": "text", "text": f"Sprint Overview:\n{text}"})
        if not content:
            content.append({"type": "text", "text": "No sprint data provided — analyze what a typical sprint should cover."})

        msg = await self.claude.messages.create(
            model=MEMBER_CONFIG["claude"]["model"],
            max_tokens=600,
            system=SYSTEM_COUNCIL,
            messages=[{"role": "user", "content": content}],
        )
        return msg.content[0].text

    async def _gpt4o_analyze(self, text: str, image_b64: Optional[str], mime: Optional[str]) -> str:
        content = []
        if image_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_b64}"},
            })
        if text:
            content.append({"type": "text", "text": f"Sprint Overview:\n{text}"})
        if not content:
            content.append({"type": "text", "text": "No sprint data provided."})

        resp = await self.openai.chat.completions.create(
            model=MEMBER_CONFIG["gpt4o"]["model"],
            max_tokens=600,
            messages=[
                {"role": "system", "content": SYSTEM_COUNCIL},
                {"role": "user", "content": content},
            ],
        )
        return resp.choices[0].message.content

    async def _gemini_analyze(self, text: str, image_b64: Optional[str], mime: Optional[str]) -> str:
        parts = []
        if image_b64:
            import base64 as b64mod
            from PIL import Image
            import io
            raw = b64mod.b64decode(image_b64)
            img = Image.open(io.BytesIO(raw))
            parts.append(img)
        prompt = f"{SYSTEM_COUNCIL}\n\nSprint Overview:\n{text or 'No sprint text provided.'}"
        parts.append(prompt)

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: self.gemini_model.generate_content(parts)
        )
        return resp.text

    # ─────────────────────── Phase 2: Cross-Review ───────────────────────

    async def _claude_review(self, peer_a_label: str, peer_a: str, peer_b_label: str, peer_b: str) -> str:
        prompt = (
            f"You are reviewing analyses from two peers:\n\n"
            f"--- {peer_a_label} ---\n{peer_a}\n\n"
            f"--- {peer_b_label} ---\n{peer_b}"
        )
        msg = await self.claude.messages.create(
            model=MEMBER_CONFIG["claude"]["model"],
            max_tokens=400,
            system=SYSTEM_REVIEWER,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    async def _gpt4o_review(self, peer_a_label: str, peer_a: str, peer_b_label: str, peer_b: str) -> str:
        prompt = (
            f"You are reviewing analyses from two peers:\n\n"
            f"--- {peer_a_label} ---\n{peer_a}\n\n"
            f"--- {peer_b_label} ---\n{peer_b}"
        )
        resp = await self.openai.chat.completions.create(
            model=MEMBER_CONFIG["gpt4o"]["model"],
            max_tokens=400,
            messages=[
                {"role": "system", "content": SYSTEM_REVIEWER},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content

    async def _gemini_review(self, peer_a_label: str, peer_a: str, peer_b_label: str, peer_b: str) -> str:
        prompt = (
            f"{SYSTEM_REVIEWER}\n\n"
            f"You are reviewing analyses from two peers:\n\n"
            f"--- {peer_a_label} ---\n{peer_a}\n\n"
            f"--- {peer_b_label} ---\n{peer_b}"
        )
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: self.gemini_model.generate_content(prompt))
        return resp.text

    # ─────────────────────── Phase 3: Chairman ───────────────────────

    async def _chairman_decide(
        self,
        analyses: dict[str, str],
        reviews: dict[str, str],
    ) -> str:
        council_brief = ""
        for member, analysis in analyses.items():
            cfg = MEMBER_CONFIG[member]
            council_brief += f"=== {cfg['label']} ANALYSIS ===\n{analysis}\n\n"
        council_brief += "\n--- PEER REVIEWS ---\n\n"
        for reviewer, review in reviews.items():
            cfg = MEMBER_CONFIG[reviewer]
            council_brief += f"=== {cfg['label']} REVIEW ===\n{review}\n\n"

        resp = await self.openai.chat.completions.create(
            model=MEMBER_CONFIG["chairman"]["model"],
            max_tokens=800,
            messages=[
                {"role": "system", "content": SYSTEM_CHAIRMAN},
                {"role": "user", "content": council_brief},
            ],
        )
        return resp.choices[0].message.content

    # ─────────────────────── Main Runner ───────────────────────

    async def run(
        self,
        sprint_text: str,
        image_b64: Optional[str],
        image_mime: Optional[str],
    ) -> AsyncIterator[dict]:

        # ── Phase 1 ──────────────────────────────────────────────────
        yield {"type": "phase_start", "phase": 1, "label": "Independent Analysis"}

        tasks = {
            "claude": self._claude_analyze(sprint_text, image_b64, image_mime),
            "gpt4o": self._gpt4o_analyze(sprint_text, image_b64, image_mime),
            "gemini": self._gemini_analyze(sprint_text, image_b64, image_mime),
        }

        analyses: dict[str, str] = {}
        for member, coro in tasks.items():
            yield {"type": "member_thinking", "member": member}

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for member, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                analyses[member] = f"[Error: {result}]"
            else:
                analyses[member] = result
            cfg = MEMBER_CONFIG[member]
            yield {
                "type": "member_analysis",
                "member": member,
                "label": cfg["label"],
                "color": cfg["color"],
                "icon": cfg["icon"],
                "content": analyses[member],
            }

        # ── Phase 2 ──────────────────────────────────────────────────
        yield {"type": "phase_start", "phase": 2, "label": "Cross-Review"}

        review_tasks = {
            "claude": self._claude_review(
                MEMBER_CONFIG["gpt4o"]["label"], analyses["gpt4o"],
                MEMBER_CONFIG["gemini"]["label"], analyses["gemini"],
            ),
            "gpt4o": self._gpt4o_review(
                MEMBER_CONFIG["claude"]["label"], analyses["claude"],
                MEMBER_CONFIG["gemini"]["label"], analyses["gemini"],
            ),
            "gemini": self._gemini_review(
                MEMBER_CONFIG["claude"]["label"], analyses["claude"],
                MEMBER_CONFIG["gpt4o"]["label"], analyses["gpt4o"],
            ),
        }

        for member in review_tasks:
            yield {"type": "member_thinking", "member": member, "phase": 2}

        review_results = await asyncio.gather(*review_tasks.values(), return_exceptions=True)
        reviews: dict[str, str] = {}
        for member, result in zip(review_tasks.keys(), review_results):
            if isinstance(result, Exception):
                reviews[member] = f"[Error: {result}]"
            else:
                reviews[member] = result
            cfg = MEMBER_CONFIG[member]
            yield {
                "type": "member_review",
                "member": member,
                "label": cfg["label"],
                "color": cfg["color"],
                "icon": cfg["icon"],
                "content": reviews[member],
            }

        # ── Phase 3 ──────────────────────────────────────────────────
        yield {"type": "phase_start", "phase": 3, "label": "Chairman's Verdict"}
        yield {"type": "member_thinking", "member": "chairman", "phase": 3}

        decision = await self._chairman_decide(analyses, reviews)
        cfg = MEMBER_CONFIG["chairman"]
        yield {
            "type": "chairman_decision",
            "member": "chairman",
            "label": cfg["label"],
            "color": cfg["color"],
            "icon": cfg["icon"],
            "content": decision,
        }

        yield {"type": "done"}
