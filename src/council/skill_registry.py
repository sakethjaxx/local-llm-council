import asyncio
import os
import sqlite3
import sys
from contextlib import contextmanager
from typing import Optional

import runtime_defaults  # noqa: F401  # configure LiteLLM before import
import litellm
import numpy as np

from db import db_connect
from embeddings import cosine_similarity as _cosine_similarity, get_embedder
from logging_utils import get_logger
from memory_embeddings import (
    _to_vector,
    deserialize_embedding,
    embed_memory_text,
    serialize_embedding,
)
from run_store import DB_PATH, SCHEMA
from skill_db import deduplicate_skills_db, increment_skill_usage, list_skill_records
from skill_extraction import (
    _extract_json_block,
    _extract_risk_score,
    extract_and_persist_skill,
    request_skill_text,
    should_extract_skill,
)

logger = get_logger(__name__)


def _db_connect(path: str) -> sqlite3.Connection:
    return db_connect(path, check_same_thread=False, row_factory=True)


def _get_litellm():
    mod = sys.modules.get("skill_registry")
    return getattr(mod, "litellm", litellm)


def _get_embedder():
    mod = sys.modules.get("skill_registry")
    return getattr(mod, "get_embedder", get_embedder)()


def _rank_and_score_skills(rows, vector: np.ndarray, top_k: int) -> list[dict]:
    ranked = []
    for row in rows:
        stored = deserialize_embedding(row["embedding"])
        if stored is None:
            continue
        score = _cosine_similarity(vector, stored) * float(row["confidence"])
        ranked.append(
            (
                score,
                {
                    "id": row["id"],
                    "name": row["name"],
                    "body": row["body"],
                    "domain": row["domain"],
                    "confidence": row["confidence"],
                    "used_count": row["used_count"],
                },
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked[: max(0, top_k)]]


class SkillRegistry:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._memory_conn = _db_connect(":memory:") if db_path == ":memory:" else None
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = self._memory_conn or _db_connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self._memory_conn is None:
                conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(SCHEMA)

    def _embed_text(self, text: str) -> np.ndarray:
        return _to_vector(_get_embedder().encode(text))

    def _serialize_embedding(self, vector: np.ndarray) -> bytes:
        return serialize_embedding(vector)

    def _deserialize_embedding(self, blob: Optional[bytes]) -> Optional[np.ndarray]:
        return deserialize_embedding(blob)

    def _extract_risk_score(self, raw_output: str) -> Optional[float]:
        return _extract_risk_score(raw_output)

    def _should_extract(self, run_id: str) -> bool:
        with self._connection() as conn:
            return should_extract_skill(conn, run_id)

    async def _request_text(self, model: str, prompt: str, temperature: float) -> str:
        return await request_skill_text(_get_litellm(), model, prompt, temperature)

    async def extract_skills(self, run_id: str, topic: str, chairman_model: str) -> None:
        async def _do_extract() -> None:
            with self._connection() as conn:
                await extract_and_persist_skill(
                    conn, run_id, topic, chairman_model, _get_litellm(),
                    self._embed_text, self._serialize_embedding, self._deserialize_embedding,
                    self.deduplicate_skills,
                )

        try:
            await asyncio.wait_for(_do_extract(), timeout=45.0)
        except asyncio.TimeoutError:
            logger.warning("skill_extraction_timeout", extra={"run_id": run_id})

    async def get_skills_for_topic(self, topic: str, top_k: int = 3) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, body, domain, confidence, used_count, embedding
                FROM skills
                WHERE embedding IS NOT NULL
                """
            ).fetchall()
        if not rows or top_k <= 0:
            return []

        vector = await asyncio.to_thread(self._embed_text, topic)
        skills = _rank_and_score_skills(rows, vector, top_k)
        if skills:
            asyncio.create_task(asyncio.to_thread(self._increment_used_count, [skill["id"] for skill in skills]))
        return skills

    def _increment_used_count(self, skill_ids: list[int]) -> None:
        with self._connection() as conn:
            increment_skill_usage(conn, skill_ids)

    def format_skills_block(self, skills: list[dict]) -> str:
        if not skills:
            return ""
        lines = ["COUNCIL SKILLS (apply these analytical approaches if relevant to the topic):"]
        for s in skills:
            lines.append(f"- [{s['name']}]: {s['body']}")
        return "\n".join(lines) + "\n\n"

    def list_skills(self, limit: int = 50, domain: Optional[str] = None) -> list[dict]:
        with self._connection() as conn:
            return list_skill_records(conn, limit, domain)

    def deduplicate_skills(self, threshold: float = 0.90, conn=None) -> dict:
        if conn is None:
            with self._connection() as owned_conn:
                return deduplicate_skills_db(owned_conn, self._deserialize_embedding, threshold)
        return deduplicate_skills_db(conn, self._deserialize_embedding, threshold)


skill_registry = SkillRegistry()
