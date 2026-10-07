import asyncio
import os
import unittest
from unittest.mock import patch

import shutdown_state
from http_security import BrowserBoundaryMiddleware


async def ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class BrowserBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        while shutdown_state.active_stream_count():
            shutdown_state.release_run_slot()

    async def request(self, headers=None, client="127.0.0.1", method="GET", path="/health",
                      app=ok_app, body_chunks=(b"",), max_runs=4, max_body_bytes=1024):
        messages = []
        chunks = list(body_chunks)
        self.receive_calls = 0

        async def send(message):
            messages.append(message)

        async def receive():
            self.receive_calls += 1
            body = chunks.pop(0) if chunks else b""
            return {"type": "http.request", "body": body, "more_body": bool(chunks)}

        request_headers = {"host": "127.0.0.1:8765", **(headers or {})}
        scope = {"type": "http", "scheme": "http", "method": method, "path": path,
                 "client": (client, 1000), "headers": [(k.encode(), v.encode()) for k, v in request_headers.items()]}
        middleware = BrowserBoundaryMiddleware(app, ["http://localhost:8765"], max_runs=max_runs,
                                               max_body_bytes=max_body_bytes)
        await middleware(scope, receive, send)
        return messages

    async def test_cross_origin_form_post_rejected_before_app(self):
        with patch.dict(os.environ, {"COUNCIL_API_KEY": ""}):
            messages = await self.request({"origin": "https://attacker.example"}, method="POST", path="/council/stream")
        self.assertEqual(messages[0]["status"], 403)

    async def test_rebinding_host_and_remote_peer_rejected_without_key(self):
        with patch.dict(os.environ, {"COUNCIL_API_KEY": ""}):
            host = await self.request({"host": "attacker.example"})
            remote = await self.request(client="192.168.1.5")
        self.assertEqual(host[0]["status"], 400)
        self.assertEqual(remote[0]["status"], 403)

    async def test_cross_site_model_download_rejected_without_origin(self):
        with patch.dict(os.environ, {"COUNCIL_API_KEY": ""}):
            messages = await self.request({"sec-fetch-site": "cross-site"}, path="/models/pull/stream")
        self.assertEqual(messages[0]["status"], 403)

    async def test_same_origin_custom_port_and_safe_headers(self):
        with patch.dict(os.environ, {"COUNCIL_API_KEY": ""}):
            messages = await self.request({"host": "localhost:8799", "origin": "http://localhost:8799"}, method="POST")
        self.assertEqual(messages[0]["status"], 200)
        headers = dict(messages[0]["headers"])
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(headers[b"x-frame-options"], b"DENY")
        csp = headers[b"content-security-policy"].decode()
        for directive in ("default-src 'self'", "connect-src 'self'", "img-src 'self' data: blob:",
                          "object-src 'none'", "frame-ancestors 'none'", "base-uri 'none'"):
            self.assertIn(directive, csp)
        self.assertNotIn("http", csp)  # no third-party origins anywhere

    async def test_keyed_remote_host_requires_the_key(self):
        remote = {"host": "council.example", "origin": "http://council.example"}
        with patch.dict(os.environ, {"COUNCIL_API_KEY": "test-key"}):
            missing = await self.request(remote, client="192.168.1.5")
            wrong = await self.request({**remote, "x-api-key": "nope"}, client="192.168.1.5")
            good = await self.request({**remote, "x-api-key": "test-key"}, client="192.168.1.5")
        self.assertEqual(missing[0]["status"], 403)
        self.assertEqual(wrong[0]["status"], 403)
        self.assertEqual(good[0]["status"], 200)

    async def test_unauthenticated_upload_is_rejected_before_the_body_is_read(self):
        reached = []

        async def parsing_app(scope, receive, send):
            reached.append(await receive())
            await ok_app(scope, receive, send)

        with patch.dict(os.environ, {"COUNCIL_API_KEY": "test-key"}):
            messages = await self.request(method="POST", path="/council/stream", app=parsing_app,
                                          body_chunks=[b"x" * 100])
        self.assertEqual(messages[0]["status"], 403)
        self.assertEqual(reached, [])
        self.assertEqual(self.receive_calls, 0)
        self.assertEqual(shutdown_state.active_stream_count(), 0)

    async def test_ui_shell_and_assets_stay_public_when_keyed(self):
        with patch.dict(os.environ, {"COUNCIL_API_KEY": "test-key"}):
            for path in ("/", "/static/app.js", "/demo-samples/brief.md"):
                self.assertEqual((await self.request(path=path))[0]["status"], 200, path)
            self.assertEqual((await self.request(method="OPTIONS", path="/council/stream"))[0]["status"], 200)
            self.assertEqual((await self.request(path="/runs"))[0]["status"], 403)
            self.assertEqual((await self.request(method="POST", path="/"))[0]["status"], 403)

    async def test_declared_oversize_body_gets_413_without_reaching_the_app(self):
        called = []

        async def app(scope, receive, send):
            called.append(True)
            await ok_app(scope, receive, send)

        with patch.dict(os.environ, {"COUNCIL_API_KEY": ""}):
            messages = await self.request({"content-length": "2048"}, method="POST", path="/council/stream", app=app)
        self.assertEqual(messages[0]["status"], 413)
        self.assertEqual(called, [])
        self.assertEqual(shutdown_state.active_stream_count(), 0)

    async def test_chunked_body_over_the_limit_gets_413_and_the_app_reply_is_dropped(self):
        async def reading_app(scope, receive, send):
            try:
                while (await receive()).get("more_body"):
                    pass
            except Exception:
                # Frameworks turn parse failures into their own error response.
                await send({"type": "http.response.start", "status": 400, "headers": []})
                await send({"type": "http.response.body", "body": b"parse error"})
                return
            await ok_app(scope, receive, send)

        with patch.dict(os.environ, {"COUNCIL_API_KEY": ""}):
            messages = await self.request(method="POST", path="/council/stream", app=reading_app,
                                          body_chunks=[b"x" * 600, b"x" * 600])
            within = await self.request(method="POST", path="/council/stream", app=reading_app,
                                        body_chunks=[b"x" * 500, b"x" * 500])
        self.assertEqual([m["status"] for m in messages if m["type"] == "http.response.start"], [413])
        self.assertEqual(within[0]["status"], 200)
        self.assertEqual(shutdown_state.active_stream_count(), 0)

    async def test_run_admission_is_atomic_and_released_on_every_exit(self):
        gate = asyncio.Event()

        async def slow_app(scope, receive, send):
            await gate.wait()
            await ok_app(scope, receive, send)

        async def failing_app(scope, receive, send):
            raise RuntimeError("boom")

        with patch.dict(os.environ, {"COUNCIL_API_KEY": ""}):
            runs = [asyncio.create_task(self.request(method="POST", path="/council/stream", app=slow_app, max_runs=2))
                    for _ in range(5)]
            await asyncio.sleep(0.05)
            self.assertEqual(shutdown_state.active_stream_count(), 2)
            # Non-run endpoints never consume run slots.
            self.assertEqual((await self.request(path="/runs", max_runs=2))[0]["status"], 200)
            gate.set()
            statuses = sorted([(await task)[0]["status"] for task in runs])
            self.assertEqual(statuses, [200, 200, 429, 429, 429])
            self.assertEqual(shutdown_state.active_stream_count(), 0)

            with self.assertRaises(RuntimeError):
                await self.request(method="POST", path="/council/chat", app=failing_app)
            self.assertEqual(shutdown_state.active_stream_count(), 0)

            blocked = asyncio.create_task(self.request(method="POST", path="/council/review-project", app=slow_app))
            gate.clear()
            await asyncio.sleep(0.05)
            blocked.cancel()  # client disconnect cancels the request task
            with self.assertRaises(asyncio.CancelledError):
                await blocked
            self.assertEqual(shutdown_state.active_stream_count(), 0)


if __name__ == "__main__":
    unittest.main()
