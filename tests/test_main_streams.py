import importlib
import asyncio
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
from cloud_keys import get_cloud_keys
from metrics_store import metrics_store
from shutdown_state import clear_shutdown_request


class MainStreamsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with metrics_store._lock:
            metrics_store._active_runs.clear()
            metrics_store._recent_runs.clear()
        clear_shutdown_request()
        self.empty_request = type("Req", (), {"headers": {}})()

    async def _read_stream(self, response):
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    async def test_background_task_completion_ignores_cancellation(self):
        task = asyncio.create_task(asyncio.sleep(60))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        main._consume_background_task(task)

    async def test_project_review_records_failed_run_when_models_are_missing(self):
        graph = {"stats": {"files": 1}, "nodes": [{"id": "app.py"}], "review_input": "Review app"}
        missing = {"ready": False, "missing": ["qwen2.5:7b"], "installed": [], "required": ["qwen2.5:7b"]}
        request = main.ReviewProjectRequest(path=tempfile.gettempdir())

        with patch.object(main, "get_project_code_graph", return_value=graph), \
             patch.object(main, "_pick_top_files", return_value=["app.py"]), \
             patch.object(main, "_read_files_as_attachments", return_value=[{"filename": "app.py", "kind": "text", "text": "x"}]), \
             patch.object(main, "ensure_models_for_config", return_value=missing), \
             patch.object(main.metrics_store, "start_run", return_value="project-run"), \
             patch.object(main.metrics_store, "finish_run") as finish_run:
            response = await main.review_project(request, self.empty_request)
            payload = await self._read_stream(response)

        self.assertIn("Missing models", payload)
        finish_run.assert_called_once_with(
            "project-run", status="failed", error="Missing Ollama models: qwen2.5:7b"
        )

    async def test_council_stream_emits_run_started_and_done(self):
        async def fake_run(self, topic_text, attachments, custom_config=None, deep_debate=False, run_id=None, token_budget_profile=None):
            yield {"type": "phase_start", "phase": 1, "label": "Independent Analysis"}
            yield {"type": "done"}

        ready_status = {
            "provider": "ollama",
            "required": ["qwen2.5:7b"],
            "installed": ["qwen2.5:7b"],
            "missing": [],
            "pulled": [],
            "ready": True,
            "auto_pull_enabled": False,
        }
        with patch.object(main, "ensure_models_for_config", return_value=ready_status), \
             patch.object(main.CouncilOrchestrator, "run", new=fake_run):
            response = await main.council_stream(self.empty_request, topic_text="check this")
            payload = await self._read_stream(response)

        self.assertIn('"type": "run_started"', payload)
        self.assertIn('"type": "model_status"', payload)
        self.assertIn('"type": "done"', payload)

    async def test_council_stream_scopes_cloud_keys_to_request(self):
        captured = {}

        class FakeRequest:
            headers = {"x-openai-api-key": "sk-test123", "x-anthropic-api-key": "sk-ant-456"}

        async def fake_run(self, topic_text, attachments, custom_config=None, deep_debate=False, run_id=None, token_budget_profile=None):
            captured["keys"] = get_cloud_keys()
            captured["profile"] = token_budget_profile
            yield {"type": "done"}

        ready_status = {
            "provider": "ollama",
            "required": ["qwen2.5:7b"],
            "installed": ["qwen2.5:7b"],
            "missing": [],
            "pulled": [],
            "ready": True,
            "auto_pull_enabled": False,
        }
        with patch.object(main, "ensure_models_for_config", return_value=ready_status), \
             patch.object(main.CouncilOrchestrator, "run", new=fake_run):
            response = await main.council_stream(request=FakeRequest(), topic_text="check this")
            await self._read_stream(response)

        self.assertEqual(captured["keys"]["openai"], "sk-test123")
        self.assertEqual(captured["keys"]["anthropic"], "sk-ant-456")
        self.assertEqual(captured["profile"], "balanced")
        self.assertEqual(get_cloud_keys(), {})

    async def test_council_stream_reports_missing_models(self):
        missing_status = {
            "provider": "ollama",
            "required": ["qwen2.5:7b", "gemma2:9b"],
            "installed": ["qwen2.5:7b"],
            "missing": ["gemma2:9b"],
            "pulled": [],
            "ready": False,
            "auto_pull_enabled": False,
        }
        with patch.object(main, "ensure_models_for_config", return_value=missing_status):
            response = await main.council_stream(self.empty_request, topic_text="check this")
            payload = await self._read_stream(response)

        self.assertIn('"type": "model_status"', payload)
        self.assertIn('Missing Ollama models: gemma2:9b', payload)
        self.assertEqual(len(metrics_store._active_runs), 0)
        self.assertEqual(metrics_store._recent_runs[0]["status"], "failed")

    async def test_council_stream_emits_shutdown_event(self):
        async def fake_run(self, topic_text, attachments, custom_config=None, deep_debate=False, run_id=None, token_budget_profile=None):
            yield {"type": "shutdown", "message": "bye"}

        ready_status = {
            "provider": "ollama",
            "required": ["qwen2.5:7b"],
            "installed": ["qwen2.5:7b"],
            "missing": [],
            "pulled": [],
            "ready": True,
            "auto_pull_enabled": False,
        }
        with patch.object(main, "ensure_models_for_config", return_value=ready_status), \
             patch.object(main.CouncilOrchestrator, "run", new=fake_run):
            response = await main.council_stream(self.empty_request, topic_text="check this")
            payload = await self._read_stream(response)

        self.assertIn('"type": "shutdown"', payload)

    async def test_council_stream_passes_uploaded_attachments(self):
        captured = {}

        async def fake_run(self, topic_text, attachments, custom_config=None, deep_debate=False, run_id=None, token_budget_profile=None):
            captured["topic_text"] = topic_text
            captured["attachments"] = attachments
            captured["profile"] = token_budget_profile
            yield {"type": "done"}

        ready_status = {
            "provider": "ollama",
            "required": ["qwen2.5:7b"],
            "installed": ["qwen2.5:7b"],
            "missing": [],
            "pulled": [],
            "ready": True,
            "auto_pull_enabled": False,
        }
        uploads = [
            main.UploadFile(filename="notes.md", content_type="text/markdown", body=b"# Notes\nhello"),
            main.UploadFile(filename="photo.png", content_type="image/png", body=b"\x89PNG"),
        ]

        with patch.object(main, "ensure_models_for_config", return_value=ready_status), \
             patch.object(main.CouncilOrchestrator, "run", new=fake_run):
            response = await main.council_stream(self.empty_request, topic_text="review these", attachments=uploads)
            await self._read_stream(response)

        self.assertEqual(captured["topic_text"], "review these")
        self.assertEqual(len(captured["attachments"]), 2)
        self.assertEqual(captured["attachments"][0]["kind"], "text")
        self.assertEqual(captured["attachments"][1]["kind"], "image")
        self.assertIn("data", captured["attachments"][1])
        self.assertEqual(captured["profile"], "balanced")

    async def test_council_stream_keeps_hardware_models_when_swarm_personas_are_generated(self):
        ready_status = {
            "provider": "ollama",
            "required": ["qwen2.5:7b"],
            "installed": ["qwen2.5:7b"],
            "missing": [],
            "pulled": [],
            "ready": True,
            "auto_pull_enabled": False,
        }
        captured = {}

        async def fake_run(self, topic_text, attachments, custom_config=None, deep_debate=False, run_id=None, token_budget_profile=None):
            captured["config"] = custom_config
            captured["profile"] = token_budget_profile
            yield {"type": "done"}

        with patch.object(main, "ensure_models_for_config", return_value=ready_status), \
             patch("router_agent.generate_swarm", return_value={
                 "architect": {"label": "A", "model": "ollama/qwen2.5:7b", "color": "#111", "icon": "A", "persona": "a"},
                 "security": {"label": "S", "model": "ollama/gemma2:9b", "color": "#222", "icon": "S", "persona": "s"},
                 "perf": {"label": "P", "model": "ollama/qwen2.5:7b", "color": "#333", "icon": "P", "persona": "p"},
             }), \
             patch.object(main.CouncilOrchestrator, "run", new=fake_run):
            response = await main.council_stream(self.empty_request, topic_text="route me", dynamic_swarm=True)
            payload = await self._read_stream(response)

        self.assertIn('"type": "swarm_routed"', payload)
        self.assertIn("architect", captured["config"])
        self.assertEqual(captured["config"]["architect"]["label"], "A")
        self.assertEqual(captured["config"]["architect"]["model"], "ollama/qwen2.5:7b")
        self.assertEqual(captured["profile"], "balanced")

    async def test_council_stream_warns_and_falls_back_when_swarm_generation_fails(self):
        ready_status = {
            "provider": "ollama",
            "required": ["qwen2.5:7b"],
            "installed": ["qwen2.5:7b"],
            "missing": [],
            "pulled": [],
            "ready": True,
            "auto_pull_enabled": False,
        }
        seen = {}

        async def fake_run(self, topic_text, attachments, custom_config=None, deep_debate=False, run_id=None, token_budget_profile=None):
            seen["label"] = custom_config["architect"]["label"]
            seen["profile"] = token_budget_profile
            yield {"type": "done"}

        with patch.object(main, "ensure_models_for_config", return_value=ready_status), \
             patch("router_agent.generate_swarm", return_value=None), \
             patch.object(main.CouncilOrchestrator, "run", new=fake_run):
            response = await main.council_stream(self.empty_request, topic_text="route me", dynamic_swarm=True)
            payload = await self._read_stream(response)

        self.assertIn('Dynamic Swarm failed. Keeping the selected roster and personas.', payload)
        self.assertEqual(seen["label"], "Lead Architect")
        self.assertEqual(seen["profile"], "balanced")

    async def test_ollama_check_reports_warnings(self):
        ready_status = {
            "provider": "ollama",
            "required": ["qwen2.5:7b"],
            "installed": ["qwen2.5:7b"],
            "missing": [],
            "pulled": [],
            "ready": True,
            "auto_pull_enabled": False,
        }
        request = main.ConfigCheckRequest(
            council_config={
                "architect": {"label": "Architect", "model": "ollama/qwen2.5:7b"},
                "chairman": {"label": "Chairman", "model": "ollama/qwen2.5:7b"},
            },
            attachment_names=["screen.png"],
        )
        with patch.object(main, "ensure_models_for_config", return_value=ready_status):
            body = await main.ollama_check(request)

        self.assertEqual(body["ready"], True)
        self.assertEqual(body["image_seats"], [])
        self.assertEqual(len(body["warnings"]), 1)

    async def test_council_chat_emits_run_started_and_done(self):
        async def fake_chat(self, member_id, messages, custom_config=None, run_id=None, token_budget_profile=None):
            yield "hello"

        request = main.ChatRequest(
            member_id="architect",
            messages=[main.ChatMessage(role="user", content="hello")],
        )

        with patch.object(main.CouncilOrchestrator, "chat_with_member", new=fake_chat):
            response = await main.council_chat(request, self.empty_request)
            payload = await self._read_stream(response)

        self.assertIn('"type": "run_started"', payload)
        self.assertIn('"type": "chat_done"', payload)
        self.assertIn('"chunk": "hello"', payload)

    def test_confine_to_project_root_blocks_escape(self):
        from fastapi import HTTPException

        with patch.dict(os.environ, {"COUNCIL_PROJECT_ROOT": "/home/user/local-llm-council"}):
            ok = main._confine_to_project_root("/home/user/local-llm-council/main.py")
            self.assertTrue(ok.startswith(os.path.realpath("/home/user/local-llm-council")))
            with self.assertRaises(HTTPException) as ctx:
                main._confine_to_project_root("/etc/passwd")
            self.assertEqual(ctx.exception.status_code, 403)

    def test_confine_to_project_root_blocks_symlink_escape(self):
        from fastapi import HTTPException
        import tempfile

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            escaped = os.path.join(root, "outside-link")
            os.symlink(outside, escaped)
            with patch.dict(os.environ, {"COUNCIL_PROJECT_ROOT": root}):
                with self.assertRaises(HTTPException) as ctx:
                    main._confine_to_project_root(escaped)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_confine_to_project_root_blocks_sensitive_prefixes_when_root_unset(self):
        from fastapi import HTTPException

        env = dict(os.environ)
        env.pop("COUNCIL_PROJECT_ROOT", None)
        with patch.dict(os.environ, env, clear=True):
            for blocked_path in ("/etc/shadow", "/etc", "/sys/devices", os.path.expanduser("~/.ssh/id_rsa")):
                with self.assertRaises(HTTPException) as ctx:
                    main._confine_to_project_root(blocked_path)
                self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
