"""Secrets must not leave the process through any boundary: streams, chat, errors,
logs, feedback, metrics, memory, skills or exports."""

import json
import logging
import os
import random
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import numpy as np

import logging_utils
import routes_stream
from memory_store import SQLiteMemory
from metrics_store import MetricsStore
from provider_caps import StreamScrubber, redact_config
from run_store import RunStore
from skill_registry import SkillRegistry

SECRETS = [
    "sk-ant-api03-" + "Ab3_" * 8,
    "sk-proj-" + "x9Y" * 8,
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "ghp_" + "a1B2" * 6,
    "xoxb-" + "1234-5678-abcdef",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
]
BEARER = "Bearer abcdefghijklmnopqrstuvwxyz012345"


def stream_through(text: str, cuts: list[int]) -> str:
    scrubber = StreamScrubber()
    pieces, start = [], 0
    for cut in sorted(cuts) + [len(text)]:
        pieces.append(scrubber.feed(text[start:cut]))
        start = cut
    return "".join(pieces) + scrubber.flush()


class StreamScrubberTests(unittest.TestCase):
    def test_secret_split_at_every_position_is_caught(self):
        for secret in SECRETS + [BEARER]:
            text = f"the key is {secret}, keep it safe"
            for i in range(len(text) + 1):
                out = stream_through(text, [i])
                self.assertNotIn(secret[-12:], out, (secret, i))
                self.assertTrue(out.startswith("the key is ") and out.endswith(", keep it safe"), out)

    def test_secret_split_into_many_chunks_is_caught(self):
        rng = random.Random(7)
        for secret in SECRETS:
            text = f"echo {secret}\n"
            for _ in range(50):
                cuts = rng.sample(range(1, len(text)), k=min(8, len(text) - 1))
                self.assertNotIn(secret[-12:], stream_through(text, cuts))

    def test_plain_text_passes_through_unchanged(self):
        rng = random.Random(3)
        text = "## Findings\n- Use WAL mode (2 writers max).\n- Cache keys like `user:42`.\n" * 5
        for _ in range(30):
            cuts = rng.sample(range(1, len(text)), k=12)
            self.assertEqual(stream_through(text, cuts), text)


