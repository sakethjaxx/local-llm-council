"""Enforce the browser-to-local-server boundary before routing or parsing."""

import ipaddress
import os
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


class BrowserBoundaryMiddleware:
    def __init__(self, app, allowed_origins):
        self.app = app
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
        host = headers.get("host", "")
        try:
            hostname = urlsplit("http://" + host).hostname
        except ValueError:
            hostname = None
        keyed = bool(os.getenv("COUNCIL_API_KEY", "").strip())
        if not keyed and hostname not in {"localhost", "127.0.0.1", "::1"}:
            return await JSONResponse({"detail": "Untrusted host"}, status_code=400)(scope, receive, send)
        client = scope.get("client")
        if not keyed and client and client[0] != "testclient":
            try:
                local = ipaddress.ip_address(client[0]).is_loopback
            except ValueError:
                local = False
            if not local:
                return await JSONResponse({"detail": "Remote access requires COUNCIL_API_KEY"}, status_code=403)(scope, receive, send)
        origin = headers.get("origin")
        same_origin = f"{scope.get('scheme', 'http')}://{host}"
        allowed = origin and (origin == same_origin or origin in self.allowed_origins or "*" in self.allowed_origins)
        if (origin and not allowed) or (headers.get("sec-fetch-site") == "cross-site" and not allowed
                                      and not (scope["method"] == "GET" and scope["path"] == "/")):
            return await JSONResponse({"detail": "Untrusted browser origin"}, status_code=403)(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                ])
                if scope["path"] != "/" and not scope["path"].startswith(("/static/", "/demo-samples/")):
                    response_headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, receive, secure_send)
