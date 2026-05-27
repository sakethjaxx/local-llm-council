import time
import types
import unittest
from unittest.mock import patch

import numpy as np

from memory_store import SQLiteMemory


class _FakeEmbedder:
    def encode(self, text: str):
        text = text.lower()
        vector = np.zeros(4, dtype=np.float32)
        if "microservices" in text or "service mesh" in text:
            vector[0] = 1.0
        if "caching" in text or "cache" in text:
            vector[1] = 1.0
        if "fresh" in text:
            vector[2] = 1.0
        if "stale" in text:
            vector[3] = 1.0
        if not vector.any():
            vector[0] = 0.1
        return vector


def _fake_completion_with_triples(triples):
    content = '{"triples": ' + str(triples).replace("'", '"') + "}"
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


class MemoryStoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = SQLiteMemory(":memory:")

    async def test_empty_db_returns_empty_context(self):
        with patch("memory_store.get_embedder", return_value=_FakeEmbedder()):
            context = await self.store.get_context("microservices design", "test-model")
        self.assertEqual(context, "")

    async def test_extract_and_retrieve(self):
        async def fake_acompletion(*args, **kwargs):
            return _fake_completion_with_triples(
                [{"subject": "microservices", "predicate": "decided_to_use", "object": "service mesh"}]
            )

        with patch("memory_store.get_embedder", return_value=_FakeEmbedder()), \
             patch("memory_store.litellm.acompletion", side_effect=fake_acompletion):
            await self.store.extract_memory("microservices design", "use service mesh", "test-model")
            context = await self.store.get_context("service mesh architecture", "test-model")

        self.assertIn("microservices -> decided_to_use -> service mesh", context)

    async def test_confidence_decay(self):
        now = time.time()
        vector = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        blob = vector.tobytes()
        with self.store._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_triples (
                    subject, predicate, object, confidence, reinforced,
                    contradicted, last_seen, created_at, embedding
                )
                VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?)
                """,
                ("stale-system", "recommended", "service mesh", 1.0, now - (365 * 86400), now, blob),
            )
            conn.execute(
                """
                INSERT INTO memory_triples (
                    subject, predicate, object, confidence, reinforced,
                    contradicted, last_seen, created_at, embedding
                )
                VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?)
                """,
                ("fresh-system", "recommended", "service mesh", 1.0, now, now, blob),
            )

        with patch("memory_store.get_embedder", return_value=_FakeEmbedder()):
            context = await self.store.get_context("service mesh architecture", "test-model")

        lines = [line for line in context.splitlines() if "->" in line]
        self.assertEqual(lines[0], "fresh-system -> recommended -> service mesh")
        self.assertEqual(lines[1], "stale-system -> recommended -> service mesh")

    async def test_reinforcement(self):
        responses = [
            [{"subject": "microservices", "predicate": "decided_to_use", "object": "service mesh"}],
            [{"subject": "platform", "predicate": "recommended", "object": "service mesh"}],
        ]

        async def fake_acompletion(*args, **kwargs):
            return _fake_completion_with_triples(responses.pop(0))

        with patch("memory_store.get_embedder", return_value=_FakeEmbedder()), \
             patch("memory_store.litellm.acompletion", side_effect=fake_acompletion):
            await self.store.extract_memory("microservices design", "use service mesh", "test-model")
            await self.store.extract_memory("service mesh architecture", "keep service mesh", "test-model")

        with self.store._connection() as conn:
            rows = conn.execute(
                "SELECT subject, predicate, object, reinforced FROM memory_triples"
            ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reinforced"], 2)

    async def test_graph_data_shape(self):
        with self.store._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_triples (
                    subject, predicate, object, confidence, reinforced,
                    contradicted, last_seen, created_at, embedding
                )
                VALUES (?, ?, ?, 1.0, 1, 0, ?, ?, ?)
                """,
                ("microservices", "uses", "service mesh", time.time(), time.time(), np.array([1, 0, 0, 0], dtype=np.float32).tobytes()),
            )

        graph = self.store.get_graph_data()
        self.assertIsInstance(graph, dict)
        self.assertIsInstance(graph["nodes"], list)
        self.assertIsInstance(graph["edges"], list)
        self.assertEqual(graph["edges"][0]["label"], "uses")

    async def test_quality_gate_skips_unrated_high_risk_run(self):
        async def fake_acompletion(*args, **kwargs):
            return _fake_completion_with_triples(
                [{"subject": "microservices", "predicate": "decided_to_use", "object": "service mesh"}]
            )

        with self.store._connection() as conn:
            now = time.time()
            conn.executescript(
                """
                CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    status TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    roster_json TEXT NOT NULL,
                    fingerprint_hash TEXT,
                    deep_debate INTEGER NOT NULL,
                    smart_phase_score REAL,
                    error TEXT
                );
                CREATE TABLE phase_outputs (
                    run_id TEXT NOT NULL,
                    phase INTEGER NOT NULL,
                    member_id TEXT NOT NULL,
                    output TEXT NOT NULL,
                    tokens_in INTEGER,
                    tokens_out INTEGER,
                    latency_ms INTEGER,
                    finish_reason TEXT,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (run_id, phase, member_id)
                );
                CREATE TABLE run_feedback (
                    run_id TEXT NOT NULL,
                    action_index INTEGER NOT NULL,
                    rating TEXT NOT NULL,
                    note TEXT,
                    rated_at REAL NOT NULL,
                    PRIMARY KEY (run_id, action_index)
                );
                """
            )
            conn.execute(
                """
                INSERT INTO runs (run_id, started_at, status, topic, roster_json, deep_debate)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("run-1", now, "completed", "topic", "{}", 0),
            )
            conn.execute(
                """
                INSERT INTO phase_outputs (run_id, phase, member_id, output, attempt_number)
                VALUES (?, 3, 'chairman', ?, 1)
                """,
                ("run-1", '{"verdict":"hold","risk_score":6,"action_items":[],"consensus":[],"disputes":[]}'),
            )

        with patch("memory_store.get_embedder", return_value=_FakeEmbedder()), \
             patch("memory_store.litellm.acompletion", side_effect=fake_acompletion):
            await self.store.extract_memory("microservices design", "use service mesh", "test-model", run_id="run-1")

        with self.store._connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM memory_triples").fetchone()[0]
        self.assertEqual(count, 0)

    def test_prune_memory_decays_and_deletes_low_confidence_triples(self):
        now = time.time()
        with self.store._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_triples (
                    subject, predicate, object, confidence, reinforced,
                    contradicted, last_seen, created_at, embedding
                )
                VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?)
                """,
                (
                    "old-low",
                    "recommended",
                    "service mesh",
                    0.26,
                    now - (365 * 86400),
                    now - (365 * 86400),
                    np.array([1, 0, 0, 0], dtype=np.float32).tobytes(),
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_triples (
                    subject, predicate, object, confidence, reinforced,
                    contradicted, last_seen, created_at, embedding
                )
                VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?)
                """,
                (
                    "fresh-high",
                    "recommended",
                    "service mesh",
                    1.0,
                    now,
                    now,
                    np.array([1, 0, 0, 0], dtype=np.float32).tobytes(),
                ),
            )

        result = self.store.prune_memory(force=True)

        with self.store._connection() as conn:
            rows = conn.execute("SELECT subject FROM memory_triples ORDER BY subject").fetchall()

        self.assertEqual(result["deleted"], 1)
        self.assertEqual([row["subject"] for row in rows], ["fresh-high"])


if __name__ == "__main__":
    unittest.main()
