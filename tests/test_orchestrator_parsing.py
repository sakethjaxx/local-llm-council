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

from orchestrator import (
    CouncilOrchestrator,
    _count_tokens,
    _specificity_score,
    parse_chairman_response,
)


class OrchestratorParsingTests(unittest.IsolatedAsyncioTestCase):
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

    def test_parse_chairman_response_includes_confidence(self):
        result = parse_chairman_response(
            '{"verdict":"ship","risk_score":2,"confidence":8,"action_items":[],"consensus":[],"disputes":[]}'
        )
        self.assertEqual(result["confidence"], 8)
        legacy = parse_chairman_response('{"verdict":"ship","risk_score":2,"action_items":[]}')
        self.assertEqual(legacy["confidence"], -1)

    def test_parse_chairman_response_regex_robustness(self):
        raw = "verdict: 'revise', risk_score: 8, confidence: 6, action_items: ['fix bugs', 'run tests'], consensus: [], disputes: ['none']"
        result = parse_chairman_response(raw)
        self.assertEqual(result["verdict"], "revise")
        self.assertEqual(result["risk_score"], 8)
        self.assertEqual(result["confidence"], 6)
        self.assertEqual(result["action_items"], ["fix bugs", "run tests"])
        self.assertEqual(result["disputes"], ["none"])
        self.assertEqual(result["_parse_tier"], "regex_extracted")

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


if __name__ == "__main__":
    unittest.main()
