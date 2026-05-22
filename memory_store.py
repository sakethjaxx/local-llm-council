import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import List, Optional

import litellm
import numpy as np
from pydantic import BaseModel

from embeddings import get_embedder
from run_store import DB_PATH


class Triple(BaseModel):
    subject: str
    predicate: str
    object: str


class MemoryExtraction(BaseModel):
    triples: List[Triple]


def _extract_json_block(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
    return raw


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


class SQLiteMemory:
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
                """
            )

    def _embed_text(self, text: str) -> np.ndarray:
        return _to_vector(get_embedder().encode(text))

    def _serialize_embedding(self, vector: np.ndarray) -> bytes:
        return vector.astype(np.float32).tobytes()

    def _deserialize_embedding(self, blob: Optional[bytes]) -> Optional[np.ndarray]:
        if not blob:
            return None
        return np.frombuffer(blob, dtype=np.float32)

    def _extract_risk_score(self, raw_output: str) -> Optional[float]:
        try:
            parsed = json.loads(raw_output)
            value = parsed.get("risk_score")
            return float(value) if value is not None else None
        except Exception:
            pass

        try:
            parsed = json.loads(_extract_json_block(raw_output))
            value = parsed.get("risk_score")
            return float(value) if value is not None else None
        except Exception:
            pass

        match = re.search(r'"risk_score"\s*:\s*(\d+(?:\.\d+)?)', raw_output)
        if match:
            return float(match.group(1))
        return None

    def _should_extract(self, run_id: Optional[str]) -> bool:
        if not run_id:
            return True

        with self._connection() as conn:
            feedback_rows = conn.execute(
                "SELECT rating FROM run_feedback WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            has_thumbs_up = any(str(row["rating"]).lower() in {"up", "thumbs_up"} for row in feedback_rows)
            if has_thumbs_up:
                return True

            chairman_row = conn.execute(
                """
                SELECT output
                FROM phase_outputs
                WHERE run_id = ? AND phase = 3 AND member_id = 'chairman'
                """,
                (run_id,),
            ).fetchone()

        if chairman_row is None:
            return True

        risk_score = self._extract_risk_score(chairman_row["output"] or "")
        return risk_score is None or risk_score <= 3

    async def extract_memory(
        self,
        topic: str,
        verdict: str,
        extraction_model: str,
        run_id: str = None,
    ) -> None:
        if not self._should_extract(run_id):
            print(f"[Memory] Skipping extraction for run {run_id}: quality gate not met.")
            return

        prompt = f"""You are an information extraction engine for an AI council.
Given the topic discussed and the final verdict delivered by the Chairman, extract the core knowledge as a list of facts.
Use the provided JSON schema to output an array of triples under the 'triples' key.
Each triple has a subject, predicate, and object. Keep subjects and objects concise (1-4 words).
Examples of predicates: "decided_to_use", "rejected", "identified_risk", "recommended".

Topic: {topic[:500]}...
Verdict: {verdict[:1500]}..."""
        model = os.getenv("COUNCIL_MEMORY_MODEL", extraction_model)

        try:
            print(f"\n[🧠 Memory] Extracting triples using {model}...")
            resp = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                response_format=MemoryExtraction,
            )
            raw_output = resp.choices[0].message.content
            data = MemoryExtraction.model_validate_json(_extract_json_block(raw_output))
            now = time.time()
            added = 0
            updated = 0

            with self._connection() as conn:
                existing_rows = conn.execute(
                    """
                    SELECT id, confidence, reinforced, embedding
                    FROM memory_triples
                    WHERE embedding IS NOT NULL
                    """
                ).fetchall()

                existing_vectors = []
                for row in existing_rows:
                    vector = self._deserialize_embedding(row["embedding"])
                    if vector is not None:
                        existing_vectors.append((row, vector))

                for triple in data.triples:
                    triple_text = f"{triple.subject} {triple.predicate} {triple.object}"
                    vector = self._embed_text(triple_text)

                    best_match = None
                    best_score = -1.0
                    for row, stored_vector in existing_vectors:
                        score = _cosine_similarity(vector, stored_vector)
                        if score > 0.92 and score > best_score:
                            best_match = row
                            best_score = score

                    if best_match is not None:
                        conn.execute(
                            """
                            UPDATE memory_triples
                            SET reinforced = reinforced + 1,
                                last_seen = ?,
                                confidence = MIN(1.0, confidence + 0.1)
                            WHERE id = ?
                            """,
                            (now, best_match["id"]),
                        )
                        updated += 1
                        continue

                    conn.execute(
                        """
                        INSERT INTO memory_triples (
                            subject, predicate, object, confidence, reinforced,
                            contradicted, last_seen, created_at, embedding
                        )
                        VALUES (?, ?, ?, 1.0, 1, 0, ?, ?, ?)
                        """,
                        (
                            triple.subject,
                            triple.predicate,
                            triple.object,
                            now,
                            now,
                            self._serialize_embedding(vector),
                        ),
                    )
                    existing_vectors.append(({"id": conn.execute("SELECT last_insert_rowid()").fetchone()[0]}, vector))
                    added += 1

            print(f"[✅ Memory] Added {added} new facts and reinforced {updated} existing facts.")
        except Exception as exc:
            print(f"[❌ Memory] Extraction failed: {exc}")

    async def get_context(self, topic: str, extraction_model: str, top_k: int = 10) -> str:
        del extraction_model

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, subject, predicate, object, confidence, last_seen, embedding
                FROM memory_triples
                """
            ).fetchall()

        if not rows:
            return ""

        query_vector = self._embed_text(topic)
        now = time.time()
        scored = []
        for row in rows:
            vector = self._deserialize_embedding(row["embedding"])
            if vector is None:
                continue
            similarity = _cosine_similarity(query_vector, vector)
            days_since_last_seen = max(0.0, (now - float(row["last_seen"])) / 86400.0)
            effective_confidence = float(row["confidence"]) * (0.99 ** days_since_last_seen)
            score = similarity * effective_confidence
            scored.append(
                (
                    score,
                    f'{row["subject"]} -> {row["predicate"]} -> {row["object"]}',
                )
            )

        if not scored:
            return ""

        scored.sort(key=lambda item: item[0], reverse=True)
        top = [text for _, text in scored[: max(1, top_k)]]
        return "COUNCIL HISTORICAL MEMORY (Past decisions you must consider):\n" + "\n".join(top) + "\n\n"

    def get_graph_data(self) -> dict:
        with self._connection() as conn:
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

    def rebuild_embeddings(self) -> None:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, subject, predicate, object
                FROM memory_triples
                WHERE embedding IS NULL
                """
            ).fetchall()

            rebuilt = 0
            for row in rows:
                text = f'{row["subject"]} {row["predicate"]} {row["object"]}'
                conn.execute(
                    "UPDATE memory_triples SET embedding = ? WHERE id = ?",
                    (self._serialize_embedding(self._embed_text(text)), row["id"]),
                )
                rebuilt += 1

        print(f"[Memory] Rebuilt embeddings for {rebuilt} triples.")


memory_store = SQLiteMemory()
