import unittest
from types import SimpleNamespace
from unittest.mock import patch

import llm_council.hardware_detect as hardware_detect


def _memory(total_gb: float):
    return SimpleNamespace(total=int(total_gb * (1024 ** 3)))


class HardwareSuggestionTests(unittest.TestCase):
    def test_24gb_prefers_balanced_mid_sized_roster(self):
        with patch.object(hardware_detect.psutil, "virtual_memory", return_value=_memory(24)):
            suggestion = hardware_detect.get_hardware_suggestion()

        self.assertEqual(suggestion["tier_name"], "Tier 3A: 20-28GB (Balanced 7B-9B Local Models)")
        self.assertEqual(suggestion["config"]["architect"]["model"], "ollama/qwen2.5:7b")
        self.assertEqual(suggestion["config"]["security"]["model"], "ollama/gemma2:9b")
        self.assertEqual(suggestion["config"]["perf"]["model"], "ollama/llama3.1:8b")
        self.assertEqual(suggestion["config"]["chairman"]["model"], "ollama/qwen2.5:7b")
        self.assertNotIn("ollama pull qwen2.5:14b", suggestion["recommended_pull"])
        self.assertNotIn("ollama pull deepseek-r1:14b", suggestion["recommended_pull"])

    def test_32gb_allows_one_14b_default_model(self):
        with patch.object(hardware_detect.psutil, "virtual_memory", return_value=_memory(32)):
            suggestion = hardware_detect.get_hardware_suggestion()

        self.assertEqual(suggestion["tier_name"], "Tier 3B: 28-40GB (Mixed 8B-14B Local Models)")
        self.assertEqual(suggestion["config"]["architect"]["model"], "ollama/qwen2.5:14b")
        self.assertEqual(suggestion["config"]["security"]["model"], "ollama/gemma2:9b")
        self.assertEqual(suggestion["config"]["perf"]["model"], "ollama/llama3.1:8b")
        self.assertEqual(suggestion["config"]["chairman"]["model"], "ollama/qwen2.5:14b")
        self.assertNotIn("ollama pull deepseek-r1:14b", suggestion["recommended_pull"])


if __name__ == "__main__":
    unittest.main()
