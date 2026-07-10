import unittest
from unittest.mock import patch

import llm_council.ollama_manager as ollama_manager


class TagNormalizationTests(unittest.TestCase):
    """`ollama pull llama3.2` installs `llama3.2:latest` — the two must match.

    Found live: a roster pinned to `ollama/llama3.2` was reported missing while
    `llama3.2:latest` sat installed, blocking every run.
    """

    CONFIG = {
        "a": {"model": "ollama/llama3.2"},
        "b": {"model": "ollama/qwen2.5:3b"},
        "chairman": {"model": "ollama/gemma2:2b"},
    }

    def test_untagged_requirement_matches_latest_install(self):
        with patch.object(
            ollama_manager,
            "get_installed_models",
            return_value=["llama3.2:latest", "qwen2.5:3b", "gemma2:2b"],
        ):
            status = ollama_manager.ensure_models_for_config(self.CONFIG, auto_pull=False)
        self.assertTrue(status["ready"])
        self.assertEqual(status["missing"], [])

    def test_tagged_requirement_matches_untagged_install(self):
        with patch.object(
            ollama_manager,
            "get_installed_models",
            return_value=["llama3.2", "qwen2.5:3b", "gemma2:2b"],
        ):
            status = ollama_manager.ensure_models_for_config(self.CONFIG, auto_pull=False)
        self.assertTrue(status["ready"])

    def test_genuinely_missing_model_still_reported(self):
        with patch.object(
            ollama_manager,
            "get_installed_models",
            return_value=["qwen2.5:3b"],
        ):
            status = ollama_manager.ensure_models_for_config(self.CONFIG, auto_pull=False)
        self.assertFalse(status["ready"])
        self.assertIn("llama3.2", status["missing"])
        self.assertIn("gemma2:2b", status["missing"])

    def test_distinct_tags_are_not_conflated(self):
        with patch.object(
            ollama_manager,
            "get_installed_models",
            return_value=["qwen2.5:7b"],
        ):
            missing = ollama_manager.get_missing_models({"a": {"model": "ollama/qwen2.5:3b"}})
        self.assertEqual(missing, ["qwen2.5:3b"])

    def test_server_down_reports_not_running(self):
        with patch.object(ollama_manager, "get_installed_models", return_value=None):
            status = ollama_manager.ensure_models_for_config(self.CONFIG, auto_pull=False)
        self.assertFalse(status["ollama_running"])
        self.assertFalse(status["ready"])
        self.assertIn("not reachable", status["hint"])


if __name__ == "__main__":
    unittest.main()
