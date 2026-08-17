import unittest

import orchestrator
from ollama_manager import _iter_ollama_models


class MalformedRosterTests(unittest.TestCase):
    """A bad roster shape used to raise AttributeError inside the SSE generator,
    killing the stream before any event was written — the UI just hung."""

    def test_list_roster_does_not_raise(self):
        self.assertEqual(list(_iter_ollama_models([{"model": "ollama/x"}])), [])

    def test_non_dict_seats_are_skipped(self):
        config = {"a": "not-a-dict", "b": {"model": "ollama/llama3.2:3b"}}
        self.assertEqual(list(_iter_ollama_models(config)), ["llama3.2:3b"])

    def test_seat_without_model_is_skipped(self):
        config = {"a": {}, "b": {"model": None}, "c": {"model": "ollama/llama3.2:3b"}}
        self.assertEqual(list(_iter_ollama_models(config)), ["llama3.2:3b"])


class TemperatureTests(unittest.TestCase):
    def test_chairman_phase_runs_colder_than_analysis(self):
        self.assertLess(
            orchestrator._temperature_for({}, 3),
            orchestrator._temperature_for({}, 1),
        )

    def test_per_seat_override_wins(self):
        self.assertEqual(orchestrator._temperature_for({"temperature": 0.9}, 1), 0.9)

    def test_override_is_clamped(self):
        self.assertEqual(orchestrator._temperature_for({"temperature": 99}, 1), 2.0)
        self.assertEqual(orchestrator._temperature_for({"temperature": -5}, 1), 0.0)

    def test_garbage_override_falls_back_to_default(self):
        self.assertEqual(
            orchestrator._temperature_for({"temperature": "hot"}, 1),
            orchestrator.ANALYSIS_TEMPERATURE,
        )


class ConcurrencyDefaultTests(unittest.TestCase):
    def test_parallelism_default_is_low_enough_for_a_shared_local_model(self):
        # Hardware tiers put every seat on one resident model; a high fan-out
        # multiplies its KV cache and thrashes the memory budget.
        import importlib
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COUNCIL_MAX_PARALLEL_MEMBERS", None)
            reloaded = importlib.reload(orchestrator)
            try:
                self.assertLessEqual(reloaded.MAX_PARALLEL_MEMBERS, 2)
            finally:
                importlib.reload(orchestrator)

    def test_parallelism_is_always_at_least_one(self):
        self.assertGreaterEqual(orchestrator.MAX_PARALLEL_MEMBERS, 1)


if __name__ == "__main__":
    unittest.main()
