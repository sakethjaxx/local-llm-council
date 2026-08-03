import sqlite3


def db_connect(path: str, *, check_same_thread: bool = True, row_factory: bool = False, timeout: float = 30.0) -> sqlite3.Connection:
    """Shared SQLite connection setup: WAL journal + foreign keys + 30s busy timeout,
    used by all stores (run_store, memory_store, skill_registry) to prevent database locks
    during parallel async execution."""
    conn = sqlite3.connect(path, check_same_thread=check_same_thread, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn
