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

    def test_installed_tag_outside_registry_is_listed_with_its_real_size(self):
        with patch("hardware_detect._installed_models", return_value=["ollama/llama3.2:latest"]), \
             patch("ollama_manager.installed_model_sizes_gb", return_value={"llama3.2:latest": 2.019}), \
             patch("psutil.virtual_memory") as mem:
            mem.return_value.total = 16 * (1024 ** 3)
            catalog = hardware_detect.get_model_catalog()

        entry = next(m for m in catalog["models"] if m["tag"] == "llama3.2:latest")
        self.assertTrue(entry["installed"])
        self.assertEqual(entry["model_id"], "ollama/llama3.2:latest")
        self.assertEqual(entry["size_gb"], 2.0)
        self.assertEqual([m["size_gb"] for m in catalog["models"]], sorted(m["size_gb"] for m in catalog["models"]))

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


class ComputeAwareRosterTests(unittest.TestCase):
    INSTALLED = ["ollama/qwen2.5:7b", "ollama/llama3.1:8b", "ollama/qwen2.5:3b", "ollama/gemma2:2b"]

    def _suggest(self, vram_gb, installed=INSTALLED, strategy="auto"):
        with patch("hardware_detect._gpu_vram_gb", return_value=vram_gb), patch("psutil.virtual_memory") as mem:
            mem.return_value.total = 24 * (1024 ** 3)
            return hardware_detect.get_hardware_suggestion(installed, strategy=strategy)

    def test_cpu_only_auto_shares_one_small_model_across_all_seats(self):
        suggestion = self._suggest(None)
        self.assertEqual(suggestion["compute"], "cpu")
        self.assertEqual({seat["model"] for seat in suggestion["config"].values()}, {"ollama/qwen2.5:3b"})
        self.assertIn("CPU", suggestion["reason"])

    def test_gpu_too_small_for_7b_counts_as_cpu(self):
        self.assertEqual(self._suggest(2.0)["compute"], "cpu")

    def test_capable_gpu_keeps_the_diverse_7b_roster(self):
        suggestion = self._suggest(12.0)
        self.assertEqual(suggestion["compute"], "gpu")
        self.assertEqual(suggestion["strategy"], "diverse")
        self.assertIn("ollama/qwen2.5:7b", {seat["model"] for seat in suggestion["config"].values()})

    def test_explicit_strategy_is_honored_on_cpu(self):
        self.assertEqual(self._suggest(None, strategy="diverse")["strategy"], "diverse")

    def test_cpu_only_without_small_models_suggests_pulling_one(self):
        suggestion = self._suggest(None, installed=["ollama/qwen2.5:7b"])
        self.assertEqual(suggestion["config"]["chairman"]["model"], "ollama/qwen2.5:7b")
        self.assertIn("ollama pull qwen2.5:3b", suggestion["reason"])

    def test_vram_override_env(self):
        for value, expected in (("0", None), ("8", 8.0), ("junk", "probe")):
            hardware_detect._gpu_vram_gb.cache_clear()
            with patch.dict("os.environ", {"COUNCIL_GPU_VRAM_GB": value}), \
                    patch("hardware_detect.shutil.which", return_value=None), \
                    patch("hardware_detect.sys.platform", "linux"):
                self.assertEqual(hardware_detect._gpu_vram_gb(), None if expected == "probe" else expected)
        hardware_detect._gpu_vram_gb.cache_clear()


if __name__ == "__main__":
    unittest.main()
