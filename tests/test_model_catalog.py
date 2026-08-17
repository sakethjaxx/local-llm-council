import unittest
from unittest.mock import patch

import hardware_detect


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_lists_only_ollama_models_with_expected_fields(self):
        with patch("hardware_detect._installed_models", return_value=["ollama/qwen2.5:7b"]), \
             patch("psutil.virtual_memory") as mem:
            mem.return_value.total = 32 * (1024 ** 3)
            catalog = hardware_detect.get_model_catalog()

        self.assertEqual(catalog["ram_gb"], 32.0)
        self.assertGreater(len(catalog["models"]), 0)

        tags = {m["tag"] for m in catalog["models"]}
        self.assertIn("qwen2.5:7b", tags)
        self.assertNotIn("gpt-4o", tags)  # non-ollama models excluded

        qwen = next(m for m in catalog["models"] if m["tag"] == "qwen2.5:7b")
        self.assertTrue(qwen["installed"])
        self.assertEqual(qwen["model_id"], "ollama/qwen2.5:7b")
        self.assertIn(qwen["tier"], {"light", "medium", "heavy", "very_heavy"})

        llama70b = next(m for m in catalog["models"] if m["tag"] == "llama3.1:70b")
        self.assertFalse(llama70b["installed"])
        self.assertEqual(llama70b["tier"], "very_heavy")

    def test_catalog_sorted_by_size_ascending(self):
        with patch("hardware_detect._installed_models", return_value=[]), \
             patch("psutil.virtual_memory") as mem:
            mem.return_value.total = 16 * (1024 ** 3)
            catalog = hardware_detect.get_model_catalog()

        sizes = [m["size_gb"] for m in catalog["models"]]
        self.assertEqual(sizes, sorted(sizes))

    def test_recommended_flag_matches_hardware_suggestion(self):
        with patch("hardware_detect._installed_models", return_value=["ollama/qwen2.5:7b", "ollama/llama3.1:8b", "ollama/gemma2:9b"]), \
             patch("psutil.virtual_memory") as mem:
            mem.return_value.total = 32 * (1024 ** 3)
            catalog = hardware_detect.get_model_catalog()
            suggestion = hardware_detect.get_hardware_suggestion()

        recommended_tags = {m["tag"] for m in catalog["models"] if m["recommended"]}
        expected_tags = {seat["model"].split("/", 1)[1] for seat in suggestion["config"].values()}
        self.assertEqual(recommended_tags, expected_tags)

    def test_small_ram_machine_flags_large_models_as_not_fitting(self):
        with patch("hardware_detect._installed_models", return_value=[]), \
             patch("psutil.virtual_memory") as mem:
            mem.return_value.total = 8 * (1024 ** 3)
            catalog = hardware_detect.get_model_catalog()

        llama70b = next(m for m in catalog["models"] if m["tag"] == "llama3.1:70b")
        self.assertFalse(llama70b["fits_now"])

    def test_mixed_strategy_uses_small_analysts_and_largest_fitting_chairman(self):
        installed = [
            "ollama/qwen2.5:14b",
            "ollama/qwen2.5:3b",
            "ollama/llama3.2:3b",
            "ollama/gemma2:2b",
        ]
        with patch("psutil.virtual_memory") as mem:
            mem.return_value.total = 16 * (1024 ** 3)
            suggestion = hardware_detect.get_hardware_suggestion(installed, strategy="mixed")

        self.assertEqual(suggestion["strategy"], "mixed")
        self.assertTrue(suggestion["requires_phase_model_swap"])
        self.assertEqual(suggestion["config"]["chairman"]["model"], "ollama/qwen2.5:14b")
        for seat_id in ("architect", "security", "perf"):
            self.assertLess(hardware_detect._get_model_gb(suggestion["config"][seat_id]["model"]), hardware_detect._STRONG_GB)


if __name__ == "__main__":
    unittest.main()
