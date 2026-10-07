import threading
import time


_shutdown_requested = threading.Event()
_active_runs = 0
_lock = threading.Lock()


def request_shutdown() -> None:
    _shutdown_requested.set()


def clear_shutdown_request() -> None:
    _shutdown_requested.clear()


def is_shutdown_requested() -> bool:
    return _shutdown_requested.is_set()


def try_reserve_run_slot(limit: int) -> bool:
    """Atomically claim a run slot; the caller must release_run_slot() on every exit path."""
    global _active_runs
    with _lock:
        if _active_runs >= limit:
            return False
        _active_runs += 1
        return True


def release_run_slot() -> None:
    global _active_runs
    with _lock:
        _active_runs = max(0, _active_runs - 1)


def active_stream_count() -> int:
    with _lock:
        return _active_runs


def wait_for_active_streams(timeout_s: float = 10.0, poll_interval_s: float = 0.1) -> int:
    deadline = time.time() + max(0.0, timeout_s)
    while time.time() < deadline:
        remaining = active_stream_count()
        if remaining <= 0:
            return 0
        time.sleep(poll_interval_s)
    return active_stream_count()
