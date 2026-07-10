import asyncio
import unittest

from llm_council.llm_streamer import LLMStreamer, _count_tokens
from llm_council.seat_executor import SeatExecutor


async def _empty_search(*args, **kwargs):
    return ""


class _NoopStore:
    def record_phase_output(self, *args, **kwargs):
        pass

    def record_llm_call(self, **kwargs):
        pass


class SeatExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.streamer = LLMStreamer(_NoopStore(), _NoopStore())
        self.executor = SeatExecutor(self.streamer.build_messages, search_context=_empty_search)

    async def test_analyze_drops_images_for_text_model(self):
        captured = {}

        async def fake_stream(member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "done"})
            return "done"

        queue = asyncio.Queue()
        await self.executor.analyze(
            "architect",
            {"label": "Architect", "model": "ollama/qwen2.5:7b", "persona": "test"},
            "topic",
            [{"kind": "image", "data": "abc", "content_type": "image/png", "filename": "photo.png"}],
            queue,
            {"phase1": 500},
            fake_stream,
        )

        self.assertEqual(len(captured["messages"]), 1)
        self.assertIsInstance(captured["messages"][0]["content"], str)
        self.assertNotIn("image_url", captured["messages"][0]["content"])

    async def test_analyze_keeps_images_for_vision_model(self):
        captured = {}

        async def fake_stream(member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "done"})
            return "done"

        queue = asyncio.Queue()
        await self.executor.analyze(
            "architect",
            {"label": "Architect", "model": "ollama/gemma3:4b", "persona": "test"},
            "topic",
            [{"kind": "image", "data": "abc", "content_type": "image/png", "filename": "photo.png"}],
            queue,
            {"phase1": 500},
            fake_stream,
        )

        self.assertEqual(captured["messages"][0]["role"], "system")
        self.assertIsInstance(captured["messages"][1]["content"], list)
        self.assertEqual(captured["messages"][1]["content"][0]["type"], "image_url")

    async def test_review_caps_total_prompt_budget(self):
        captured = {}

        async def fake_stream(member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "done"})
            return "done"

        cfg = {"label": "Reviewer", "model": "test/tiny", "persona": "test"}
        queue = asyncio.Queue()
        await self.executor.review(
            "reviewer",
            cfg,
            {"reviewer": cfg, "peer": {"label": "Peer"}},
            {"reviewer": "self", "peer": "a " * 20000},
            queue,
            {"phase2": 400},
            fake_stream,
        )

        prompt = captured["messages"][1]["content"]
        self.assertLessEqual(_count_tokens("test/tiny", prompt), 4096 - 400 - 800)

    async def test_chairman_caps_council_brief_budget(self):
        captured = {}

        async def fake_stream(member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "{}"})
            return "{}"

        queue = asyncio.Queue()
        await self.executor.chairman_decide(
            {"label": "Chairman", "model": "test/tiny", "persona": "chair"},
            {"peer": {"label": "Peer"}},
            {"peer": "a " * 20000},
            {"peer": "review " * 10000},
            queue,
            {"phase3": 800},
            fake_stream,
        )

        brief = captured["messages"][1]["content"]
        self.assertLessEqual(_count_tokens("test/tiny", brief), 4096 - 800 - 500)


if __name__ == "__main__":
    unittest.main()
