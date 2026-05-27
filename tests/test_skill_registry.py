import asyncio
import time
import types
import unittest
from unittest.mock import patch

import numpy as np

from skill_registry import SkillRegistry


class _FakeEmbedder:
    def encode(self, text: str):
        text = text.lower()
        vector = np.zeros(4, dtype=np.float32)
        if any(term in text for term in ("security", "authentication", "auth", "vulnerability")):
            vector[0] = 1.0
        if any(term in text for term in ("performance", "latency", "cache")):
            vector[1] = 1.0
        if "architecture" in text:
            vector[2] = 1.0
        if "duplicate" in text or "dedup" in text:
            vector[3] = 1.0
        if not vector.any():
            vector[0] = 0.1
        return vector


def _fake_completion(content: str):
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


class SkillRegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = SkillRegistry(":memory:")

    def _insert_run_state(self, run_id: str, risk_score: int, rating: str | None = None):
        now = time.time()
        with self.registry._connection() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, started_at, status, topic, roster_json, deep_debate)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, now, "completed", "topic", "{}", 0),
            )
            conn.execute(
                """
                INSERT INTO phase_outputs (run_id, phase, member_id, output, attempt_number)
                VALUES (?, 3, 'chairman', ?, 1)
                """,
                (run_id, f'{{"verdict":"review","risk_score":{risk_score},"action_items":[],"consensus":[],"disputes":[]}}'),
            )
            if rating is not None:
                conn.execute(
                    """
                    INSERT INTO run_feedback (run_id, action_index, rating, note, rated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (run_id, 0, rating, "", now),
                )

    async def test_extraction_quality_gate_blocks_bad_run(self):
        self._insert_run_state("bad-run", risk_score=8)

        async def fake_acompletion(*args, **kwargs):
            return _fake_completion('{"name":"Security Review","body":"Inspect auth boundaries.","domain":"security"}')

        with patch("skill_registry.get_embedder", return_value=_FakeEmbedder()), \
             patch("skill_registry.litellm.acompletion", side_effect=fake_acompletion):
            await self.registry.extract_skills("bad-run", "authentication vulnerability", "test-model")

        with self.registry._connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        self.assertEqual(count, 0)

    async def test_extraction_quality_gate_passes_thumbs_up(self):
        self._insert_run_state("good-run", risk_score=8, rating="thumbs_up")
        calls = []
        responses = [
            '{"name":"Security Review","body":"Inspect authentication boundaries and privilege escalation paths.","domain":"security"}',
            "yes",
        ]

        async def fake_acompletion(*args, **kwargs):
            calls.append(kwargs)
            return _fake_completion(responses.pop(0))

        with patch("skill_registry.get_embedder", return_value=_FakeEmbedder()), \
             patch("skill_registry.litellm.acompletion", side_effect=fake_acompletion):
            await self.registry.extract_skills("good-run", "authentication vulnerability", "test-model")

        with self.registry._connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(len(calls), 2)

    async def test_sanity_check_discards_no_answer(self):
        self._insert_run_state("sanity-run", risk_score=2)
        responses = [
            '{"name":"Security Review","body":"Inspect authentication boundaries.","domain":"security"}',
            "no",
            '{"name":"Architecture Review","body":"Trace service boundaries.","domain":"architecture"}',
            "no",
            '{"name":"Performance Review","body":"Measure latency hotspots.","domain":"backend"}',
            "no",
        ]

        async def fake_acompletion(*args, **kwargs):
            return _fake_completion(responses.pop(0))

        with patch("skill_registry.get_embedder", return_value=_FakeEmbedder()), \
             patch("skill_registry.litellm.acompletion", side_effect=fake_acompletion):
            await self.registry.extract_skills("sanity-run", "authentication vulnerability", "test-model")

        with self.registry._connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        self.assertEqual(count, 0)

    async def test_dedup_increments_confidence(self):
        self._insert_run_state("dedup-run", risk_score=2)
        vector = np.array([1.0, 0.0, 0.0, 1.0], dtype=np.float32)
        with self.registry._connection() as conn:
            conn.execute(
                """
                INSERT INTO skills (name, body, domain, source_run, confidence, used_count, created_at, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Duplicate Skill", "duplicate dedup security review", "security", "dedup-run", 0.5, 0, time.time(), vector.tobytes()),
            )

        responses = [
            '{"name":"Duplicate Skill","body":"duplicate dedup security review","domain":"security"}',
            "yes",
        ]

        async def fake_acompletion(*args, **kwargs):
            return _fake_completion(responses.pop(0))

        with patch("skill_registry.get_embedder", return_value=_FakeEmbedder()), \
             patch("skill_registry.litellm.acompletion", side_effect=fake_acompletion):
            await self.registry.extract_skills("dedup-run", "authentication vulnerability", "test-model")

        with self.registry._connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count, MAX(confidence) AS confidence FROM skills").fetchone()
        self.assertEqual(row["count"], 1)
        self.assertAlmostEqual(row["confidence"], 0.55, places=3)

    def test_deduplicate_skills_merges_near_identical_embeddings(self):
        vector = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        with self.registry._connection() as conn:
            conn.execute(
                """
                INSERT INTO skills (name, body, domain, source_run, confidence, used_count, created_at, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Security Review", "Inspect auth boundaries.", "security", None, 0.8, 2, time.time(), vector.tobytes()),
            )
            conn.execute(
                """
                INSERT INTO skills (name, body, domain, source_run, confidence, used_count, created_at, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Auth Review", "Inspect authentication boundaries.", "security", None, 0.7, 3, time.time(), vector.tobytes()),
            )
            conn.execute(
                """
                INSERT INTO skills (name, body, domain, source_run, confidence, used_count, created_at, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Access Review", "Inspect authorization boundaries.", "security", None, 0.6, 4, time.time(), vector.tobytes()),
            )

        result = self.registry.deduplicate_skills()

        with self.registry._connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count, MAX(confidence) AS confidence, MAX(used_count) AS used_count FROM skills").fetchone()

        self.assertEqual(result["merged"], 2)
        self.assertEqual(row["count"], 1)
        self.assertAlmostEqual(row["confidence"], 0.9, places=3)
        self.assertEqual(row["used_count"], 9)

    async def test_get_skills_returns_relevant(self):
        with self.registry._connection() as conn:
            conn.execute(
                """
                INSERT INTO skills (name, body, domain, source_run, confidence, used_count, created_at, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Security Review",
                    "Inspect authentication and authorization boundaries for vulnerabilities.",
                    "security",
                    None,
                    0.9,
                    0,
                    time.time(),
                    np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32).tobytes(),
                ),
            )
            conn.execute(
                """
                INSERT INTO skills (name, body, domain, source_run, confidence, used_count, created_at, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Cache Review",
                    "Measure latency before adding caches.",
                    "backend",
                    None,
                    0.9,
                    0,
                    time.time(),
                    np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32).tobytes(),
                ),
            )

        with patch("skill_registry.get_embedder", return_value=_FakeEmbedder()), \
             patch("skill_registry.litellm.acompletion") as llm_mock:
            skills = await self.registry.get_skills_for_topic("authentication vulnerability", top_k=1)

        self.assertEqual(skills[0]["name"], "Security Review")
        llm_mock.assert_not_called()

    async def test_used_count_increments(self):
        with self.registry._connection() as conn:
            conn.execute(
                """
                INSERT INTO skills (name, body, domain, source_run, confidence, used_count, created_at, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Security Review",
                    "Inspect authentication boundaries.",
                    "security",
                    None,
                    0.9,
                    0,
                    time.time(),
                    np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32).tobytes(),
                ),
            )

        with patch("skill_registry.get_embedder", return_value=_FakeEmbedder()):
            skills = await self.registry.get_skills_for_topic("authentication vulnerability", top_k=1)
            self.assertEqual(skills[0]["used_count"], 0)
            await asyncio.sleep(0.05)

        with self.registry._connection() as conn:
            used_count = conn.execute("SELECT used_count FROM skills WHERE id = ?", (skills[0]["id"],)).fetchone()[0]
        self.assertEqual(used_count, 1)

    def test_format_skills_block_empty(self):
        self.assertEqual(self.registry.format_skills_block([]), "")

    def test_format_skills_block_populated(self):
        block = self.registry.format_skills_block(
            [
                {"name": "Security Review", "body": "Inspect auth boundaries."},
                {"name": "Architecture Review", "body": "Trace service boundaries."},
            ]
        )
        self.assertTrue(block.startswith("COUNCIL SKILLS"))


if __name__ == "__main__":
    unittest.main()
