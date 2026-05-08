import json
import os
import threading
import time
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


def _coerce_usage(usage: Any) -> Optional[dict]:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif hasattr(usage, "dict"):
        usage = usage.dict()
    if not isinstance(usage, dict):
        return None

    normalized = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            normalized[key] = int(value)
    return normalized or None


class MetricsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_runs: dict[str, dict] = {}
        self._recent_runs: deque[dict] = deque(maxlen=self._max_recent_runs())

    def _max_recent_runs(self) -> int:
        try:
            return max(10, int(os.getenv("COUNCIL_MAX_RECENT_RUNS", "200")))
        except ValueError:
            return 200

    def _metrics_path(self) -> Optional[Path]:
        path = os.getenv("COUNCIL_METRICS_FILE", "council_metrics.jsonl").strip()
        if not path:
            return None
        return Path(path)

    def start_run(self, run_type: str, metadata: Optional[dict] = None, run_id: Optional[str] = None) -> str:
        run_id = run_id or str(uuid4())
        started_at = time.time()
        run = {
            "run_id": run_id,
            "run_type": run_type,
            "status": "running",
            "started_at": started_at,
            "completed_at": None,
            "duration_ms": None,
            "metadata": metadata or {},
            "llm_calls": [],
            "errors": [],
        }
        with self._lock:
            self._active_runs[run_id] = run
        return run_id

    def record_llm_call(
        self,
        run_id: Optional[str],
        member_id: str,
        phase: Optional[int],
        model: Optional[str],
        label: Optional[str],
        attempt: int,
        duration_ms: int,
        success: bool,
        usage: Optional[dict] = None,
        output_chars: int = 0,
        tool_calls: int = 0,
        error: Optional[str] = None,
    ) -> None:
        if not run_id:
            return

        event = {
            "member_id": member_id,
            "phase": phase,
            "model": model,
            "label": label,
            "attempt": attempt,
            "duration_ms": duration_ms,
            "success": success,
            "usage": _coerce_usage(usage),
            "output_chars": output_chars,
            "tool_calls": tool_calls,
            "error": error,
            "recorded_at": time.time(),
        }

        with self._lock:
            run = self._active_runs.get(run_id)
            if run is None:
                return
            run["llm_calls"].append(event)
            if error:
                run["errors"].append(error)

    def finish_run(self, run_id: Optional[str], status: str = "completed", error: Optional[str] = None) -> None:
        if not run_id:
            return

        with self._lock:
            run = self._active_runs.pop(run_id, None)
            if run is None:
                return

            completed_at = time.time()
            run["status"] = status
            run["completed_at"] = completed_at
            run["duration_ms"] = int((completed_at - run["started_at"]) * 1000)
            if error:
                run["errors"].append(error)

            totals = {
                "llm_calls": len(run["llm_calls"]),
                "successful_calls": sum(1 for call in run["llm_calls"] if call["success"]),
                "failed_calls": sum(1 for call in run["llm_calls"] if not call["success"]),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
            for call in run["llm_calls"]:
                usage = call.get("usage") or {}
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    totals[key] += int(usage.get(key, 0) or 0)
            run["totals"] = totals

            frozen = deepcopy(run)
            self._recent_runs.appendleft(frozen)

        self._append_to_disk(frozen)

    def _append_to_disk(self, run: dict) -> None:
        path = self._metrics_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(run) + "\n")
        except Exception:
            pass

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self._lock:
            active = [deepcopy(run) for run in self._active_runs.values()]
            recent = list(self._recent_runs)[:limit]
        combined = active + recent
        combined.sort(key=lambda run: run["started_at"], reverse=True)
        return combined[:limit]

    def get_summary(self) -> dict:
        runs = self.list_runs(limit=self._max_recent_runs())
        completed = [run for run in runs if run["status"] == "completed"]
        failed = [run for run in runs if run["status"] == "failed"]
        running = [run for run in runs if run["status"] == "running"]

        avg_duration_ms = 0
        if completed:
            avg_duration_ms = int(sum(run["duration_ms"] or 0 for run in completed) / len(completed))

        by_model: dict[str, dict[str, int]] = {}
        for run in runs:
            for call in run.get("llm_calls", []):
                model = call.get("model") or "unknown"
                bucket = by_model.setdefault(
                    model,
                    {"calls": 0, "successes": 0, "failures": 0, "total_duration_ms": 0},
                )
                bucket["calls"] += 1
                bucket["successes"] += int(call.get("success", False))
                bucket["failures"] += int(not call.get("success", False))
                bucket["total_duration_ms"] += int(call.get("duration_ms", 0) or 0)

        return {
            "runs_seen": len(runs),
            "completed_runs": len(completed),
            "failed_runs": len(failed),
            "running_runs": len(running),
            "avg_completed_duration_ms": avg_duration_ms,
            "by_model": by_model,
        }


metrics_store = MetricsStore()
