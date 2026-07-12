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

import orchestrator as orchestrator_module
from orchestrator import CouncilOrchestrator, DEFAULT_MEMBER_CONFIG, _count_tokens, _specificity_score, parse_chairman_response
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
        self.assertEqual(result["consensus"], [])
        self.assertEqual(result["disputes"], [])
        self.assertEqual(result["_parse_tier"], "parse_failed")

    def test_parse_chairman_response_json_repaired(self):
        result = parse_chairman_response(
            'Here is the JSON: {"verdict":"ship","risk_score":3,"action_items":["do x",],'
            '"consensus":["ok"],"disputes":[]} Hope this helps!'
        )

        self.assertEqual(result["verdict"], "ship")
        self.assertEqual(result["risk_score"], 3)
        self.assertEqual(result["action_items"], ["do x"])
        self.assertEqual(result["_parse_tier"], "json_repaired")

    def test_specificity_score_parse_failed_returns_sentinel(self):
        result = parse_chairman_response("not json at all")

        self.assertEqual(result["_parse_tier"], "parse_failed")
        self.assertEqual(_specificity_score(result, "not json at all"), -1.0)

    def test_specificity_score_rewards_concrete_action_items(self):
        result = {
            "action_items": [
                "Add validation in main.py:228 and test uploads over 20MB before release.",
                "Document COUNCIL_API_KEY behavior in SECURITY.md.",
            ]
        }

        score = _specificity_score(result, "risk and action items")

        self.assertGreaterEqual(score, 0.7)

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

    async def test_stream_passes_timeout_to_litellm(self):
        orchestrator = CouncilOrchestrator()
        captured = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)

            async def gen():
                yield types.SimpleNamespace(
                    choices=[types.SimpleNamespace(
                        delta=types.SimpleNamespace(content="hi", tool_calls=None),
                        finish_reason="stop",
                    )],
                    usage=None,
                )

            return gen()

        queue = asyncio.Queue()
        with patch("orchestrator.litellm.acompletion", new=fake_acompletion):
            await orchestrator._stream_llm_to_queue(
                "architect",
                {"label": "Architect", "model": "test/tiny"},
                1,
                [{"role": "user", "content": "hi"}],
                queue,
                100,
                run_id=None,
            )

        self.assertIn("timeout", captured)
        self.assertEqual(captured["timeout"], orchestrator_module.LLM_TIMEOUT_S)

    async def test_run_marks_partial_when_member_errors(self):
        orchestrator = CouncilOrchestrator()

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            errored = phase == 1 and member_id == "security"
            event = {"type": "member_done", "member": member_id, "full_text": f"{member_id}-{phase}", "errored": errored}
            if errored:
                event["error"] = "boom"
            await queue.put(event)
            return event["full_text"]

        captured_status = {}

        def fake_finish(run_id, status, error=None):
            captured_status["status"] = status
            captured_status["error"] = error

        with patch("orchestrator.parse_input", side_effect=_return_text), \
             patch("orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("orchestrator.run_store.finish_run", side_effect=fake_finish), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("ship it", None, deep_debate=False, run_id="partial-run")]

        done_event = events[-1]
        self.assertEqual(done_event["type"], "done")
        self.assertEqual(done_event["status"], "partial")
        self.assertIn("security", done_event["errored_members"])
        self.assertEqual(captured_status["status"], "partial")

    async def test_run_caps_oversized_roster(self):
        orchestrator = CouncilOrchestrator()
        phase1_members = []

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            if phase == 1:
                phase1_members.append(member_id)
            await queue.put({"type": "member_done", "member": member_id, "full_text": "ok"})
            return "ok"

        oversized = {f"m{i}": {"label": f"M{i}", "model": "test/tiny", "persona": "p"} for i in range(12)}
        oversized["chairman"] = {"label": "Chairman", "model": "test/tiny", "persona": "chair"}

        with patch("orchestrator.parse_input", side_effect=_return_text), \
             patch("orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("ship it", None, oversized, deep_debate=False, run_id="capped-run")]

        self.assertEqual(len(phase1_members), orchestrator_module.MAX_COUNCIL_MEMBERS)
        warnings = [e for e in events if e.get("type") == "warning"]
        self.assertTrue(any("cap" in w["message"].lower() for w in warnings))

    async def test_member_review_caps_total_prompt_budget(self):
        orchestrator = CouncilOrchestrator()
        captured = {}

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "done"})
            return "done"

        cfg = {"label": "Reviewer", "model": "test/tiny", "persona": "test"}
        members_config = {
            "reviewer": cfg,
            "peer_a": {"label": "Peer A"},
            "peer_b": {"label": "Peer B"},
        }
        analyses = {
            "reviewer": "self",
            "peer_a": "a " * 20000,
            "peer_b": "b " * 20000,
        }

        with patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            queue = asyncio.Queue()
            await orchestrator._member_review("reviewer", cfg, members_config, analyses, queue)

        prompt = captured["messages"][1]["content"]
        self.assertLessEqual(_count_tokens("test/tiny", prompt), 4096 - orchestrator._token_budget["phase2"] - 800)

    async def test_chairman_decide_caps_council_brief_budget(self):
        orchestrator = CouncilOrchestrator()
        captured = {}

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "{}"})
            return "{}"

        chairman_cfg = {"label": "Chairman", "model": "test/tiny", "persona": "chair"}
        members_config = {
            "peer_a": {"label": "Peer A"},
            "peer_b": {"label": "Peer B"},
        }
        analyses = {"peer_a": "a " * 20000, "peer_b": "b " * 20000}
        reviews = {"peer_a": "review a " * 10000, "peer_b": "review b " * 10000}

        with patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            queue = asyncio.Queue()
            await orchestrator._chairman_decide(chairman_cfg, members_config, analyses, reviews, queue)

        brief = captured["messages"][1]["content"]
        self.assertLessEqual(_count_tokens("test/tiny", brief), 4096 - orchestrator._token_budget["phase3"] - 500)

    async def test_chairman_skip_path_uses_honest_note_not_fake_reviews(self):
        orchestrator = CouncilOrchestrator()
        captured = {}

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "{}"})
            return "{}"

        chairman_cfg = {"label": "Chairman", "model": "test/tiny", "persona": "chair"}
        members_config = {"peer_a": {"label": "Peer A"}, "peer_b": {"label": "Peer B"}}
        analyses = {"peer_a": "analysis a", "peer_b": "analysis b"}
        reviews = {"peer_a": "SKIPPED - unanimous stub", "peer_b": "SKIPPED - unanimous stub"}

        with patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            queue = asyncio.Queue()
            await orchestrator._chairman_decide(
                chairman_cfg, members_config, analyses, reviews, queue,
                phase2_note="high agreement (min pairwise 0.95)",
            )

        brief = captured["messages"][1]["content"]
        self.assertIn("Phase 2 cross-review was SKIPPED", brief)
        self.assertIn("high agreement", brief)
        self.assertNotIn("unanimous stub", brief)

    async def test_chairman_fair_allocation_keeps_every_member(self):
        orchestrator = CouncilOrchestrator()
        captured = {}

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "{}"})
            return "{}"

        chairman_cfg = {"label": "Chairman", "model": "test/tiny", "persona": "chair"}
        members_config = {
            "peer_a": {"label": "PeerAAA"},
            "peer_b": {"label": "PeerBBB"},
            "peer_c": {"label": "PeerCCC"},
        }
        # Oversized analyses force truncation; every member label must still appear.
        analyses = {"peer_a": "a " * 9000, "peer_b": "b " * 9000, "peer_c": "c " * 9000}
        reviews = {"peer_a": "ra " * 5000, "peer_b": "rb " * 5000, "peer_c": "rc " * 5000}

        with patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            queue = asyncio.Queue()
            await orchestrator._chairman_decide(chairman_cfg, members_config, analyses, reviews, queue)

        brief = captured["messages"][1]["content"]
        for label in ("PeerAAA", "PeerBBB", "PeerCCC"):
            self.assertIn(label, brief)

    async def test_member_review_keeps_all_peers_under_pressure(self):
        orchestrator = CouncilOrchestrator()
        captured = {}

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            captured["messages"] = messages
            await queue.put({"type": "member_done", "member": member_id, "full_text": "done"})
            return "done"

        cfg = {"label": "Reviewer", "model": "test/tiny", "persona": "test"}
        members_config = {
            "reviewer": cfg,
            "peer_a": {"label": "PeerAAA"},
            "peer_b": {"label": "PeerBBB"},
        }
        analyses = {"reviewer": "self", "peer_a": "a " * 20000, "peer_b": "b " * 20000}

        with patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            queue = asyncio.Queue()
            await orchestrator._member_review("reviewer", cfg, members_config, analyses, queue)

        prompt = captured["messages"][1]["content"]
        self.assertIn("PeerAAA", prompt)
        self.assertIn("PeerBBB", prompt)

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
        self.assertEqual(max_tokens_by_phase[1], {500})
        self.assertEqual(max_tokens_by_phase[2], {400})
        self.assertEqual(max_tokens_by_phase[3], {800})

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

    async def test_full_council_deep_debate_with_stubbed_ollama(self):
        class FakeDelta:
            content = "stubbed output"

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

        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunStore(os.path.join(temp_dir, "runs.db"))
            with patch("orchestrator.run_store", store), \
                 patch("orchestrator.litellm.acompletion", side_effect=fake_acompletion), \
                 patch("orchestrator.parse_input", side_effect=_return_text), \
                 patch("orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
                 patch("orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
                 patch("orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
                 patch("orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
                 patch("orchestrator.skill_registry.extract_skills", side_effect=_noop_async), \
                 patch("orchestrator.get_search_context", side_effect=_return_empty_search), \
                 patch("orchestrator.smart_phase.should_skip", return_value=(False, 0.42)):
                events = [
                    event
                    async for event in CouncilOrchestrator().run(
                        "run a full stubbed council",
                        None,
                        custom_config=DEFAULT_MEMBER_CONFIG,
                        deep_debate=True,
                        run_id="stubbed-full-run",
                    )
                ]
            run = store.get_run("stubbed-full-run")

        phase_counts = {}
        for phase in run["phases"]:
            phase_counts[phase["phase"]] = phase_counts.get(phase["phase"], 0) + 1

        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(phase_counts, {1: 3, 2: 3, 3: 1})


if __name__ == "__main__":
    unittest.main()
