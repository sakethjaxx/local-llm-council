import sqlite3
from typing import Optional
from embeddings import cosine_similarity as _cosine_similarity
from logging_utils import get_logger

logger = get_logger(__name__)


def list_skill_records(conn: sqlite3.Connection, limit: int = 50, domain: Optional[str] = None) -> list[dict]:
    limit = max(1, min(int(limit), 500))
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


def increment_skill_usage(conn: sqlite3.Connection, skill_ids: list[int]) -> None:
    conn.executemany(
        "UPDATE skills SET used_count = used_count + 1 WHERE id = ?",
        [(skill_id,) for skill_id in skill_ids],
    )


def deduplicate_skills_db(conn: sqlite3.Connection, deserialize_fn, threshold: float = 0.90) -> dict:
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
        left = deserialize_fn(row["embedding"])
        if left is None:
            continue
        current_confidence = float(row["confidence"])
        current_used_count = int(row["used_count"] or 0)
        for other in rows[idx + 1:]:
            if other["id"] in deleted_ids:
                continue
            right = deserialize_fn(other["embedding"])
            if right is None or _cosine_similarity(left, right) <= threshold:
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
