import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Optional

from provider_caps import redact_config


DB_PATH = "council_runs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    started_at       REAL NOT NULL,
    finished_at      REAL,
    status           TEXT NOT NULL,
    topic            TEXT NOT NULL,
    roster_json      TEXT NOT NULL,
    fingerprint_hash TEXT,
    deep_debate      INTEGER NOT NULL,
    smart_phase_score REAL,
    error            TEXT
);

CREATE TABLE IF NOT EXISTS phase_outputs (
    run_id     TEXT NOT NULL,
    phase      INTEGER NOT NULL,
    member_id  TEXT NOT NULL,
    output     TEXT NOT NULL,
    tokens_in  INTEGER,
    tokens_out INTEGER,
    latency_ms INTEGER,
    finish_reason TEXT,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (run_id, phase, member_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS run_feedback (
    run_id        TEXT NOT NULL,
    action_index  INTEGER NOT NULL,
    rating        TEXT NOT NULL,
    note          TEXT,
    rated_at      REAL NOT NULL,
    PRIMARY KEY (run_id, action_index),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    body        TEXT NOT NULL,
    domain      TEXT,
    source_run  TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    confidence  REAL NOT NULL DEFAULT 0.5,
    used_count  INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    embedding   BLOB
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_fingerprint ON runs(fingerprint_hash);
CREATE INDEX IF NOT EXISTS idx_skills_confidence ON skills(confidence DESC);

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


def _db_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@dataclass
class StoredRun:
    run_id: str
    started_at: float
    finished_at: Optional[float]
    status: str
    topic: str
    roster: dict
    fingerprint_hash: Optional[str]
    deep_debate: bool
    smart_phase_score: Optional[float]
    error: Optional[str]


class RunStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        conn = _db_connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        try:
            with self._connection() as conn:
                conn.executescript(SCHEMA)
                self._migrate_runs(conn)
                self._migrate_phase_outputs(conn)
        except Exception as exc:
            print(f"[❌ RunStore] Failed to initialize DB: {exc}")

    def _migrate_runs(self, conn):
        cursor = conn.execute("PRAGMA table_info(runs)")
        cols = {row[1] for row in cursor.fetchall()}
        if "smart_phase_score" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN smart_phase_score REAL")

    def _migrate_phase_outputs(self, conn):
        cursor = conn.execute("PRAGMA table_info(phase_outputs)")
        cols = {row[1] for row in cursor.fetchall()}
        if "finish_reason" not in cols:
            conn.execute("ALTER TABLE phase_outputs ADD COLUMN finish_reason TEXT")
        if "attempt_number" not in cols:
            conn.execute("ALTER TABLE phase_outputs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1")

    def begin_run(self, run_id, topic, roster, deep_debate, fingerprint_hash=None) -> None:
        try:
            roster_json = json.dumps(redact_config(roster or {}))
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, started_at, status, topic, roster_json,
                        fingerprint_hash, deep_debate
                    )
                    VALUES (?, ?, 'running', ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        topic=excluded.topic,
                        roster_json=excluded.roster_json,
                        fingerprint_hash=excluded.fingerprint_hash,
                        deep_debate=excluded.deep_debate,
                        status='running',
                        smart_phase_score=NULL,
                        finished_at=NULL,
                        error=NULL
                    """,
                    (
                        run_id,
                        time.time(),
                        topic or "",
                        roster_json,
                        fingerprint_hash,
                        int(bool(deep_debate)),
                    ),
                )
        except Exception as exc:
            print(f"[❌ RunStore] Failed to begin run {run_id}: {exc}")

    def record_phase_output(
        self,
        run_id,
        phase,
        member_id,
        output,
        tokens_in=None,
        tokens_out=None,
        latency_ms=None,
        finish_reason: str | None = None,
        attempt_number: int | None = 1,
    ):
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO phase_outputs (
                        run_id, phase, member_id, output, tokens_in, tokens_out,
                        latency_ms, finish_reason, attempt_number
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, phase, member_id) DO UPDATE SET
                        output=excluded.output,
                        tokens_in=COALESCE(excluded.tokens_in, phase_outputs.tokens_in),
                        tokens_out=COALESCE(excluded.tokens_out, phase_outputs.tokens_out),
                        latency_ms=COALESCE(excluded.latency_ms, phase_outputs.latency_ms),
                        finish_reason=COALESCE(excluded.finish_reason, phase_outputs.finish_reason),
                        attempt_number=COALESCE(?, phase_outputs.attempt_number)
                    """,
                    (
                        run_id,
                        phase,
                        member_id,
                        output or "",
                        tokens_in,
                        tokens_out,
                        latency_ms,
                        finish_reason,
                        attempt_number if attempt_number is not None else 1,
                        attempt_number,
                    ),
                )
        except Exception as exc:
            print(f"[❌ RunStore] Failed to record phase output for {run_id}: {exc}")

    def finish_run(self, run_id, status: str, error: Optional[str] = None):
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    UPDATE runs
                    SET finished_at = ?, status = ?, error = ?
                    WHERE run_id = ?
                    """,
                    (time.time(), status, error, run_id),
                )
        except Exception as exc:
            print(f"[❌ RunStore] Failed to finish run {run_id}: {exc}")

    def update_smart_phase_score(self, run_id, score):
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    UPDATE runs
                    SET smart_phase_score = ?
                    WHERE run_id = ?
                    """,
                    (score, run_id),
                )
        except Exception as exc:
            print(f"[❌ RunStore] Failed to update smart phase score for {run_id}: {exc}")

    def record_feedback(self, run_id, action_index: int, rating: str, note: str = ""):
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO run_feedback (run_id, action_index, rating, note, rated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, action_index) DO UPDATE SET
                        rating=excluded.rating,
                        note=excluded.note,
                        rated_at=excluded.rated_at
                    """,
                    (run_id, action_index, rating, note or "", time.time()),
                )
        except Exception as exc:
            print(f"[❌ RunStore] Failed to record feedback for {run_id}: {exc}")

    def get_run(self, run_id: str) -> dict:
        with self._connection() as conn:
            run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if run is None:
                return {}
            phases = conn.execute(
                "SELECT * FROM phase_outputs WHERE run_id = ? ORDER BY phase, member_id",
                (run_id,),
            ).fetchall()
            feedback = conn.execute(
                "SELECT * FROM run_feedback WHERE run_id = ? ORDER BY action_index",
                (run_id,),
            ).fetchall()
        result = self._run_row_to_dict(run)
        result["phases"] = [dict(row) for row in phases]
        result["feedback"] = [dict(row) for row in feedback]
        return result

    def list_runs(self, limit: int = 50, fingerprint_hash: Optional[str] = None) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        with self._connection() as conn:
            if fingerprint_hash:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE fingerprint_hash = ? ORDER BY started_at DESC LIMIT ?",
                    (fingerprint_hash, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._run_row_to_dict(row) for row in rows]

    def delete_run(self, run_id: str):
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            deleted = cursor.rowcount > 0
        return deleted

    def _run_row_to_dict(self, row) -> dict:
        stored = StoredRun(
            run_id=row["run_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            topic=row["topic"],
            roster=json.loads(row["roster_json"] or "{}"),
            fingerprint_hash=row["fingerprint_hash"],
            deep_debate=bool(row["deep_debate"]),
            smart_phase_score=row["smart_phase_score"],
            error=row["error"],
        )
        return asdict(stored)


run_store = RunStore()
