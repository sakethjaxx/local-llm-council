import unittest
from unittest.mock import patch

import numpy as np

import smart_phase


class FakeEmbedder:
    def encode(self, texts):
        return np.array([[1.0, 0.0], [0.9, 0.1]])


class KeywordEmbedder:
    """Maps any chunk containing a keyword to a fixed orthogonal unit vector, so
    tests can control pairwise similarity deterministically."""

    VECTORS = {"alpha": [1.0, 0.0, 0.0], "beta": [0.0, 1.0, 0.0]}

    def encode(self, texts):
        out = []
        for text in texts:
            vec = [0.0, 0.0, 1.0]
            for keyword, mapped in self.VECTORS.items():
                if keyword in text:
                    vec = mapped
            out.append(vec)
        return np.array(out, dtype=float)


class SmartPhaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_should_skip_returns_bool_and_score(self):
        with patch.object(smart_phase, "get_embedder", return_value=FakeEmbedder()):
            result = await smart_phase.should_skip({"a": "same", "b": "similar"})

        self.assertIsInstance(result, tuple)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], float)

    async def test_unanimous_analyses_skip(self):
        analyses = {"a": "alpha one", "b": "alpha two", "c": "alpha three"}
        with patch.object(smart_phase, "get_embedder", return_value=KeywordEmbedder()):
            skip, score = await smart_phase.should_skip(analyses)

        self.assertTrue(skip)
        self.assertGreater(score, smart_phase.SKIP_THRESHOLD)

    async def test_single_dissenter_blocks_skip_via_min_pairwise(self):
        # Two members agree strongly, one is orthogonal — the mean is high but the
        # MIN pairwise is 0, so the debate must NOT be skipped.
        analyses = {"a": "alpha one", "b": "alpha two", "c": "beta three"}
        with patch.object(smart_phase, "get_embedder", return_value=KeywordEmbedder()):
            skip, score = await smart_phase.should_skip(analyses)

        self.assertFalse(skip)
        self.assertLessEqual(score, smart_phase.SKIP_THRESHOLD)

    async def test_explicit_disagreement_forces_debate(self):
        # All embed identically, but an explicit phrase vetoes the skip.
        analyses = {"a": "alpha one", "b": "alpha two, but I strongly disagree", "c": "alpha three"}
        with patch.object(smart_phase, "get_embedder", return_value=KeywordEmbedder()):
            skip, _ = await smart_phase.should_skip(analyses)

        self.assertFalse(skip)

    async def test_conflicting_positions_force_debate_even_when_prose_is_similar(self):
        analyses = {
            "a": "alpha one\n## POSITION\n- SHIP because evidence is sufficient",
            "b": "alpha two\n## POSITION\n- BLOCK because evidence is insufficient",
            "c": "alpha three\n## POSITION\n- SHIP with safeguards",
        }
        with patch.object(smart_phase, "get_embedder", return_value=KeywordEmbedder()):
            skip, score = await smart_phase.should_skip(analyses)

        self.assertGreater(score, smart_phase.SKIP_THRESHOLD)
        self.assertFalse(skip)

    async def test_extended_disagreement_phrases_force_debate(self):
        phrases = ["cannot ship", "unacceptable risk", "not ready for production", "flawed assumption"]
        for phrase in phrases:
            analyses = {
                "a": "alpha one",
                "b": f"alpha two with {phrase} noted",
                "c": "alpha three",
            }
            with patch.object(smart_phase, "get_embedder", return_value=KeywordEmbedder()):
                skip, _ = await smart_phase.should_skip(analyses)
            self.assertFalse(skip, f"Phrase '{phrase}' should have forced debate")

    def test_strip_template_headers(self):
        text = "## STRENGTHS\nGood points\n## RISKS\nSome risk\n## RECOMMENDATIONS\nFix it\n## POSITION\n- SHIP"
        stripped = smart_phase._strip_template_headers(text)
        self.assertNotIn("## STRENGTHS", stripped)
        self.assertNotIn("## RISKS", stripped)
        self.assertIn("Good points", stripped)
        self.assertIn("Some risk", stripped)


if __name__ == "__main__":
    unittest.main()
