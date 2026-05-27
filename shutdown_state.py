import threading
import time
from contextlib import contextmanager


_shutdown_requested = threading.Event()
_active_streams = 0
_lock = threading.Lock()


def request_shutdown() -> None:
    _shutdown_requested.set()


def clear_shutdown_request() -> None:
    _shutdown_requested.clear()


def is_shutdown_requested() -> bool:
    return _shutdown_requested.is_set()


@contextmanager
def track_active_stream():
    global _active_streams
    with _lock:
        _active_streams += 1
    try:
        yield
    finally:
        with _lock:
            _active_streams = max(0, _active_streams - 1)


def active_stream_count() -> int:
    with _lock:
        return _active_streams


def wait_for_active_streams(timeout_s: float = 10.0, poll_interval_s: float = 0.1) -> int:
    deadline = time.time() + max(0.0, timeout_s)
    while time.time() < deadline:
        remaining = active_stream_count()
        if remaining <= 0:
            return 0
        time.sleep(poll_interval_s)
    return active_stream_count()
