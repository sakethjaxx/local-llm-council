import sys
import types
import unittest
from unittest.mock import patch


if "litellm" not in sys.modules:
    litellm_stub = types.ModuleType("litellm")
    litellm_stub.suppress_debug_info = False

    async def _unused_acompletion(*args, **kwargs):
        raise RuntimeError("litellm stub should not be called in tests")

    litellm_stub.acompletion = _unused_acompletion
    sys.modules["litellm"] = litellm_stub

import io_parser
import router_agent


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class InputAndRouterTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_uploaded_file_degrades_gracefully_on_bad_pdf(self):
        with patch.object(io_parser.fitz, "open", side_effect=RuntimeError("bad pdf")):
            result = io_parser.parse_uploaded_file("broken.pdf", "application/pdf", b"not-a-pdf")

        self.assertEqual(result["kind"], "unsupported")
        self.assertIn("Failed to parse attachment", result["summary"])

    async def test_generate_swarm_omits_response_format_for_ollama(self):
        captured = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)
            return _FakeResponse(
                """```json
                {"experts": {"architect": {"label": "Architect", "model": "ollama/qwen2.5:7b", "color": "#111111", "icon": "A", "persona": "design"}}}
                ```"""
            )

        with patch.object(router_agent.litellm, "acompletion", side_effect=fake_acompletion):
            swarm = await router_agent.generate_swarm("review architecture", "ollama/qwen2.5:7b")

        self.assertNotIn("response_format", captured)
        self.assertIn("architect", swarm)
        self.assertEqual(swarm["architect"]["model"], "ollama/qwen2.5:7b")

    async def test_generate_swarm_only_capability_routes_to_available_models(self):
        async def fake_acompletion(**kwargs):
            return _FakeResponse(
                '{"experts": {"code": {"label": "Code Engineer", "model": "ollama/qwen2.5:7b", "color": "#111111", "icon": "C", "persona": "review code"}}}'
            )

        with patch.object(router_agent.litellm, "acompletion", side_effect=fake_acompletion):
            swarm = await router_agent.generate_swarm(
                "review architecture",
                "ollama/qwen2.5:7b",
                available_models=["ollama/qwen2.5:7b", "ollama/qwen2.5-coder:7b"],
            )

        self.assertEqual(swarm["code"]["model"], "ollama/qwen2.5-coder:7b")

    def test_apply_personas_to_roster_preserves_hardware_fitted_models(self):
        roster = {
            "architect": {"label": "Architect", "model": "ollama/qwen2.5:3b", "persona": "base", "color": "#111", "icon": "A"},
            "security": {"label": "Security", "model": "ollama/llama3.2:3b", "persona": "base", "color": "#222", "icon": "S"},
            "chairman": {"label": "Chairman", "model": "ollama/qwen2.5:14b", "persona": "chair", "color": "#333", "icon": "C"},
        }
        personas = {
            "code": {"label": "Code Reviewer", "model": "ollama/qwen2.5-coder:14b", "persona": "review code", "color": "#abc", "icon": "R"},
            "risk": {"label": "Risk Analyst", "model": "ollama/deepseek-r1:32b", "persona": "find risks", "color": "#def", "icon": "!"},
        }

        routed = router_agent.apply_personas_to_roster(roster, personas)

        self.assertEqual(routed["architect"]["model"], "ollama/qwen2.5:3b")
        self.assertEqual(routed["security"]["model"], "ollama/llama3.2:3b")
        self.assertEqual(routed["chairman"], roster["chairman"])
        self.assertEqual(routed["architect"]["label"], "Code Reviewer")


if __name__ == "__main__":
    unittest.main()
