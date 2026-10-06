import socket
import unittest
from unittest.mock import patch

import httpx
import io_parser


def dns(address):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]


class URLFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_uses_validated_ip_with_original_host_and_tls_identity(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, content=b"safe", headers={"Content-Type": "text/plain"})

        with patch.object(io_parser.socket, "getaddrinfo", return_value=dns("93.184.216.34")) as resolve:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
                fetched = await io_parser._fetch_url_bytes(client, "https://public.example/docs")
        self.assertEqual(fetched[0], b"safe")
        self.assertEqual(fetched[2], "https://public.example/docs")
        self.assertEqual(str(requests[0].url), "https://93.184.216.34/docs")
        self.assertEqual(requests[0].headers["Host"], "public.example")
        self.assertEqual(requests[0].extensions["sni_hostname"], "public.example")
        self.assertEqual(resolve.call_count, 1)

    async def test_redirect_is_resolved_and_private_target_never_requested(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={"Location": "http://internal.example/admin"})

        with patch.object(io_parser.socket, "getaddrinfo", side_effect=[dns("93.184.216.34"), dns("127.0.0.1")]):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
                fetched = await io_parser._fetch_url_bytes(client, "http://public.example/")
        self.assertIsNone(fetched)
        self.assertEqual(len(requests), 1)

    async def test_mixed_public_private_dns_and_url_credentials_are_rejected(self):
        with patch.object(io_parser.socket, "getaddrinfo", return_value=dns("93.184.216.34") + dns("127.0.0.1")):
            self.assertFalse(io_parser._is_safe_url("https://public.example/"))
        self.assertFalse(io_parser._is_safe_url("https://user:password@public.example/"))

    async def test_disabled_url_fetch_does_not_resolve_or_contact_network(self):
        with patch.dict("os.environ", {"COUNCIL_ALLOW_URL_FETCH": "false"}), \
                patch.object(io_parser.socket, "getaddrinfo") as resolve:
            topic = "Review https://public.example/docs"
            self.assertEqual(await io_parser.parse_input(topic), topic)
        resolve.assert_not_called()
