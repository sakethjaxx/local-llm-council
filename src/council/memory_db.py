import sqlite3
import time
from typing import Optional
from db import db_connect
from embeddings import cosine_similarity as _cosine_similarity
from logging_utils import get_logger

logger = get_logger(__name__)


def _db_connect(path: str) -> sqlite3.Connection:
    return db_connect(path, check_same_thread=False, row_factory=True)


def init_memory_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_triples (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            subject      TEXT NOT NULL,
            predicate    TEXT NOT NULL,
            object       TEXT NOT NULL,
            confidence   REAL NOT NULL DEFAULT 1.0,
            reinforced   INTEGER NOT NULL DEFAULT 1,
            contradicted INTEGER NOT NULL DEFAULT 0,
            last_seen    REAL NOT NULL,
            created_at   REAL NOT NULL,
            embedding    BLOB
        );
        CREATE INDEX IF NOT EXISTS idx_memory_subject ON memory_triples(subject);
        CREATE INDEX IF NOT EXISTS idx_memory_last_seen ON memory_triples(last_seen DESC);
        CREATE TABLE IF NOT EXISTS maintenance_state (
            key TEXT PRIMARY KEY,
            value REAL NOT NULL
        );
        """
    )


def fetch_graph_records(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT subject, predicate, object FROM memory_triples ORDER BY last_seen DESC, id DESC"
    ).fetchall()
    node_ids = []
    seen = set()
    edges = []
    for row in rows:
        for value in (row["subject"], row["object"]):
            if value not in seen:
                seen.add(value)
                node_ids.append({"id": value, "label": str(value)})
        edges.append(
            {"from": row["subject"], "to": row["object"], "label": str(row["predicate"])}
        )
    return {"nodes": node_ids, "edges": edges}


def query_memory_context(
    conn: sqlite3.Connection,
    topic: str,
    embed_fn,
    deserialize_fn,
    relevance_floor: float,
    top_k: int = 10,
) -> str:
    rows = conn.execute(
        """
        SELECT id, subject, predicate, object, confidence, last_seen, embedding
        FROM memory_triples
        WHERE embedding IS NOT NULL
        ORDER BY confidence DESC, last_seen DESC
        LIMIT 500
        """
    ).fetchall()

    if not rows:
        return ""
    if len(rows) == 500:
        logger.warning("memory_row_cap_hit", extra={"limit": 500})

    query_vector = embed_fn(topic)
    now = time.time()
    scored = []
    for row in rows:
        vector = deserialize_fn(row["embedding"])
        if vector is None:
            continue
        similarity = _cosine_similarity(query_vector, vector)
        days_since_last_seen = max(0.0, (now - float(row["last_seen"])) / 86400.0)
        effective_confidence = float(row["confidence"]) * (0.99 ** days_since_last_seen)
        score = similarity * effective_confidence
        scored.append((score, f'{row["subject"]} -> {row["predicate"]} -> {row["object"]}'))

    if not scored:
        return ""

    scored.sort(key=lambda item: item[0], reverse=True)
    relevant = [(score, text) for score, text in scored if score >= relevance_floor]
    if not relevant:
        logger.info("memory_context_empty", extra={"best_score": round(scored[0][0], 4) if scored else None})
        return ""
    top = [text for _, text in relevant[: max(1, top_k)]]
    return "COUNCIL HISTORICAL MEMORY (Past decisions you must consider):\n" + "\n".join(top) + "\n\n"


def prune_memory_db(
    conn: sqlite3.Connection,
    min_confidence: float = 0.30,
    decay_per_day: float = 0.99,
    max_age_days: int = 30,
    force: bool = False,
) -> dict:
    now = time.time()
    state = conn.execute(
        "SELECT value FROM maintenance_state WHERE key = 'memory_pruned_at'"
    ).fetchone()
    last_pruned_at = float(state["value"]) if state is not None else None
    if not force and last_pruned_at is not None and now - last_pruned_at < 86400:
        return {"decayed": 0, "deleted": 0, "skipped": True}

    rows = conn.execute(
        "SELECT id, confidence, last_seen FROM memory_triples"
    ).fetchall()
    decayed = 0
    for row in rows:
        decay_start = max(float(row["last_seen"]), last_pruned_at or float(row["last_seen"]))
        days = max(0.0, (now - decay_start) / 86400.0)
        if days <= 0:
            continue
        new_confidence = max(0.0, float(row["confidence"]) * (decay_per_day ** days))
        if new_confidence != float(row["confidence"]):
            conn.execute(
                "UPDATE memory_triples SET confidence = ? WHERE id = ?",
                (new_confidence, row["id"]),
            )
            decayed += 1

    cutoff = now - (max(1, int(max_age_days)) * 86400)
    deleted = conn.execute(
        "DELETE FROM memory_triples WHERE confidence < ? AND last_seen < ?",
        (min_confidence, cutoff),
    ).rowcount
    conn.execute(
        """
        INSERT INTO maintenance_state (key, value)
        VALUES ('memory_pruned_at', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (now,),
    )
    return {"decayed": decayed, "deleted": deleted, "skipped": False}
