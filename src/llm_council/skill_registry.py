import asyncio
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

import litellm
import numpy as np

from llm_council.cloud_keys import litellm_kwargs_for_model
from llm_council.embeddings import get_embedder
from llm_council.logging_utils import get_logger
from llm_council.run_store import DB_PATH, SCHEMA


logger = get_logger(__name__)


def _db_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _to_vector(value) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32)
    if vector.ndim > 1:
        vector = vector[0]
    return vector


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def _extract_json_block(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
    return raw


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
        return _to_vector(get_embedder().encode(text))

    def _serialize_embedding(self, vector: np.ndarray) -> bytes:
        return vector.astype(np.float32).tobytes()

    def _deserialize_embedding(self, blob: Optional[bytes]) -> Optional[np.ndarray]:
        if not blob:
            return None
        return np.frombuffer(blob, dtype=np.float32)

    def _extract_risk_score(self, raw_output: str) -> Optional[float]:
        for candidate in (raw_output, _extract_json_block(raw_output)):
            try:
                parsed = json.loads(candidate)
                value = parsed.get("risk_score")
                return float(value) if value is not None else None
            except Exception:
                pass

        match = re.search(r'"risk_score"\s*:\s*(\d+(?:\.\d+)?)', raw_output or "")
        if match:
            return float(match.group(1))
        return None

    def _should_extract(self, run_id: str) -> bool:
        with self._connection() as conn:
            feedback_rows = conn.execute(
                "SELECT rating FROM run_feedback WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            has_thumbs_up = any(str(row["rating"]).lower() in {"up", "thumbs_up"} for row in feedback_rows)

            chairman_row = conn.execute(
                """
                SELECT output
                FROM phase_outputs
                WHERE run_id = ? AND phase = 3 AND member_id = 'chairman'
                """,
                (run_id,),
            ).fetchone()

        risk_score = None
        if chairman_row is not None:
            risk_score = self._extract_risk_score(chairman_row["output"] or "")

        return not (not has_thumbs_up and risk_score is not None and risk_score > 3)

    async def _request_text(self, model: str, prompt: str, temperature: float) -> str:
        resp = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=temperature,
            **litellm_kwargs_for_model(model),
        )
        return resp.choices[0].message.content or ""

    async def extract_skills(self, run_id: str, topic: str, chairman_model: str) -> None:
        async def _do_extract() -> None:
            if not self._should_extract(run_id):
                logger.info("skill_extraction_skipped", extra={"run_id": run_id, "reason": "quality_gate"})
                return

            with self._connection() as conn:
                chairman_row = conn.execute(
                    """
                    SELECT output
                    FROM phase_outputs
                    WHERE run_id = ? AND phase = 3 AND member_id = 'chairman'
                    """,
                    (run_id,),
                ).fetchone()

            if chairman_row is None:
                return

            verdict = chairman_row["output"] or ""
            temperature = 0.4
            try:
                extract_prompt = (
                    "You are a skill extractor for an AI council system.\n"
                    "Given the topic and chairman verdict below, extract ONE reusable analysis skill that future councils could apply.\n"
                    "A skill is a concrete analytical approach, heuristic, or reasoning pattern — not a conclusion.\n"
                    'Respond with JSON: {"name": "short skill name (max 6 words)", "body": "one paragraph describing the skill and when to apply it", "domain": "optional domain tag (e.g. backend, security, architecture, or null)"}\n\n'
                    f"Topic: {topic[:400]}\n"
                    f"Chairman Verdict: {verdict[:1200]}"
                )
                extracted_raw = await self._request_text(chairman_model, extract_prompt, temperature)
                skill = json.loads(_extract_json_block(extracted_raw))
                name = str(skill.get("name", "")).strip()
                body = str(skill.get("body", "")).strip()
                domain = skill.get("domain")
                if not name or not body:
                    return
                if domain is not None:
                    domain = str(domain).strip() or None

                sanity_prompt = (
                    "Does the following analysis skill logically follow from this council verdict?\n"
                    f"Skill: {body}\n"
                    f"Verdict: {verdict[:800]}\n"
                    'Answer with only "yes" or "no".'
                )
                sanity = await self._request_text(chairman_model, sanity_prompt, temperature)
                if not sanity.strip().lower().startswith("yes"):
                    return

                vector = await asyncio.to_thread(self._embed_text, f"{name} {body}")
                serialized = self._serialize_embedding(vector)
                now = time.time()

                with self._connection() as conn:
                    rows = conn.execute(
                        """
                        SELECT id, confidence, embedding
                        FROM skills
                        WHERE embedding IS NOT NULL
                        """
                    ).fetchall()

                    duplicate_id = None
                    duplicate_confidence = None
                    for row in rows:
                        stored = self._deserialize_embedding(row["embedding"])
                        if stored is None:
                            continue
                        if _cosine_similarity(vector, stored) > 0.90:
                            duplicate_id = row["id"]
                            duplicate_confidence = row["confidence"]
                            break

                    if duplicate_id is not None:
                        conn.execute(
                            """
                            UPDATE skills
                            SET confidence = MIN(1.0, ? + 0.05)
                            WHERE id = ?
                            """,
                            (float(duplicate_confidence), duplicate_id),
                        )
                        logger.info("skill_duplicate_reinforced", extra={"skill_id": duplicate_id, "run_id": run_id})
                        return

                    conn.execute(
                        """
                        INSERT INTO skills (
                            name, body, domain, source_run, confidence,
                            used_count, created_at, embedding
                        )
                        VALUES (?, ?, ?, ?, 0.5, 0, ?, ?)
                        """,
                        (name, body, domain, run_id, now, serialized),
                    )
                    self.deduplicate_skills(conn=conn)
            except Exception as exc:
                logger.exception("skill_extraction_failed", extra={"run_id": run_id, "error": str(exc)})

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

        ranked = []
        for row in rows:
            stored = self._deserialize_embedding(row["embedding"])
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
        skills = [item[1] for item in ranked[: max(0, top_k)]]
        if skills:
            asyncio.create_task(asyncio.to_thread(self._increment_used_count, [skill["id"] for skill in skills]))
        return skills

    def apply_feedback(self, run_id: str, rating: str) -> dict:
        """Close the feedback loop: a rated run adjusts the confidence of the
        skills it produced, which directly changes their retrieval rank
        (rank score = cosine similarity x confidence).

        thumbs-down: confidence -0.15 (floor 0.05); thumbs-up: +0.05 (cap 1.0).
        """
        normalized = str(rating or "").lower()
        if normalized in {"down", "thumbs_down"}:
            delta = -0.15
        elif normalized in {"up", "thumbs_up"}:
            delta = 0.05
        else:
            return {"adjusted": 0}

        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE skills
                SET confidence = MAX(0.05, MIN(1.0, confidence + ?))
                WHERE source_run = ?
                """,
                (delta, run_id),
            )
            adjusted = cursor.rowcount
        if adjusted:
            logger.info("skill_feedback_applied", extra={"run_id": run_id, "rating": normalized, "adjusted": adjusted, "delta": delta})
        return {"adjusted": adjusted, "delta": delta}

    def _increment_used_count(self, skill_ids: list[int]) -> None:
        with self._connection() as conn:
            conn.executemany(
                "UPDATE skills SET used_count = used_count + 1 WHERE id = ?",
                [(skill_id,) for skill_id in skill_ids],
            )

    def format_skills_block(self, skills: list[dict]) -> str:
        if not skills:
            return ""
        lines = ["COUNCIL SKILLS (apply these analytical approaches if relevant to the topic):"]
        for s in skills:
            lines.append(f"- [{s['name']}]: {s['body']}")
        return "\n".join(lines) + "\n\n"

    def list_skills(self, limit: int = 50, domain: Optional[str] = None) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        with self._connection() as conn:
            if domain is not None:
                rows = conn.execute(
                    """
                    SELECT id, name, body, domain, confidence, used_count, created_at
                    FROM skills
                    WHERE domain = ?
                    ORDER BY confidence DESC, created_at DESC
                    LIMIT ?
                    """,
                    (domain, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, name, body, domain, confidence, used_count, created_at
                    FROM skills
                    ORDER BY confidence DESC, created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def deduplicate_skills(self, threshold: float = 0.90, conn=None) -> dict:
        if conn is None:
            with self._connection() as owned_conn:
                return self.deduplicate_skills(threshold=threshold, conn=owned_conn)

        rows = conn.execute(
            """
            SELECT id, confidence, used_count, embedding
            FROM skills
            WHERE embedding IS NOT NULL
            ORDER BY confidence DESC, used_count DESC, id ASC
            """
        ).fetchall()
        deleted_ids: set[int] = set()
        merges = 0

        for idx, row in enumerate(rows):
            if row["id"] in deleted_ids:
                continue
            left = self._deserialize_embedding(row["embedding"])
            if left is None:
                continue
            current_confidence = float(row["confidence"])
            current_used_count = int(row["used_count"] or 0)
            for other in rows[idx + 1:]:
                if other["id"] in deleted_ids:
                    continue
                right = self._deserialize_embedding(other["embedding"])
                if right is None:
                    continue
                if _cosine_similarity(left, right) <= threshold:
                    continue
                new_confidence = min(1.0, max(current_confidence, float(other["confidence"])) + 0.05)
                new_used_count = current_used_count + int(other["used_count"] or 0)
                conn.execute(
                    "UPDATE skills SET confidence = ?, used_count = ? WHERE id = ?",
                    (new_confidence, new_used_count, row["id"]),
                )
                conn.execute("DELETE FROM skills WHERE id = ?", (other["id"],))
                current_confidence = new_confidence
                current_used_count = new_used_count
                deleted_ids.add(other["id"])
                merges += 1

        if merges:
            logger.info("skills_deduplicated", extra={"merges": merges})
        return {"merged": merges}


skill_registry = SkillRegistry()
