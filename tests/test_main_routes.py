import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


def _install_test_stubs():
    if "litellm" not in sys.modules:
        litellm_stub = types.ModuleType("litellm")
        litellm_stub.suppress_debug_info = False

        async def _unused_acompletion(*args, **kwargs):
            raise RuntimeError("litellm stub should not be called in tests")

        litellm_stub.acompletion = _unused_acompletion
        sys.modules["litellm"] = litellm_stub

    if "dotenv" not in sys.modules:
        dotenv_stub = types.ModuleType("dotenv")
        dotenv_stub.load_dotenv = lambda *args, **kwargs: None
        sys.modules["dotenv"] = dotenv_stub

    if "main" not in sys.modules:
        fastapi_stub = types.ModuleType("fastapi")

        class FakeFastAPI:
            def __init__(self, *args, **kwargs):
                self.routes = []

            def add_middleware(self, *args, **kwargs):
                return None

            def mount(self, *args, **kwargs):
                return None

            def get(self, *args, **kwargs):
                def decorator(func):
                    self.routes.append(("GET", args, kwargs, func))
                    return func

                return decorator

            def post(self, *args, **kwargs):
                def decorator(func):
                    self.routes.append(("POST", args, kwargs, func))
                    return func

                return decorator

            def delete(self, *args, **kwargs):
                def decorator(func):
                    self.routes.append(("DELETE", args, kwargs, func))
                    return func

                return decorator

        class UploadFile:
            def __init__(self, filename="", content_type="application/octet-stream", body=b""):
                self.filename = filename
                self.content_type = content_type
                self._body = body

            async def read(self, size=-1):
                if size is None or size < 0:
                    return self._body
                return self._body[:size]

        fastapi_stub.FastAPI = FakeFastAPI
        fastapi_stub.Depends = lambda dependency=None: dependency
        fastapi_stub.File = lambda default=None: default
        fastapi_stub.Form = lambda default=None: default
        fastapi_stub.Header = lambda default=None: default
        fastapi_stub.HTTPException = type(
            "HTTPException",
            (Exception,),
            {
                "__init__": lambda self, status_code=500, detail=None: (
                    setattr(self, "status_code", status_code),
                    setattr(self, "detail", detail),
                    Exception.__init__(self, detail),
                )[-1]
            },
        )
        fastapi_stub.Request = object
        fastapi_stub.UploadFile = UploadFile
        sys.modules["fastapi"] = fastapi_stub

        cors_module = types.ModuleType("fastapi.middleware.cors")
        cors_module.CORSMiddleware = object
        sys.modules["fastapi.middleware.cors"] = cors_module

        responses_module = types.ModuleType("fastapi.responses")

        class HTMLResponse(str):
            pass

        class StreamingResponse:
            def __init__(self, body_iterator, media_type=None, headers=None):
                self.body_iterator = body_iterator
                self.media_type = media_type
                self.headers = headers or {}

        class Response:
            def __init__(self, content=b"", media_type=None, headers=None, status_code=200):
                self.body = content if isinstance(content, bytes) else str(content).encode("utf-8")
                self.media_type = media_type
                self.headers = headers or {}
                self.status_code = status_code

        responses_module.HTMLResponse = HTMLResponse
        responses_module.Response = Response
        responses_module.StreamingResponse = StreamingResponse
        sys.modules["fastapi.responses"] = responses_module

        staticfiles_module = types.ModuleType("fastapi.staticfiles")

        class StaticFiles:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        staticfiles_module.StaticFiles = StaticFiles
        sys.modules["fastapi.staticfiles"] = staticfiles_module


_install_test_stubs()
os.environ["COUNCIL_METRICS_FILE"] = ""
main = importlib.import_module("main")
from metrics_store import metrics_store
from shutdown_state import clear_shutdown_request


class MainRoutesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with metrics_store._lock:
            metrics_store._active_runs.clear()
            metrics_store._recent_runs.clear()
        clear_shutdown_request()

    async def _read_stream(self, response):
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    async def test_health_reports_feature_flags(self):
        body = await main.health()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(set(body.keys()), {"status"})

    async def test_status_reports_operational_detail(self):
        body = await main.status()
        self.assertIn("ollama", body)
        self.assertIn("db", body)
        self.assertIn("keys_configured", body)
        self.assertIn("python_tool_enabled", body["features"])

    async def test_status_requires_configured_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(main.HTTPException) as ctx:
                main.require_api_key(None)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_ollama_status_endpoint(self):
        fake_status = {
            "provider": "ollama",
            "required": ["qwen2.5:7b"],
            "installed": ["qwen2.5:7b"],
            "missing": [],
            "pulled": [],
            "ready": True,
            "auto_pull_enabled": False,
        }
        with patch.object(main, "ensure_models_for_config", return_value=fake_status):
            body = await main.ollama_status()
        self.assertEqual(body["ready"], True)
        self.assertEqual(body["required"], ["qwen2.5:7b"])

    async def test_models_catalog_endpoint_delegates_to_hardware_detect(self):
        fake_catalog = {"ram_gb": 32.0, "budget_gb": 22.0, "models": []}
        with patch.object(main, "get_model_catalog", return_value=fake_catalog):
            body = await main.models_catalog()
        self.assertEqual(body, fake_catalog)

    async def test_hardware_suggestion_forwards_requested_roster_strategy(self):
        expected = {"strategy": "mixed", "config": {}}
        with patch.object(main, "get_hardware_suggestion", return_value=expected) as suggest:
            body = await main.hardware_suggest(strategy="mixed")
        self.assertEqual(body, expected)
        suggest.assert_called_once_with(strategy="mixed")

    async def test_models_pull_stream_rejects_unknown_tag(self):
        with self.assertRaises(main.HTTPException) as ctx:
            await main.models_pull_stream(tag="not-a-real-model:1b")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_models_pull_stream_streams_known_tag(self):
        async def fake_pull_stream(tag):
            yield {"type": "line", "text": "pulling manifest"}
            yield {"type": "done", "success": True, "returncode": 0}

        with patch.object(main, "pull_model_stream", new=fake_pull_stream):
            response = await main.models_pull_stream(tag="qwen2.5:7b")
            payload = await self._read_stream(response)

        self.assertIn('"pulling manifest"', payload)
        self.assertIn('"success": true', payload)

    async def test_metrics_endpoints_return_recorded_runs(self):
        run_id = metrics_store.start_run("council", {"deep_debate": False}, run_id="metrics-run")
        metrics_store.record_llm_call(
            run_id=run_id,
            member_id="architect",
            phase=1,
            model="openrouter/test-model",
            label="Architect",
            attempt=1,
            duration_ms=123,
            success=True,
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        )
        metrics_store.finish_run(run_id, status="completed")

        runs = await main.get_runs(limit=5)
        summary = await main.get_metrics_summary()

        self.assertEqual(runs["runs"][0]["run_id"], "metrics-run")
        self.assertEqual(summary["completed_runs"], 1)
        self.assertIn("openrouter/test-model", summary["by_model"])

    async def test_metrics_quality_endpoint_delegates_to_run_store(self):
        expected = {"runs": [{"run_id": "r1"}], "summary": {"runs_seen": 1}}
        with patch.object(main.run_store, "list_quality_metrics", return_value=expected) as quality:
            body = await main.get_metrics_quality(limit=25)
        self.assertEqual(body, expected)
        quality.assert_called_once_with(25)

    async def test_project_code_graph_endpoint(self):
        body = await main.project_code_graph()
        self.assertIn("nodes", body)
        self.assertIn("edges", body)
        self.assertIn("summary", body)
        self.assertIn("PROJECT CODE GRAPH", body["summary"])

    async def test_demo_catalog_endpoint(self):
        body = await main.demo_catalog()
        self.assertIn("presets", body)
        self.assertIn("samples", body)
        self.assertGreaterEqual(len(body["presets"]), 3)

    async def test_config_presets_endpoint(self):
        body = await main.config_presets()
        self.assertIn("presets", body)
        self.assertGreater(len(body["presets"]), 0)

    async def test_run_endpoints_delegate_to_store(self):
        with patch.object(main.run_store, "list_runs", return_value=[{"run_id": "r1"}]) as list_runs:
            listed = await main.list_persisted_runs(limit=10)
        self.assertEqual(listed["runs"][0]["run_id"], "r1")
        list_runs.assert_called_once()

        with patch.object(main.run_store, "get_run", return_value={"run_id": "r1"}) as get_run:
            detail = await main.get_persisted_run("r1")
        self.assertEqual(detail["run_id"], "r1")
        get_run.assert_called_once_with("r1")

        with patch.object(main.run_store, "delete_run", return_value=True):
            deleted = await main.delete_persisted_run("r1")
        self.assertEqual(deleted, {"run_id": "r1", "deleted": True})

        request = main.FeedbackRequest(action_index=0, rating="thumbs_up", note="useful")
        with patch.object(main.run_store, "run_exists", return_value=True), \
             patch.object(main.run_store, "record_feedback") as record_feedback:
            feedback = await main.record_run_feedback("r1", request)
        self.assertEqual(feedback["recorded"], True)
        record_feedback.assert_called_once_with("r1", 0, "thumbs_up", "useful")

    async def test_unknown_run_endpoints_return_404(self):
        with patch.object(main.run_store, "get_run", return_value={}):
            with self.assertRaises(main.HTTPException) as ctx:
                await main.get_persisted_run("nope")
        self.assertEqual(ctx.exception.status_code, 404)

        with patch.object(main.run_store, "delete_run", return_value=False):
            with self.assertRaises(main.HTTPException) as ctx:
                await main.delete_persisted_run("nope")
        self.assertEqual(ctx.exception.status_code, 404)

        with patch.object(main.run_store, "delete_all_runs", return_value=5):
            res = await main.delete_all_persisted_runs()
            self.assertEqual(res["deleted_count"], 5)
            self.assertEqual(res["deleted"], True)

        request = main.FeedbackRequest(action_index=0, rating="thumbs_down")
        with patch.object(main.run_store, "run_exists", return_value=False):
            with self.assertRaises(main.HTTPException) as ctx:
                await main.record_run_feedback("nope", request)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_feedback_request_rejects_invalid_rating(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            main.FeedbackRequest(action_index=0, rating="up")

    async def test_export_run_endpoint_supports_markdown_json_and_zip(self):
        run = {
            "run_id": "r1",
            "status": "completed",
            "topic": "Review this change",
            "roster": {"chairman": {"label": "Chairman"}},
            "phases": [
                {"phase": 3, "member_id": "chairman", "output": '{"verdict":"ship","risk_score":2,"action_items":["test"]}'}
            ],
            "feedback": [],
        }
        metrics = {"run_id": "r1", "totals": {"prompt_tokens": 10}}

        with patch.object(main.run_store, "get_run", return_value=run), \
             patch.object(main, "_metrics_run_for_export", return_value=metrics):
            md_response = await main.export_persisted_run("r1", format="md")
            json_response = await main.export_persisted_run("r1", format="json")
            zip_response = await main.export_persisted_run("r1", format="zip")

        self.assertEqual(md_response.media_type, "text/markdown")
        self.assertIn(b"# Council Run Export", md_response.body)
        self.assertEqual(json_response.media_type, "application/json")
        self.assertIn(b'"run_id": "r1"', json_response.body)
        self.assertEqual(zip_response.media_type, "application/zip")
        self.assertGreater(len(zip_response.body), 0)

    async def test_ingest_folder_endpoint_confines_path_and_clamps_file_count(self):
        with patch.dict(os.environ, {"COUNCIL_PROJECT_ROOT": "/home/user/local-llm-council"}):
            with self.assertRaises(main.HTTPException) as ctx:
                await main.ingest_local_folder(
                    main.FolderIngestRequest(folder_path="/etc", max_files=3)
                )
            self.assertEqual(ctx.exception.status_code, 403)

        with patch.object(main, "ingest_folder", return_value=[]) as ingest:
            await main.ingest_local_folder(
                main.FolderIngestRequest(folder_path=".", max_files=999)
            )
        self.assertEqual(ingest.call_args.args[1], 200)

    def test_reject_if_overloaded_returns_429(self):
        from fastapi import HTTPException

        with patch.object(main, "active_stream_count", return_value=main.MAX_CONCURRENT_STREAMS):
            with self.assertRaises(HTTPException) as ctx:
                main._reject_if_overloaded()
            self.assertEqual(ctx.exception.status_code, 429)

        with patch.object(main, "active_stream_count", return_value=0):
            main._reject_if_overloaded()


if __name__ == "__main__":
    unittest.main()
