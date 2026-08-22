import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from typing import List, Optional

import runtime_defaults  # noqa: F401  # configure LiteLLM before import
import litellm
import numpy as np

from cloud_keys import litellm_kwargs_for_model
from embeddings import cosine_similarity as _cosine_similarity, get_embedder
from logging_utils import get_logger
from memory_db import (
    _db_connect,
    fetch_graph_records,
    init_memory_db,
    prune_memory_db,
    query_memory_context,
)
from memory_embeddings import (
    _to_vector,
    deserialize_embedding,
    embed_memory_text,
    serialize_embedding,
)
from memory_extraction import (
    MemoryExtraction,
    Triple,
    _extract_json_block,
    _extract_risk_score,
    execute_memory_extraction,
    persist_extracted_triples,
    should_extract_memory,
)
from provider_caps import caps_for
from run_store import DB_PATH

logger = get_logger(__name__)

MEMORY_RELEVANCE_FLOOR = float(os.getenv("COUNCIL_MEMORY_RELEVANCE_FLOOR", "0.25"))


def _get_litellm():
    mod = sys.modules.get("memory_store")
    return getattr(mod, "litellm", litellm)


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
            init_memory_db(conn)

    def _embed_text(self, text: str) -> np.ndarray:
        return embed_memory_text(text)

    def _serialize_embedding(self, vector: np.ndarray) -> bytes:
        return serialize_embedding(vector)

    def _deserialize_embedding(self, blob: Optional[bytes]) -> Optional[np.ndarray]:
        return deserialize_embedding(blob)

    def _extract_risk_score(self, raw_output: str) -> Optional[float]:
        return _extract_risk_score(raw_output)

    def _should_extract(self, run_id: Optional[str]) -> bool:
        with self._connection() as conn:
            return should_extract_memory(conn, run_id)

    async def extract_memory(
        self,
        topic: str,
        verdict: str,
        extraction_model: str,
        run_id: str = None,
    ) -> None:
        with self._connection() as conn:
            await execute_memory_extraction(
                conn, topic, verdict, extraction_model, run_id,
                _get_litellm(), self._embed_text, self._serialize_embedding, self._deserialize_embedding
            )

    async def get_context(self, topic: str, extraction_model: str, top_k: int = 10) -> str:
        del extraction_model
        with self._connection() as conn:
            return query_memory_context(
                conn, topic, self._embed_text, self._deserialize_embedding, MEMORY_RELEVANCE_FLOOR, top_k
            )

    def get_graph_data(self) -> dict:
        with self._connection() as conn:
            return fetch_graph_records(conn)

    def all_triples(self) -> list[Triple]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT subject, predicate, object, confidence FROM memory_triples ORDER BY last_seen DESC, id DESC"
            ).fetchall()
        return [
            Triple(
                subject=row["subject"],
                predicate=row["predicate"],
                object=row["object"],
                confidence=row["confidence"],
            )
            for row in rows
        ]

    def rebuild_embeddings(self) -> None:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, subject, predicate, object FROM memory_triples WHERE embedding IS NULL"
            ).fetchall()
            rebuilt = 0
            for row in rows:
                text = f'{row["subject"]} {row["predicate"]} {row["object"]}'
                conn.execute(
                    "UPDATE memory_triples SET embedding = ? WHERE id = ?",
                    (self._serialize_embedding(self._embed_text(text)), row["id"]),
                )
                rebuilt += 1
        logger.info("memory_embeddings_rebuilt", extra={"rebuilt": rebuilt})

    def prune_memory(
        self,
        min_confidence: float = 0.30,
        decay_per_day: float = 0.99,
        max_age_days: int = 30,
        force: bool = False,
    ) -> dict:
        with self._connection() as conn:
            res = prune_memory_db(conn, min_confidence, decay_per_day, max_age_days, force)
        logger.info("memory_pruned", extra={"decayed": res["decayed"], "deleted": res["deleted"]})
        return res


memory_store = SQLiteMemory()
