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


if __name__ == "__main__":
    unittest.main()
