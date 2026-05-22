import os
import tempfile
import unittest

from run_store import RunStore


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "runs.db")
        self.store = RunStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

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


if __name__ == "__main__":
    unittest.main()
