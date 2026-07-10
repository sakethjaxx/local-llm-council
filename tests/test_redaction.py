import json
import unittest

from llm_council.provider_caps import redact_config
from llm_council.run_store import RunStore


class RedactionTests(unittest.TestCase):
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
        store = RunStore(":memory:")
        store.begin_run(
            "redacted-run",
            "topic",
            {"architect": {"model": "openai/gpt-4o-mini", "api_key": "sk-test123"}},
            deep_debate=False,
        )

        with store._connection() as conn:
            raw = conn.execute("SELECT roster_json FROM runs WHERE run_id = ?", ("redacted-run",)).fetchone()[0]
        roster = json.loads(raw)

        self.assertNotIn("api_key", roster["architect"])
        self.assertEqual(roster["architect"]["model"], "openai/gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
