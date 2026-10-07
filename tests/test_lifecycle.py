import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import routes_stream
import shutdown_state
import orchestrator as orchestrator_module
from orchestrator import CouncilOrchestrator
from run_store import RunStore

SRC = str(Path(__file__).resolve().parents[1] / "src")


async def _noop(*args, **kwargs):
    return None


async def _empty(*args, **kwargs):
    return ""


async def _same(value, *args, **kwargs):
    return value


class DisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_disconnect_closes_the_pipeline_immediately(self):
        closed = []

        class FakeOrchestrator:
            async def run(self, *args, **kwargs):
                try:
                    yield {"type": "phase_start", "phase": 1, "label": "Analysis"}
                    await asyncio.sleep(3600)
                finally:
                    closed.append(True)

        ready = {"ready": True, "missing": [], "required": [], "pulled": [], "auto_pull_enabled": False}
        attrs = {"CouncilOrchestrator": FakeOrchestrator, "ensure_models_for_config": lambda *a: ready}
        with patch("routes_stream._main_attr", side_effect=lambda name, default: attrs.get(name, default)):
            stream = routes_stream.stream_council_lifecycle(
                "topic", [], {"chairman": {"model": "ollama/x"}}, None, "economy", False, False, {}, {"type": "shutdown"})
            async for frame in stream:
                if "phase_start" in frame:
                    break
            await stream.aclose()  # what Starlette does when the browser goes away
        self.assertEqual(closed, [True])

    async def test_aborted_run_cancels_and_awaits_member_calls(self):
        started, cancelled = [], []

        async def hanging_member(self, member_id, *args, **kwargs):
            started.append(member_id)
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled.append(member_id)
                raise

        with patch("orchestrator.parse_input", side_effect=_same), \
                patch("orchestrator.chunk_and_summarize", side_effect=_same), \
                patch("orchestrator.memory_engine.get_context", side_effect=_empty), \
                patch("orchestrator.skill_registry.get_skills_for_topic", side_effect=_noop), \
                patch.object(CouncilOrchestrator, "_stream_llm_to_queue", new=hanging_member):
            async def consume():
                async for _ in CouncilOrchestrator().run("topic", None, run_id="aborted-run"):
                    pass

            consumer = asyncio.create_task(consume())
            deadline = time.monotonic() + 10
            expected = min(3, orchestrator_module.MAX_PARALLEL_MEMBERS)  # the rest wait on the semaphore
            while len(started) < expected and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            consumer.cancel()  # a disconnect cancels the task that is streaming the run
            with self.assertRaises(asyncio.CancelledError):
                await consumer
        self.assertEqual(len(started), expected)
        self.assertEqual(sorted(cancelled), sorted(started))


class BackgroundTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_drain_waits_for_quick_work_and_cancels_stuck_work(self):
        finished = []

        async def quick():
            await asyncio.sleep(0.05)
            finished.append("quick")

        stuck = shutdown_state.track_background(asyncio.sleep(3600))
        shutdown_state.track_background(quick())
        started = time.monotonic()
        cancelled = await shutdown_state.drain_background(0.5)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual((finished, cancelled), (["quick"], 1))
        self.assertTrue(stuck.cancelled())
        self.assertEqual(shutdown_state._background_tasks, set())

    async def test_failed_background_work_is_logged_not_raised(self):
        async def boom():
            raise RuntimeError("extraction failed")

        with self.assertLogs("shutdown_state", level="WARNING"):
            task = shutdown_state.track_background(boom())
            await asyncio.wait({task})
            await asyncio.sleep(0)


class RecoveryTests(unittest.TestCase):
    def test_runs_left_running_by_a_dead_process_are_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(os.path.join(tmp, "runs.db"))
            store.begin_run("stale", "topic", {}, False)
            store.begin_run("done", "topic", {}, False)
            store.finish_run("done", "completed")
            self.assertEqual(store.mark_interrupted_runs(), 1)
            self.assertEqual(store.get_run("stale")["status"], "interrupted")
            self.assertEqual(store.get_run("done")["status"], "completed")
            self.assertEqual(store.mark_interrupted_runs(), 0)


class BoundedQueryTests(unittest.TestCase):
    def test_negative_or_huge_limits_stay_bounded(self):
        from metrics_store import MetricsStore
        from skill_registry import SkillRegistry

        registry = SkillRegistry(":memory:")
        with registry._connection() as conn:
            for i in range(3):
                conn.execute("INSERT INTO skills (name, body, confidence, used_count, created_at) "
                             "VALUES (?, 'b', 1.0, 0, 0)", (f"s{i}",))
        self.assertEqual(len(registry.list_skills(limit=-1)), 1)  # SQLite would read LIMIT -1 as "all rows"
        self.assertEqual(len(registry.list_skills(limit=10**9)), 3)

        metrics = MetricsStore()
        for _ in range(3):
            metrics.finish_run(metrics.start_run("council"), status="completed")
        self.assertEqual(len(metrics.list_runs(limit=-2)), 1)

        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(os.path.join(tmp, "runs.db"))
            for i in range(3):
                store.begin_run(f"r{i}", "t", {}, False)
            self.assertEqual(len(store.list_runs(limit=-1)), 1)


class LiveAppConcurrencyTests(unittest.TestCase):
    """Real FastAPI stack in a fresh interpreter, so module-level settings apply."""

    def run_script(self, body: str, extra_env: dict):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "PYTHONPATH": SRC, "COUNCIL_DB_PATH": os.path.join(tmp, "runs.db"),
                   "COUNCIL_METRICS_FILE": "", "COUNCIL_API_KEY": "", **extra_env}
            result = subprocess.run([sys.executable, "-c", body], env=env, capture_output=True, text=True,
                                    timeout=300, cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_simultaneous_admissions_and_responsive_health(self):
        body = r'''
import asyncio, json, time, httpx
from council import main
from fastapi.responses import StreamingResponse

async def slow_stream(*args, **kwargs):
    yield 'data: {"type": "phase_start"}\n\n'
    await asyncio.sleep(1.0)
    yield 'data: {"type": "done"}\n\n'

main.stream_council_lifecycle = slow_stream
main.get_project_code_graph = lambda path: (time.sleep(1.5), {"nodes": [], "edges": [], "stats": {}})[1]

async def scenario():
    transport = httpx.ASGITransport(app=main.app, client=("127.0.0.1", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
        runs = await asyncio.gather(*[client.post("/council/stream", data={"topic_text": "x"}) for _ in range(4)])
        statuses = sorted(r.status_code for r in runs)
        graph = asyncio.create_task(client.get("/project/code-graph"))
        await asyncio.sleep(0.2)
        started = time.monotonic()
        health = await client.get("/health")
        health_latency = time.monotonic() - started
        await graph
        after = await client.post("/council/stream", data={"topic_text": "x"})
    return {"statuses": statuses, "health": health.status_code, "latency": health_latency, "after": after.status_code}

print(json.dumps(asyncio.run(scenario())))
'''
        result = self.run_script(body, {"COUNCIL_MAX_CONCURRENT_RUNS": "1"})
        self.assertEqual(result["statuses"], [200, 429, 429, 429])
        self.assertEqual(result["health"], 200)
        self.assertLess(result["latency"], 0.5)  # graph building runs off the event loop
        self.assertEqual(result["after"], 200)  # the slot was released when the first stream ended


if __name__ == "__main__":
    unittest.main()