class RedactConfigTests(unittest.TestCase):
    def test_usage_counters_survive_and_credentials_do_not(self):
        redacted = redact_config({
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "tokens_in": 3, "tokens_out": 4, "max_tokens": 800, "token_budget_profile": "economy",
            "access_token": "x" * 20, "refreshToken": "y", "OPENAI_API_KEY": "z", "password": "p",
            "note": f"pasted {SECRETS[0]}",
        })
        self.assertEqual(redacted["usage"], {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        self.assertEqual((redacted["tokens_in"], redacted["tokens_out"], redacted["max_tokens"]), (3, 4, 800))
        self.assertEqual(redacted["token_budget_profile"], "economy")
        for dropped in ("access_token", "refreshToken", "OPENAI_API_KEY", "password"):
            self.assertNotIn(dropped, redacted)
        self.assertEqual(redacted["note"], "pasted [REDACTED_SECRET]")


class SseBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_member_tokens_and_errors_are_scrubbed(self):
        secret = SECRETS[0]

        class FakeOrchestrator:
            async def run(self, *args, **kwargs):
                yield {"type": "member_thinking", "member": "architect", "phase": 1, "meta": {}}
                for i in range(0, len(secret), 5):
                    yield {"type": "member_token", "member": "architect", "chunk": ("key " if i == 0 else "") + secret[i:i + 5]}
                yield {"type": "member_done", "member": "architect", "full_text": f"key {secret}"}
                raise RuntimeError(f"provider rejected {secret}")

        ready = {"ready": True, "missing": [], "required": [], "pulled": [], "auto_pull_enabled": False}
        metrics = MetricsStore()
        attrs = {"CouncilOrchestrator": FakeOrchestrator, "ensure_models_for_config": lambda *a: ready,
                 "metrics_store": metrics}
        with patch("routes_stream._main_attr", side_effect=lambda name, default: attrs.get(name, default)):
            frames = [f async for f in routes_stream.stream_council_lifecycle(
                "topic", [], {"architect": {"model": "ollama/x"}, "chairman": {"model": "ollama/x"}},
                None, "economy", False, False, {}, {"type": "shutdown"})]
        events = [json.loads(frame[len("data: "):]) for frame in frames]
        streamed = "".join(e.get("chunk", "") for e in events if e["type"] == "member_token")
        self.assertEqual(streamed, "key [REDACTED_SECRET]")
        self.assertNotIn(secret[-12:], "".join(frames))
        self.assertIn("[REDACTED_SECRET]", next(e for e in events if e["type"] == "error")["message"])
        self.assertNotIn(secret[-12:], json.dumps(metrics.list_runs()))

    async def test_chat_stream_scrubs_split_secret(self):
        secret = SECRETS[1]

        class FakeOrchestrator:
            async def chat_with_member(self, *args, **kwargs):
                for i in range(0, len(secret), 3):
                    yield secret[i:i + 3]
                yield " done"

        request = types.SimpleNamespace(member_id="architect", messages=[], council_config=None)
        with patch("routes_stream._main_attr", side_effect=lambda name, default: FakeOrchestrator if name == "CouncilOrchestrator" else default):
            frames = [f async for f in routes_stream.stream_chat_lifecycle(request, {}, "economy", "run-1", {})]
        text = "".join(json.loads(f[6:]).get("chunk", "") for f in frames)
        self.assertEqual(text, "[REDACTED_SECRET] done")


class LogBoundaryTests(unittest.TestCase):
    def _record(self):
        try:
            raise ValueError(f"upstream said {SECRETS[2]}")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord("council", logging.ERROR, __file__, 1, "call failed for %s", (SECRETS[3],), exc_info)
        record.error = f"key={SECRETS[4]}"
        return record

    def test_json_and_text_log_lines_are_scrubbed(self):
        for formatter in (logging_utils.JsonFormatter(), logging_utils.ScrubbingFormatter("%(message)s")):
            line = formatter.format(self._record())
            for secret in SECRETS[2:5]:
                self.assertNotIn(secret, line, type(formatter).__name__)
            self.assertIn("[REDACTED_SECRET]", line)


class StoreBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_errors_metrics_memory_and_skills_are_scrubbed(self):
        secret = SECRETS[0]
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(os.path.join(tmp, "runs.db"))
            store.begin_run("run-1", "topic", {}, False)
            store.record_feedback("run-1", 0, "thumbs_up", f"my key {secret}")
            store.finish_run("run-1", "failed", f"auth error for {secret}")
            self.assertNotIn(secret, json.dumps(store.get_run("run-1")))

        metrics = MetricsStore()
        run_id = metrics.start_run("council", {"note": secret})
        metrics.finish_run(run_id, status="failed", error=f"boom {secret}")
        self.assertNotIn(secret, json.dumps(metrics.list_runs()))

        class Embedder:
            def encode(self, text):
                return np.ones(4, dtype=np.float32)

        def completion(content):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])

        memory = SQLiteMemory(":memory:")
        triple = {"subject": "deploy", "predicate": "uses_key", "object": secret}

        async def memory_completion(*args, **kwargs):
            self.assertNotIn(secret, json.dumps(kwargs["messages"]))  # never sent to the extraction model
            return completion(json.dumps({"triples": [triple]}))

        with patch("memory_store.get_embedder", return_value=Embedder()), \
                patch("memory_store.litellm.acompletion", side_effect=memory_completion):
            await memory.extract_memory(f"topic {secret}", f"verdict {secret}", "test-model")
        stored = [t.object for t in memory.all_triples()]
        self.assertEqual(stored, ["[REDACTED_SECRET]"])

        registry = SkillRegistry(":memory:")
        replies = [json.dumps({"name": f"Rotate {secret}", "body": f"Never commit {secret}.", "domain": "security"}), "yes"]

        async def skill_completion(*args, **kwargs):
            return completion(replies.pop(0))

        with registry._connection() as conn:
            conn.execute("INSERT INTO runs (run_id, started_at, status, topic, roster_json, deep_debate) VALUES ('r', ?, 'completed', 't', '{}', 0)", (time.time(),))
            conn.execute("INSERT INTO phase_outputs (run_id, phase, member_id, output, attempt_number) VALUES ('r', 3, 'chairman', ?, 1)",
                         ('{"verdict":"review","risk_score":2,"action_items":[],"consensus":[],"disputes":[]}',))
            conn.execute("INSERT INTO run_feedback (run_id, action_index, rating, note, rated_at) VALUES ('r', 0, 'thumbs_up', '', ?)", (time.time(),))
        with patch("skill_registry.get_embedder", return_value=Embedder()), \
                patch("skill_registry.litellm.acompletion", side_effect=skill_completion):
            await registry.extract_skills("r", "topic", "test-model")
        with registry._connection() as conn:
            rows = [tuple(r) for r in conn.execute("SELECT name, body FROM skills").fetchall()]
        self.assertEqual(len(rows), 1)
        self.assertNotIn(secret, json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
