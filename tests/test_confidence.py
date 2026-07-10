import unittest

from llm_council.confidence import (
    CLONE_CONFIDENCE_CAP,
    agreement_state,
    council_confidence,
    enforce_grounding,
    roster_diversity,
)


class EnforceGroundingTests(unittest.TestCase):
    LABELS = ["Lead Architect", "Security Auditor", "Performance Eng"]

    def test_grounded_points_pass_through(self):
        result = {
            "verdict": "ship",
            "consensus": ["(Lead Architect, Security Auditor) Both endorse the design"],
            "disputes": ["(Security Auditor vs Performance Eng) Cache TTL"],
        }
        enforced, report = enforce_grounding(result, self.LABELS)
        self.assertFalse(report["enforced"])
        self.assertEqual(report["removed"], 0)
        self.assertEqual(report["ratio"], 1.0)
        self.assertEqual(enforced["consensus"], result["consensus"])

    def test_ungrounded_points_are_stripped_below_threshold(self):
        result = {
            "verdict": "ship",
            "consensus": [
                "(Lead Architect) Solid layering",
                "Everyone loves the new API",  # names nobody
                "The team agrees testing is good",  # names nobody
            ],
            "disputes": ["General disagreement about style"],  # names nobody
        }
        enforced, report = enforce_grounding(result, self.LABELS)
        self.assertTrue(report["enforced"])
        self.assertEqual(report["removed"], 3)
        self.assertEqual(enforced["consensus"], ["(Lead Architect) Solid layering"])
        self.assertEqual(enforced["disputes"], [])

    def test_above_threshold_reports_but_does_not_strip(self):
        result = {
            "verdict": "ship",
            "consensus": [
                "(Lead Architect) point one",
                "(Security Auditor) point two",
                "unattributed shorthand",
            ],
            "disputes": [],
        }
        enforced, report = enforce_grounding(result, self.LABELS)
        self.assertFalse(report["enforced"])
        self.assertEqual(len(enforced["consensus"]), 3)
        self.assertAlmostEqual(report["ratio"], 0.667, places=3)

    def test_no_points_returns_none_ratio(self):
        enforced, report = enforce_grounding({"verdict": "x", "consensus": [], "disputes": []}, self.LABELS)
        self.assertIsNone(report["ratio"])
        self.assertFalse(report["enforced"])


class AgreementStateTests(unittest.TestCase):
    STANCES_AGREE = {
        "a": {"verdict": "PROCEED", "confidence": 8, "summary": ""},
        "b": {"verdict": "PROCEED", "confidence": 7, "summary": ""},
    }
    STANCES_SPLIT = {
        "a": {"verdict": "PROCEED", "confidence": 8, "summary": ""},
        "b": {"verdict": "HOLD", "confidence": 7, "summary": ""},
    }

    def test_fast_mode_is_not_deliberated(self):
        self.assertEqual(agreement_state(False, self.STANCES_AGREE, 2, False, None), "not_deliberated")

    def test_unanimous(self):
        self.assertEqual(agreement_state(True, self.STANCES_AGREE, 2, False, None), "unanimous")

    def test_split_converged(self):
        converged = {
            "a": {"verdict": "HOLD", "confidence": 6, "summary": ""},
            "b": {"verdict": "HOLD", "confidence": 7, "summary": ""},
        }
        self.assertEqual(agreement_state(True, converged, 2, True, True), "split_converged")

    def test_split_unresolved(self):
        self.assertEqual(agreement_state(True, self.STANCES_SPLIT, 2, True, False), "split_unresolved")

    def test_missing_stances_are_unknown(self):
        self.assertEqual(agreement_state(True, {"a": self.STANCES_AGREE["a"]}, 3, False, None), "unknown")


class CouncilConfidenceTests(unittest.TestCase):
    def test_clones_agreeing_score_below_diverse_debate(self):
        clones = council_confidence(
            member_models=["ollama/x", "ollama/x", "ollama/x"],
            agreement="unanimous",
            grounding_ratio=1.0,
            parse_tier="json",
        )
        diverse = council_confidence(
            member_models=["ollama/x", "ollama/y"],
            agreement="split_converged",
            grounding_ratio=1.0,
            parse_tier="json",
        )
        self.assertTrue(clones["clone_capped"])
        self.assertLessEqual(clones["score"], CLONE_CONFIDENCE_CAP)
        self.assertGreater(diverse["score"], clones["score"])

    def test_reused_model_with_distinct_personas_is_discounted_not_capped(self):
        reused = council_confidence(
            member_models=["ollama/x", "ollama/x", "ollama/x"],
            member_configs=[
                {"label": "A", "model": "ollama/x", "persona": "Review architecture."},
                {"label": "B", "model": "ollama/x", "persona": "Review security."},
                {"label": "C", "model": "ollama/x", "persona": "Review performance."},
            ],
            agreement="unanimous",
            grounding_ratio=1.0,
            parse_tier="json",
        )

        self.assertFalse(reused["clone_capped"])
        self.assertEqual(reused["diversity"]["distinct_behaviors"], 3)
        self.assertIn("one base model reused", reused["explanation"])

    def test_labels_alone_do_not_make_clone_seats_diverse(self):
        diversity = roster_diversity(
            ["ollama/x", "ollama/x"],
            [
                {"label": "A", "model": "ollama/x", "persona": "same"},
                {"label": "B", "model": "ollama/x", "persona": "same"},
            ],
        )

        self.assertTrue(diversity["exact_clones"])

    def test_diverse_unanimous_grounded_scores_high(self):
        result = council_confidence(
            member_models=["ollama/a", "ollama/b", "ollama/c"],
            agreement="unanimous",
            grounding_ratio=1.0,
            parse_tier="json",
        )
        self.assertGreaterEqual(result["score"], 90)
        self.assertFalse(result["clone_capped"])

    def test_parse_failure_drags_score_down(self):
        good = council_confidence(["a", "b", "c"], "unanimous", 1.0, "json")
        bad = council_confidence(["a", "b", "c"], "unanimous", 1.0, "parse_failed")
        self.assertLess(bad["score"], good["score"])

    def test_low_grounding_noted_in_explanation(self):
        result = council_confidence(["a", "b"], "unanimous", 0.25, "json")
        self.assertIn("25%", result["explanation"])

    def test_score_bounds(self):
        worst = council_confidence(["a", "a"], "split_unresolved", 0.0, "parse_failed")
        self.assertGreaterEqual(worst["score"], 0)
        self.assertLessEqual(worst["score"], 100)


if __name__ == "__main__":
    unittest.main()
