import os
import unittest
from unittest.mock import patch

from http_security import BrowserBoundaryMiddleware


class BrowserBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, headers=None, client="127.0.0.1", method="GET", path="/health"):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b""}

        request_headers = {"host": "127.0.0.1:8765", **(headers or {})}
        scope = {"type": "http", "scheme": "http", "method": method, "path": path,
                 "client": (client, 1000), "headers": [(k.encode(), v.encode()) for k, v in request_headers.items()]}
        await BrowserBoundaryMiddleware(app, ["http://localhost:8765"])(scope, receive, send)
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

    async def test_keyed_remote_host_passes_to_api_authentication(self):
        with patch.dict(os.environ, {"COUNCIL_API_KEY": "test-key"}):
            messages = await self.request({"host": "council.example", "origin": "http://council.example"}, client="192.168.1.5")
        self.assertEqual(messages[0]["status"], 200)
