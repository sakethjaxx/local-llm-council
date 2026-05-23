import asyncio
import os
import sys
import tempfile
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

from orchestrator import CouncilOrchestrator, DEFAULT_MEMBER_CONFIG, parse_chairman_response
from run_store import RunStore


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
    def test_parse_chairman_response_clean_json(self):
        result = parse_chairman_response(
            '{"verdict":"ship","risk_score":2,"action_items":["test"],"consensus":["ok"],"disputes":[]}'
        )

        self.assertEqual(result["verdict"], "ship")
        self.assertEqual(result["risk_score"], 2)
        self.assertEqual(result["action_items"], ["test"])
        self.assertEqual(result["_parse_tier"], "json")

    def test_parse_chairman_response_fenced_json(self):
        result = parse_chairman_response(
            '```json\n{"verdict":"hold","risk_score":5,"action_items":[],"consensus":"","disputes":[]}\n```'
        )

        self.assertEqual(result["verdict"], "hold")
        self.assertEqual(result["risk_score"], 5)
        self.assertEqual(result["_parse_tier"], "fenced_json")

    def test_parse_chairman_response_partial_json(self):
        result = parse_chairman_response('notes {"verdict":"revise","risk_score":7.5 trailing')

        self.assertEqual(result["verdict"], "revise")
        self.assertEqual(result["risk_score"], 7.5)
        self.assertEqual(result["action_items"], [])
        self.assertEqual(result["_parse_tier"], "regex_extracted")

    def test_parse_chairman_response_total_garbage(self):
        result = parse_chairman_response("not json")

        self.assertEqual(result["verdict"], "parse_failed")
        self.assertEqual(result["risk_score"], -1)
        self.assertEqual(result["action_items"], [])
        self.assertEqual(result["consensus"], "")
        self.assertEqual(result["disputes"], [])
        self.assertEqual(result["_parse_tier"], "parse_failed")

    def test_build_messages_keeps_images_for_local_multimodal_model(self):
        orchestrator = CouncilOrchestrator()

        messages = orchestrator._build_messages(
            "ollama/gemma3:4b",
            "system prompt",
            [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                {"type": "text", "text": "look at this"},
            ],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIsInstance(messages[1]["content"], list)

    async def test_member_analyze_skips_images_for_text_model(self):
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

    async def test_member_analyze_keeps_images_for_image_model(self):
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
                {"label": "Architect", "model": "ollama/gemma3:4b", "persona": "test"},
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
             patch("orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
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
             patch("orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("orchestrator.smart_phase.should_skip", return_value=(False, 0.42)), \
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

    async def test_run_applies_economy_token_budget_profile(self):
        orchestrator = CouncilOrchestrator()
        max_tokens_by_phase = {}

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            max_tokens_by_phase.setdefault(phase, set()).add(max_tokens)
            await queue.put({"type": "member_done", "member": member_id, "full_text": f"{member_id}-phase-{phase}"})
            return f"{member_id}-phase-{phase}"

        with patch("orchestrator.parse_input", side_effect=_return_text), \
             patch("orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("orchestrator.smart_phase.should_skip", return_value=(False, 0.42)), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [
                event
                async for event in orchestrator.run(
                    "budget this",
                    None,
                    deep_debate=True,
                    run_id="budget-run",
                    token_budget_profile="economy",
                )
            ]

        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(max_tokens_by_phase[1], {300})
        self.assertEqual(max_tokens_by_phase[2], {250})
        self.assertEqual(max_tokens_by_phase[3], {500})

    async def test_run_records_all_fast_mode_phases(self):
        class FakeDelta:
            content = "persisted output"

        class FakeChoice:
            delta = FakeDelta()

        class FakeChunk:
            choices = [FakeChoice()]

        class FakeStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                if getattr(self, "_done", False):
                    raise StopAsyncIteration
                self._done = True
                return FakeChunk()

        async def fake_acompletion(*args, **kwargs):
            return FakeStream()

        config = {
            "architect": DEFAULT_MEMBER_CONFIG["architect"],
            "chairman": DEFAULT_MEMBER_CONFIG["chairman"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunStore(os.path.join(temp_dir, "runs.db"))
            with patch("orchestrator.run_store", store), \
                 patch("orchestrator.litellm.acompletion", side_effect=fake_acompletion), \
                 patch("orchestrator.parse_input", side_effect=_return_text), \
                 patch("orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
                 patch("orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
                 patch("orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
                 patch("orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
                 patch("orchestrator.get_search_context", side_effect=_return_empty_search):
                events = [
                    event
                    async for event in CouncilOrchestrator().run(
                        "persist this",
                        None,
                        custom_config=config,
                        deep_debate=False,
                        run_id="persist-run",
                    )
                ]
            run = store.get_run("persist-run")

        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(run["status"], "completed")
        self.assertEqual({phase["phase"] for phase in run["phases"]}, {1, 2, 3})
        self.assertTrue(all(phase["output"] for phase in run["phases"]))


if __name__ == "__main__":
    unittest.main()
