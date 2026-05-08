import asyncio
import os
import sys
import types
import unittest
from unittest.mock import patch

os.environ["COUNCIL_METRICS_FILE"] = ""

if "litellm" not in sys.modules:
    litellm_stub = types.ModuleType("litellm")
    litellm_stub.suppress_debug_info = False

    async def _unused_acompletion(*args, **kwargs):
        raise RuntimeError("litellm stub should not be called in tests")

    litellm_stub.acompletion = _unused_acompletion
    sys.modules["litellm"] = litellm_stub

from orchestrator import CouncilOrchestrator, DEFAULT_MEMBER_CONFIG


async def _return_text(value):
    return value


async def _return_first_arg(*args, **kwargs):
    return args[0]


async def _return_empty_context(*args, **kwargs):
    return ""


async def _noop_async(*args, **kwargs):
    return None


async def _return_empty_search(*args, **kwargs):
    return ""


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def test_build_messages_keeps_images_for_ollama(self):
        orchestrator = CouncilOrchestrator()

        messages = orchestrator._build_messages(
            "ollama/llava:7b",
            "system prompt",
            [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                {"type": "text", "text": "look at this"},
            ],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIsInstance(messages[1]["content"], list)

    async def test_member_analyze_skips_images_for_non_vision_model(self):
        orchestrator = CouncilOrchestrator()
        captured = {}

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "done"})
            return "done"

        with patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            queue = asyncio.Queue()
            await orchestrator._member_analyze(
                "architect",
                {"label": "Architect", "model": "ollama/qwen2.5:7b", "persona": "test"},
                "topic",
                [{"kind": "image", "data": "abc", "content_type": "image/png", "filename": "photo.png"}],
                queue,
            )

        self.assertEqual(len(captured["messages"]), 1)
        self.assertIsInstance(captured["messages"][0]["content"], str)

    async def test_member_analyze_keeps_images_for_vision_model(self):
        orchestrator = CouncilOrchestrator()
        captured = {}

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "done"})
            return "done"

        with patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            queue = asyncio.Queue()
            await orchestrator._member_analyze(
                "architect",
                {"label": "Architect", "model": "ollama/llava:7b", "persona": "test"},
                "topic",
                [{"kind": "image", "data": "abc", "content_type": "image/png", "filename": "photo.png"}],
                queue,
            )

        self.assertEqual(captured["messages"][0]["role"], "system")
        self.assertIsInstance(captured["messages"][1]["content"], list)

    async def test_run_fast_mode_completes(self):
        orchestrator = CouncilOrchestrator()
        stream_calls = []
        test_case = self

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            test_case.assertIs(self, orchestrator)
            test_case.assertIsInstance(cfg, dict)
            stream_calls.append((member_id, phase, cfg["label"]))
            await queue.put({"type": "member_done", "member": member_id, "full_text": f"{member_id}-phase-{phase}"})
            return f"{member_id}-phase-{phase}"

        with patch("orchestrator.parse_input", side_effect=_return_text), \
             patch("orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("ship it", None, deep_debate=False, run_id="fast-run")]

        phase_labels = [event["label"] for event in events if event["type"] == "phase_start"]
        self.assertEqual(
            phase_labels,
            ["Independent Analysis", "Cross-Review (Bypassed - Fast Mode)", "Chairman's Verdict"],
        )
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(
            stream_calls,
            [
                ("architect", 1, DEFAULT_MEMBER_CONFIG["architect"]["label"]),
                ("security", 1, DEFAULT_MEMBER_CONFIG["security"]["label"]),
                ("perf", 1, DEFAULT_MEMBER_CONFIG["perf"]["label"]),
                ("chairman", 3, DEFAULT_MEMBER_CONFIG["chairman"]["label"]),
            ],
        )

    async def test_run_deep_debate_uses_review_phase(self):
        orchestrator = CouncilOrchestrator()
        phases = []
        test_case = self

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            test_case.assertIsInstance(cfg, dict)
            phases.append((member_id, phase))
            await queue.put({"type": "member_done", "member": member_id, "full_text": f"{member_id}-phase-{phase}"})
            return f"{member_id}-phase-{phase}"

        with patch("orchestrator.parse_input", side_effect=_return_text), \
             patch("orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("orchestrator.check_unanimous_consensus", return_value=False), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("debate this", None, deep_debate=True, run_id="debate-run")]

        phase_labels = [event["label"] for event in events if event["type"] == "phase_start"]
        self.assertEqual(
            phase_labels,
            ["Independent Analysis", "Cross-Review", "Chairman's Verdict"],
        )
        phase_two_calls = [call for call in phases if call[1] == 2]
        self.assertEqual(len(phase_two_calls), 3)
        self.assertEqual(events[-1]["type"], "done")


if __name__ == "__main__":
    unittest.main()
