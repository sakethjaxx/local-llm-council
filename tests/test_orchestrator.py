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

from llm_council.chairman_result import parse_chairman_response, specificity_score as _specificity_score
from llm_council.llm_streamer import _count_tokens
from llm_council.orchestrator import CouncilOrchestrator, DEFAULT_MEMBER_CONFIG
from llm_council.run_store import RunStore


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
    async def asyncSetUp(self):
        self._run_store = RunStore(":memory:")
        self._skill_extract_patch = patch("llm_council.orchestrator.skill_registry.extract_skills", side_effect=_noop_async)
        self._fingerprint_patch = patch("llm_council.orchestrator.fingerprint", return_value={"hash": "test-fingerprint"})
        self._run_store_patch = patch("llm_council.orchestrator.run_store", self._run_store)
        self._run_store_patch.start()
        self._skill_extract_patch.start()
        self._fingerprint_patch.start()
        self.addCleanup(self._run_store_patch.stop)
        self.addCleanup(self._skill_extract_patch.stop)
        self.addCleanup(self._fingerprint_patch.stop)

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

        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("ship it", None, deep_debate=False, run_id="fast-run")]

        phase_labels = [event["label"] for event in events if event["type"] == "phase_start"]
        self.assertEqual(
            phase_labels,
            [
                "Independent Analysis",
                "Cross-Review (Skipped — Fast mode: no debate. Enable Deep Debate for cross-examination.)",
                "Chairman's Verdict",
            ],
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

        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("llm_council.orchestrator.smart_phase.should_skip", return_value=(False, 0.42, {"reason": "stub", "stances": {}, "split": False})), \
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

    async def test_run_stops_when_every_phase1_call_fails(self):
        orchestrator = CouncilOrchestrator()
        phases = []

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            phases.append((member_id, phase))
            label = cfg.get("label", member_id)
            text = (
                f"[Error connecting to {label}: "
                "litellm.APIConnectionError: OllamaException - All connection attempts failed]"
            )
            await queue.put({"type": "member_done", "member": member_id, "full_text": text, "ok": False})
            return text

        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            with self.assertRaises(RuntimeError) as ctx:
                [event async for event in orchestrator.run("connection failure", None, deep_debate=True, run_id="fail-run")]

        self.assertIn("Phase 1 analysis failed for", str(ctx.exception))
        self.assertIn("Ollama calls use", str(ctx.exception))
        # Every seat ran Phase 1; none advanced past it.
        self.assertEqual([phase for _, phase in phases], [1, 1, 1])

    async def test_run_survives_when_one_seat_fails(self):
        orchestrator = CouncilOrchestrator()
        phases = []

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            phases.append((member_id, phase))
            if member_id == "architect" and phase == 1:
                text = "[Error connecting to Lead Architect: OllamaException]"
                await queue.put({"type": "member_done", "member": member_id, "full_text": text, "ok": False})
                return text
            text = f"{member_id}-phase-{phase}"
            await queue.put({"type": "member_done", "member": member_id, "full_text": text, "ok": True})
            return text

        unanimous_info = {"reason": "All members reached PROCEED", "stances": {}, "split": False}
        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("llm_council.orchestrator.smart_phase.should_skip", return_value=(True, 0.95, unanimous_info)), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("one seat down", None, deep_debate=True, run_id="survivor-run")]

        # Run completes despite the dropped seat.
        self.assertEqual(events[-1]["type"], "done")
        warnings = [e for e in events if e["type"] == "warning" and "Lead Architect" in e.get("message", "")]
        self.assertEqual(len(warnings), 1)
        self.assertIn("dropped", warnings[0]["message"])
        # The failed seat never advances beyond its failed Phase 1 call.
        self.assertNotIn(("architect", 3), phases)
        # Chairman still synthesizes a verdict.
        self.assertIn("chairman", [m for m, _ in phases])

    async def test_run_split_stances_trigger_rebuttal_round(self):
        orchestrator = CouncilOrchestrator()
        phases = []

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            phases.append((member_id, phase))
            await queue.put({"type": "member_done", "member": member_id, "full_text": f"{member_id}-phase-{phase}"})
            return f"{member_id}-phase-{phase}"

        split_info = {
            "reason": "Stances split (architect=PROCEED, security=HOLD)",
            "stances": {"architect": {"verdict": "PROCEED", "confidence": 8, "summary": ""}},
            "split": True,
        }
        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("llm_council.orchestrator.smart_phase.should_skip", return_value=(False, 0.3, split_info)), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("contested topic", None, deep_debate=True, run_id="rebuttal-run")]

        phase_two_calls = [call for call in phases if call[1] == 2]
        # 3 cross-reviews + 3 rebuttals, one bounded round
        self.assertEqual(len(phase_two_calls), 6)
        self.assertEqual(len([e for e in events if e["type"] == "rebuttal_start"]), 1)
        decision_events = [e for e in events if e["type"] == "smart_phase_decision"]
        self.assertEqual(len(decision_events), 1)
        self.assertTrue(decision_events[0]["split"])
        self.assertIn("split", decision_events[0]["reason"].lower())
        self.assertEqual(events[-1]["type"], "done")

    async def test_run_unanimous_stances_skip_debate_without_rebuttal(self):
        orchestrator = CouncilOrchestrator()
        phases = []

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            phases.append((member_id, phase))
            await queue.put({"type": "member_done", "member": member_id, "full_text": f"{member_id}-phase-{phase}"})
            return f"{member_id}-phase-{phase}"

        unanimous_info = {
            "reason": "All 3 members independently reached PROCEED",
            "stances": {},
            "split": False,
        }
        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("llm_council.orchestrator.smart_phase.should_skip", return_value=(True, 0.95, unanimous_info)), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("agreed topic", None, deep_debate=True, run_id="skip-run")]

        phase_two_calls = [call for call in phases if call[1] == 2]
        self.assertEqual(len(phase_two_calls), 0)
        self.assertEqual(len([e for e in events if e["type"] == "rebuttal_start"]), 0)
        skip_labels = [e["label"] for e in events if e["type"] == "phase_start" and e["phase"] == 2]
        self.assertIn("PROCEED", skip_labels[0])
        self.assertEqual(events[-1]["type"], "done")

    async def test_run_warns_when_all_seats_share_one_model(self):
        orchestrator = CouncilOrchestrator()

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            await queue.put({"type": "member_done", "member": member_id, "full_text": f"{member_id}-out"})
            return f"{member_id}-out"

        clone_config = {
            "a": {"label": "Seat A", "model": "ollama/qwen2.5:7b", "persona": "same"},
            "b": {"label": "Seat B", "model": "ollama/qwen2.5:7b", "persona": "same"},
            "c": {"label": "Seat C", "model": "ollama/qwen2.5:7b", "persona": "same"},
            "chairman": {"label": "Chairman", "model": "ollama/qwen2.5:7b", "persona": "chair"},
        }
        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [
                event
                async for event in orchestrator.run(
                    "clone check", None, custom_config=clone_config, deep_debate=False, run_id="clone-run"
                )
            ]

        clone_warnings = [e for e in events if e["type"] == "warning" and "same model" in e.get("message", "")]
        self.assertEqual(len(clone_warnings), 1)
        self.assertIn("ollama/qwen2.5:7b", clone_warnings[0]["message"])

    async def test_run_does_not_warn_when_one_model_has_distinct_seat_behavior(self):
        orchestrator = CouncilOrchestrator()

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            await queue.put({"type": "member_done", "member": member_id, "full_text": f"{member_id}-out"})
            return f"{member_id}-out"

        reused_model_config = {
            "a": {"label": "Seat A", "model": "ollama/qwen2.5:7b", "persona": "architecture"},
            "b": {"label": "Seat B", "model": "ollama/qwen2.5:7b", "persona": "security"},
            "c": {"label": "Seat C", "model": "ollama/qwen2.5:7b", "persona": "performance"},
            "chairman": {"label": "Chairman", "model": "ollama/qwen2.5:7b", "persona": "chair"},
        }
        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [
                event
                async for event in orchestrator.run(
                    "reused model check", None, custom_config=reused_model_config, deep_debate=False, run_id="reused-run"
                )
            ]

        clone_warnings = [e for e in events if e["type"] == "warning" and "same model" in e.get("message", "")]
        confidence_events = [e for e in events if e["type"] == "council_confidence"]
        self.assertEqual(clone_warnings, [])
        self.assertEqual(confidence_events[0]["diversity"]["distinct_behaviors"], 3)
        self.assertFalse(confidence_events[0]["clone_capped"])

    async def test_run_yields_chairman_member_done_with_full_text(self):
        orchestrator = CouncilOrchestrator()

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            text = '{"verdict":"ship"}' if member_id == "chairman" else f"{member_id}-out"
            await queue.put({"type": "member_done", "member": member_id, "full_text": text})
            return text

        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("verdict check", None, deep_debate=False, run_id="done-run")]

        chairman_done = [e for e in events if e["type"] == "member_done" and e["member"] == "chairman"]
        self.assertEqual(len(chairman_done), 1)
        self.assertEqual(chairman_done[0]["full_text"], '{"verdict":"ship"}')

    async def test_run_emits_enforced_verdict_and_confidence_events(self):
        orchestrator = CouncilOrchestrator()
        chairman_json = (
            '{"verdict":"ship it","risk_score":3,"action_items":["do x"],'
            '"consensus":["Everybody agrees on quality","Also everyone likes tests"],'
            '"disputes":[]}'
        )

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            text = chairman_json if member_id == "chairman" else f"{member_id} analysis\nSTANCE: PROCEED | CONFIDENCE: 8 | Go."
            await queue.put({"type": "member_done", "member": member_id, "full_text": text})
            return text

        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            events = [event async for event in orchestrator.run("trust check", None, deep_debate=False, run_id="trust-run")]

        # Both chairman consensus points name no member → grounding enforcement strips them.
        grounding_events = [e for e in events if e["type"] == "chairman_grounding"]
        self.assertEqual(len(grounding_events), 1)
        self.assertTrue(grounding_events[0]["enforced"])
        self.assertEqual(grounding_events[0]["removed"], 2)

        verdict_events = [e for e in events if e["type"] == "chairman_verdict"]
        self.assertEqual(len(verdict_events), 1)
        self.assertEqual(verdict_events[0]["verdict"], "ship it")
        self.assertEqual(verdict_events[0]["consensus"], [])
        self.assertEqual(verdict_events[0]["removed_points"], 2)

        confidence_events = [e for e in events if e["type"] == "council_confidence"]
        self.assertEqual(len(confidence_events), 1)
        self.assertIn("score", confidence_events[0])
        # Fast mode → not_deliberated, and stances were still extracted natively.
        self.assertEqual(confidence_events[0]["agreement_state"], "not_deliberated")
        self.assertEqual(len(confidence_events[0]["stances"]), 3)

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

        with patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=fake_stream):
            queue = asyncio.Queue()
            await orchestrator._chairman_decide(chairman_cfg, members_config, analyses, reviews, queue)

        brief = captured["messages"][1]["content"]
        self.assertLessEqual(_count_tokens("test/tiny", brief), 4096 - orchestrator._token_budget["phase3"] - 500)

    async def test_run_applies_economy_token_budget_profile(self):
        orchestrator = CouncilOrchestrator()
        max_tokens_by_phase = {}

        async def fake_stream(self, member_id, cfg, phase, messages, queue, max_tokens, response_format=None, run_id=None):
            max_tokens_by_phase.setdefault(phase, set()).add(max_tokens)
            await queue.put({"type": "member_done", "member": member_id, "full_text": f"{member_id}-phase-{phase}"})
            return f"{member_id}-phase-{phase}"

        with patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("llm_council.orchestrator.smart_phase.should_skip", return_value=(False, 0.42, {"reason": "stub", "stances": {}, "split": False})), \
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

        store = RunStore(":memory:")
        with patch("llm_council.orchestrator.run_store", store), \
             patch("llm_council.llm_streamer.litellm.acompletion", side_effect=fake_acompletion), \
             patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search):
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

        store = RunStore(":memory:")
        with patch("llm_council.orchestrator.run_store", store), \
             patch("llm_council.llm_streamer.litellm.acompletion", side_effect=fake_acompletion), \
             patch("llm_council.orchestrator.parse_input", side_effect=_return_text), \
             patch("llm_council.orchestrator.chunk_and_summarize", side_effect=_return_first_arg), \
             patch("llm_council.orchestrator.memory_engine.get_context", side_effect=_return_empty_context), \
             patch("llm_council.orchestrator.memory_engine.extract_memory", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop_async), \
             patch("llm_council.orchestrator.skill_registry.extract_skills", side_effect=_noop_async), \
             patch("llm_council.orchestrator.get_search_context", side_effect=_return_empty_search), \
             patch("llm_council.orchestrator.smart_phase.should_skip", return_value=(False, 0.42, {"reason": "stub", "stances": {}, "split": False})):
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
