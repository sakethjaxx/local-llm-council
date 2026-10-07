"""Enforce the browser-to-local-server boundary before routing or body parsing.

Everything here runs before FastAPI reads a request body: FastAPI parses
multipart/JSON bodies *before* resolving route dependencies, so authentication,
size limits and run admission must live at the ASGI layer to protect parsing.
"""

import hmac
import ipaddress
import os
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from shutdown_state import release_run_slot, try_reserve_run_slot

MAX_BODY_BYTES = 52 * 1024 * 1024
# Endpoints that start model work; each holds one run slot from admission until its stream ends.
RUN_PATHS = {"/council/stream", "/council/review-project", "/council/chat"}
_PUBLIC_PREFIXES = ("/static/", "/demo-samples/")


class _BodyTooLarge(Exception):
    pass


def _is_public(method: str, path: str) -> bool:
    """The UI shell and its assets must load before a browser can supply the API key."""
    if method == "OPTIONS":  # CORS preflights never carry custom headers
        return True
    return method in {"GET", "HEAD"} and (path == "/" or path.startswith(_PUBLIC_PREFIXES))


def api_key_valid(provided: str | None) -> bool:
    expected = os.getenv("COUNCIL_API_KEY", "").strip()
    return not expected or hmac.compare_digest((provided or "").encode(), expected.encode())


class BrowserBoundaryMiddleware:
    def __init__(self, app, allowed_origins, max_runs: int = 4, max_body_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.allowed_origins = set(allowed_origins)
        self.max_runs = max_runs
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
        rejection = self._reject(scope, headers)
        if rejection:
            return await JSONResponse({"detail": rejection[1]}, status_code=rejection[0])(scope, receive, send)

        is_run = scope["method"] == "POST" and scope["path"] in RUN_PATHS
        if is_run and not try_reserve_run_slot(self.max_runs):
            detail = f"Server is at maximum capacity ({self.max_runs} active runs). Wait for a run to finish."
            return await JSONResponse({"detail": detail}, status_code=429)(scope, receive, send)
        try:
            await self._call_with_limits(scope, receive, send)
        finally:
            if is_run:
                release_run_slot()

    def _reject(self, scope, headers) -> tuple[int, str] | None:
        host = headers.get("host", "")
        try:
            hostname = urlsplit("http://" + host).hostname
        except ValueError:
            hostname = None
        keyed = bool(os.getenv("COUNCIL_API_KEY", "").strip())
        if not keyed and hostname not in {"localhost", "127.0.0.1", "::1"}:
            return 400, "Untrusted host"
        client = scope.get("client")
        if not keyed and client and client[0] != "testclient":
            try:
                local = ipaddress.ip_address(client[0]).is_loopback
            except ValueError:
                local = False
            if not local:
                return 403, "Remote access requires COUNCIL_API_KEY"
        method, path = scope["method"], scope["path"]
        origin = headers.get("origin")
        same_origin = f"{scope.get('scheme', 'http')}://{host}"
        allowed = origin and (origin == same_origin or origin in self.allowed_origins or "*" in self.allowed_origins)
        if (origin and not allowed) or (headers.get("sec-fetch-site") == "cross-site" and not allowed
                                      and not (method == "GET" and path == "/")):
            return 403, "Untrusted browser origin"
        if not _is_public(method, path) and not api_key_valid(headers.get("x-api-key")):
            return 403, "Forbidden"
        try:
            declared = int(headers.get("content-length", "0") or 0)
        except ValueError:
            return 400, "Invalid Content-Length"
        if declared > self.max_body_bytes:
            return 413, f"Request body exceeds {self.max_body_bytes // (1024 * 1024)} MiB"
        return None

    async def _call_with_limits(self, scope, receive, send):
        received = 0
        too_large = False
        started = False

        async def limited_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:  # also catches chunked bodies with no Content-Length
                    too_large = True
                    raise _BodyTooLarge()
            return message

        async def secure_send(message):
            nonlocal started
            if too_large:
                return  # the app's error response for the aborted body is replaced by a 413
            if message["type"] == "http.response.start":
                started = True
                response_headers = list(message.get("headers", []))
                response_headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                ])
                if scope["path"] != "/" and not scope["path"].startswith(_PUBLIC_PREFIXES):
                    response_headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, limited_receive, secure_send)
        except Exception:
            if not too_large:
                raise
        if too_large and not started:
            detail = f"Request body exceeds {self.max_body_bytes // (1024 * 1024)} MiB"
            await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)
