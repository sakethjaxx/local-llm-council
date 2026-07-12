import sqlite3


def db_connect(path: str, *, check_same_thread: bool = True, row_factory: bool = False) -> sqlite3.Connection:
    """Shared SQLite connection setup: WAL journal + foreign keys on, used by all
    three stores (run_store, memory_store, skill_registry) so the pragma boilerplate
    lives in exactly one place."""
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn
