import unittest

from llm_council.provider_caps import MODELS, PROVIDERS, caps_for, supports_image_input


class ProviderCapsTests(unittest.TestCase):
    def test_known_local_model_caps(self):
        model_caps, provider_caps = caps_for("ollama/qwen2.5:7b")

        self.assertEqual(model_caps.provider, "ollama")
        self.assertEqual(provider_caps.provider, "ollama")
        self.assertEqual(provider_caps.response_format, False)
        self.assertEqual(provider_caps.cost_per_1k_input, 0.0)

    def test_known_image_model_caps(self):
        model_caps, provider_caps = caps_for("ollama/gemma3:4b")

        self.assertEqual(provider_caps.provider, "ollama")
        self.assertEqual(model_caps.context_window, 32768)
        self.assertEqual(supports_image_input("ollama/gemma3:4b"), True)

    def test_unknown_model_uses_safe_defaults(self):
        model_caps, provider_caps = caps_for("made-up-model/unknown-v99")

        self.assertEqual(model_caps.provider, "made-up-model")
        self.assertEqual(model_caps.vision, False)
        self.assertEqual(model_caps.context_window, 4096)
        self.assertEqual(model_caps.strengths, [])
        self.assertEqual(model_caps.tool_use, False)
        self.assertEqual(provider_caps.provider, "made-up-model")
        self.assertEqual(provider_caps.response_format, False)

    def test_required_providers_present(self):
        for provider in ("ollama", "openai", "anthropic", "gemini", "groq"):
            self.assertIn(provider, PROVIDERS)

    def test_all_known_models_have_strengths_and_tool_use_fields(self):
        for model_caps in MODELS.values():
            self.assertIsInstance(model_caps.strengths, list)
            self.assertIsInstance(model_caps.tool_use, bool)


if __name__ == "__main__":
    unittest.main()
