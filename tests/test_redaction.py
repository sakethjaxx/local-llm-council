import json
import os
import sqlite3
import tempfile
import unittest

from provider_caps import redact_config, scrub_secret_values
from run_store import RunStore


class RedactionTests(unittest.TestCase):
    def test_scrub_secret_values_masks_free_text_keys(self):
        text = "here is my key sk-abcdef_1234567890ABCDEF and AKIAIOSFODNN7EXAMPLE"
        scrubbed = scrub_secret_values(text)
        self.assertNotIn("sk-abcdefe_1234567890ABCDEF"[:20], scrubbed)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", scrubbed)
        self.assertIn("[REDACTED_SECRET]", scrubbed)

    def test_redact_config_scrubs_secrets_in_string_values(self):
        redacted = redact_config({"topic": "please review sk-abcdefghijklmnop12345 in prod"})
        self.assertNotIn("sk-abcdefghijklmnop12345", redacted["topic"])
        self.assertIn("[REDACTED_SECRET]", redacted["topic"])

    def test_pasted_secret_in_topic_and_output_not_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "runs.db")
            store = RunStore(db_path)
            store.begin_run(
                "secret-run",
                "audit my key sk-abcdefghijklmnop12345 please",
                {"architect": {"model": "ollama/qwen2.5:7b"}},
                deep_debate=False,
            )
            store.record_phase_output("secret-run", 1, "architect", "found AKIAIOSFODNN7EXAMPLE in code")

            with sqlite3.connect(db_path) as conn:
                topic = conn.execute("SELECT topic FROM runs WHERE run_id = ?", ("secret-run",)).fetchone()[0]
                output = conn.execute(
                    "SELECT output FROM phase_outputs WHERE run_id = ? AND phase = 1", ("secret-run",)
                ).fetchone()[0]

        self.assertNotIn("sk-abcdefghijklmnop12345", topic)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", output)
        self.assertIn("[REDACTED_SECRET]", topic)
    def test_redact_config_removes_sensitive_keys_recursively(self):
        redacted = redact_config(
            {
                "seat": {
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-test123",
                    "nested": {"secret_token": "token-value", "persona": "review"},
                },
                "OPENAI_API_KEY": "sk-env",
            }
        )

        self.assertNotIn("OPENAI_API_KEY", redacted)
        self.assertNotIn("api_key", redacted["seat"])
        self.assertNotIn("secret_token", redacted["seat"]["nested"])
        self.assertEqual(redacted["seat"]["nested"]["persona"], "review")

    def test_redact_config_handles_adversarial_shapes(self):
        redacted = redact_config(
            {
                "db": {"api_key": "secret", "port": 5432},
                "seats": [{"token": "abc", "label": "Architect"}],
                "mixed": {
                    "Api_Key_Value": "drop",
                    "refreshToken": "drop",
                    "clientSecret": "drop",
                    "safe": None,
                    "numbers": [1, None, {"count": 2}],
                },
                "non_sensitive": "preserve",
            }
        )

        self.assertNotIn("api_key", redacted["db"])
        self.assertEqual(redacted["db"]["port"], 5432)
        self.assertNotIn("token", redacted["seats"][0])
        self.assertEqual(redacted["seats"][0]["label"], "Architect")
        self.assertNotIn("Api_Key_Value", redacted["mixed"])
        self.assertNotIn("refreshToken", redacted["mixed"])
        self.assertNotIn("clientSecret", redacted["mixed"])
        self.assertIsNone(redacted["mixed"]["safe"])
        self.assertEqual(redacted["mixed"]["numbers"], [1, None, {"count": 2}])
        self.assertEqual(redacted["non_sensitive"], "preserve")

    def test_roster_round_trips_without_sensitive_key_in_db(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "runs.db")
            store = RunStore(db_path)
            store.begin_run(
                "redacted-run",
                "topic",
                {"architect": {"model": "openai/gpt-4o-mini", "api_key": "sk-test123"}},
                deep_debate=False,
            )

            with sqlite3.connect(db_path) as conn:
                raw = conn.execute("SELECT roster_json FROM runs WHERE run_id = ?", ("redacted-run",)).fetchone()[0]
            roster = json.loads(raw)

        self.assertNotIn("api_key", roster["architect"])
        self.assertEqual(roster["architect"]["model"], "openai/gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
