import unittest

from llm_council.run_store import RunStore


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = RunStore(":memory:")

    def test_run_lifecycle_and_phase_outputs(self):
        roster = {"architect": {"model": "ollama/qwen2.5:7b", "persona": "review"}}

        self.store.begin_run("run-1", "topic", roster, deep_debate=True)
        self.store.record_phase_output("run-1", 1, "architect", "analysis", tokens_in=10, tokens_out=5, latency_ms=123)
        self.store.record_phase_output("run-1", 2, "architect", "review")
        self.store.record_phase_output(
            "run-1",
            3,
            "chairman",
            "verdict",
            finish_reason="json",
            attempt_number=2,
        )
        self.store.finish_run("run-1", "completed")

        run = self.store.get_run("run-1")
        self.assertEqual(run["run_id"], "run-1")
        self.assertEqual(run["status"], "completed")
        self.assertIsNone(run["smart_phase_score"])
        self.assertEqual(len(run["phases"]), 3)
        self.assertTrue(all(phase["output"] for phase in run["phases"]))
        chairman_phase = next(phase for phase in run["phases"] if phase["phase"] == 3)
        self.assertEqual(chairman_phase["member_id"], "chairman")
        self.assertEqual(chairman_phase["finish_reason"], "json")
        self.assertEqual(chairman_phase["attempt_number"], 2)

        listed = self.store.list_runs()
        self.assertEqual(listed[0]["run_id"], "run-1")
        self.assertIsNotNone(listed[0]["started_at"])

    def test_feedback_and_delete(self):
        self.store.begin_run("run-2", "topic", {}, deep_debate=False)
        self.store.record_feedback("run-2", 0, "up", "useful")

        run = self.store.get_run("run-2")
        self.assertEqual(run["feedback"][0]["rating"], "up")

        self.assertEqual(self.store.delete_run("run-2"), True)
        self.assertEqual(self.store.get_run("run-2"), {})

    def test_idempotent_writes(self):
        self.store.begin_run("run-3", "topic", {}, deep_debate=False)
        self.store.begin_run("run-3", "topic updated", {}, deep_debate=True)
        self.store.record_phase_output("run-3", 1, "architect", "first")
        self.store.record_phase_output("run-3", 1, "architect", "updated")

        run = self.store.get_run("run-3")
        self.assertEqual(run["topic"], "topic updated")
        self.assertEqual(len(run["phases"]), 1)
        self.assertEqual(run["phases"][0]["output"], "updated")

    def test_update_smart_phase_score(self):
        self.store.begin_run("run-4", "topic", {}, deep_debate=True)
        self.store.update_smart_phase_score("run-4", 0.91)

        run = self.store.get_run("run-4")
        self.assertEqual(run["smart_phase_score"], 0.91)

    def test_schema_migrations_are_recorded(self):
        with self.store._connection() as conn:
            rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()

        self.assertEqual(
            [row["version"] for row in rows],
            [
                "001_smart_phase_score",
                "002_phase_output_observability",
                "003_quality_metrics",
                "004_confidence_metrics",
            ],
        )

    def test_quality_metrics_lifecycle(self):
        self.store.begin_run("quality-run", "topic", {}, deep_debate=True)
        self.store.update_quality_metrics("quality-run", "json", 0.25, 0.8)
        self.store.finish_run("quality-run", "completed")

        run = self.store.get_run("quality-run")
        quality = self.store.list_quality_metrics()

        self.assertEqual(run["parse_tier"], "json")
        self.assertEqual(run["phase1_divergence"], 0.25)
        self.assertEqual(run["specificity_score"], 0.8)
        self.assertEqual(quality["runs"][0]["run_id"], "quality-run")
        self.assertEqual(quality["summary"]["parse_tiers"], {"json": 1})

    def test_confidence_metrics_lifecycle(self):
        self.store.begin_run("conf-run", "topic", {}, deep_debate=True)
        self.store.update_confidence_metrics(
            "conf-run", 0.8, 72, '{"stances": {"a": {"verdict": "PROCEED"}}, "agreement": "unanimous"}'
        )
        self.store.finish_run("conf-run", "completed")

        run = self.store.get_run("conf-run")
        self.assertEqual(run["grounding_ratio"], 0.8)
        self.assertEqual(run["council_confidence"], 72)
        self.assertEqual(run["stance_summary"]["agreement"], "unanimous")

        quality = self.store.list_quality_metrics()
        self.assertEqual(quality["summary"]["avg_grounding_ratio"], 0.8)
        self.assertEqual(quality["summary"]["avg_council_confidence"], 72)


if __name__ == "__main__":
    unittest.main()
