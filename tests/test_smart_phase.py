import unittest
from unittest.mock import patch

import numpy as np

import smart_phase


class FakeEmbedder:
    def encode(self, texts):
        # Near-identical embeddings — high cosine similarity for any input,
        # so these tests prove the gate ignores text similarity for its decision.
        return np.array([[1.0, 0.0]] * len(texts)) + np.random.default_rng(0).normal(0, 0.01, (len(texts), 2))


def _patched_embedder():
    return patch.object(smart_phase, "get_embedder", return_value=FakeEmbedder())


class StanceExtractionTests(unittest.TestCase):
    def test_extracts_full_stance_line(self):
        stance = smart_phase.extract_stance(
            "Long analysis here.\nSTANCE: PROCEED | CONFIDENCE: 8 | Ship it with monitoring."
        )
        self.assertEqual(stance["verdict"], "PROCEED")
        self.assertEqual(stance["confidence"], 8)
        self.assertEqual(stance["summary"], "Ship it with monitoring.")

    def test_extracts_markdown_wrapped_stance(self):
        stance = smart_phase.extract_stance("**STANCE:** HOLD | **CONFIDENCE:** 9 | Too risky.")
        self.assertEqual(stance["verdict"], "HOLD")
        self.assertEqual(stance["confidence"], 9)

    def test_last_stance_line_wins(self):
        stance = smart_phase.extract_stance(
            "STANCE: PROCEED | CONFIDENCE: 5 | early guess\nMore analysis...\nSTANCE: HOLD | CONFIDENCE: 7 | changed my mind"
        )
        self.assertEqual(stance["verdict"], "HOLD")

    def test_returns_none_without_stance(self):
        self.assertIsNone(smart_phase.extract_stance("No stance anywhere in this text."))
        self.assertIsNone(smart_phase.extract_stance(""))


class SmartPhaseGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_opposite_stances_do_not_skip_despite_similar_text(self):
        # Same vocabulary, opposite conclusions — the old cosine gate got this wrong.
        analyses = {
            "a": "The migration is well planned with clear risks.\nSTANCE: PROCEED | CONFIDENCE: 8 | Ship it.",
            "b": "The migration is well planned with clear risks.\nSTANCE: HOLD | CONFIDENCE: 8 | Do not ship.",
        }
        with _patched_embedder():
            skip, score, info = await smart_phase.should_skip(analyses)

        self.assertFalse(skip)
        self.assertTrue(info["split"])
        self.assertIn("split", info["reason"].lower())

    async def test_unanimous_stances_skip_even_with_risk_wording(self):
        # "risk", "but", "concern" everywhere — the old keyword heuristic force-ran debate on this.
        analyses = {
            "a": "There are risks and concerns, but manageable.\nSTANCE: PROCEED | CONFIDENCE: 8 | Go.",
            "b": "Some risk, however mitigations exist.\nSTANCE: PROCEED | CONFIDENCE: 7 | Go.",
            "c": "Concerns noted but acceptable.\nSTANCE: PROCEED | CONFIDENCE: 9 | Go.",
        }
        with _patched_embedder():
            skip, score, info = await smart_phase.should_skip(analyses)

        self.assertTrue(skip)
        self.assertFalse(info["split"])
        self.assertIn("PROCEED", info["reason"])

    async def test_missing_stance_runs_debate_to_be_safe(self):
        analyses = {
            "a": "Analysis with no stance line at all.",
            "b": "STANCE: PROCEED | CONFIDENCE: 8 | Go.",
        }
        with _patched_embedder():
            skip, score, info = await smart_phase.should_skip(analyses)

        self.assertFalse(skip)
        self.assertFalse(info["split"])
        self.assertIn("a", info["reason"])

    async def test_mixed_stance_runs_debate(self):
        analyses = {
            "a": "STANCE: MIXED | CONFIDENCE: 5 | Torn on this.",
            "b": "STANCE: PROCEED | CONFIDENCE: 8 | Go.",
        }
        with _patched_embedder():
            skip, score, info = await smart_phase.should_skip(analyses)

        self.assertFalse(skip)

    async def test_single_member_never_skips(self):
        skip, score, info = await smart_phase.should_skip({"a": "STANCE: PROCEED | CONFIDENCE: 9 | Go."})
        self.assertFalse(skip)
        self.assertEqual(score, 0.0)

    async def test_embedder_failure_does_not_break_gate(self):
        analyses = {
            "a": "STANCE: PROCEED | CONFIDENCE: 8 | Go.",
            "b": "STANCE: PROCEED | CONFIDENCE: 7 | Go.",
        }
        with patch.object(smart_phase, "get_embedder", side_effect=RuntimeError("no model")):
            skip, score, info = await smart_phase.should_skip(analyses)

        self.assertTrue(skip)
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
