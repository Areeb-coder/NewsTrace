"""Regression tests for public URL validation and outbound redirect handling."""

import asyncio
import socket
import unittest
from unittest.mock import patch

from utils.url_safety import (
    install_public_network_guard,
    safe_get,
    validate_public_http_url,
)


def dns_answer(address):
    return [
        (
            socket.AF_INET if ":" not in address else socket.AF_INET6,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 443),
        )
    ]


class PublicUrlValidationTests(unittest.TestCase):
    def test_accepts_public_hostname_when_dns_is_public(self):
        with patch("utils.url_safety.socket.getaddrinfo", return_value=dns_answer("93.184.216.34")):
            self.assertEqual(
                validate_public_http_url("https://news.example/world"),
                "https://news.example/world",
            )

    def test_rejects_private_ip_literal(self):
        for address in (
            "127.0.0.1",
            "10.0.0.5",
            "169.254.169.254",
            "192.168.1.10",
            "::1",
            "fc00::1",
        ):
            with self.subTest(address=address), self.assertRaises(ValueError):
                validate_public_http_url(f"http://[{address}]" if ":" in address else f"http://{address}")

    def test_rejects_hostname_if_any_dns_answer_is_not_global(self):
        answers = dns_answer("93.184.216.34") + dns_answer("10.0.0.9")
        with patch("utils.url_safety.socket.getaddrinfo", return_value=answers):
            with self.assertRaisesRegex(ValueError, "public"):
                validate_public_http_url("https://mixed.example")

    def test_rejects_local_hosts_credentials_and_nonstandard_ports(self):
        invalid = (
            "http://localhost",
            "http://printer.local",
            "http://service.internal",
            "https://user:password@news.example",
            "https://news.example:8443",
            "ftp://news.example",
            "https://",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_public_http_url(value, resolve_dns=False)


class FakeResponse:
    def __init__(self, status_code, url, headers=None, text=""):
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}
        self.text = text
        self.closed = False

    @property
    def is_redirect(self):
        return self.status_code in {301, 302, 303, 307, 308} and bool(self.headers.get("Location"))

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class SafeRedirectTests(unittest.TestCase):
    def test_follows_relative_redirect_after_validating_each_hop(self):
        first = FakeResponse(302, "https://news.example/start", {"Location": "/world"})
        final = FakeResponse(200, "https://news.example/world")
        session = FakeSession([first, final])
        with patch("utils.url_safety.validate_public_http_url", side_effect=lambda value: value) as validate:
            result = safe_get(
                "https://news.example/start",
                session=session,
                timeout=(2, 3),
            )
        self.assertIs(result, final)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(validate.call_count, 2)
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertTrue(first.closed)

    def test_rejects_private_redirect_before_making_second_request(self):
        first = FakeResponse(302, "https://news.example/start", {"Location": "http://127.0.0.1/admin"})
        session = FakeSession([first])
        original_validator = validate_public_http_url

        def validate_only_private_with_real_checker(value):
            if "127.0.0.1" in value:
                return original_validator(value)
            return value

        with patch(
            "utils.url_safety.validate_public_http_url",
            side_effect=validate_only_private_with_real_checker,
        ):
            with self.assertRaises(ValueError):
                safe_get("https://news.example/start", session=session)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(first.closed)

    def test_stops_after_redirect_limit(self):
        redirects = [
            FakeResponse(302, f"https://news{i}.example/", {"Location": f"https://news{i + 1}.example/"})
            for i in range(7)
        ]
        session = FakeSession(redirects)
        with patch("utils.url_safety.validate_public_http_url", side_effect=lambda value: value):
            with self.assertRaisesRegex(RuntimeError, "redirect"):
                safe_get("https://news0.example/", session=session, max_redirects=5)
        self.assertLessEqual(len(session.calls), 6)


class BrowserNetworkGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_aborts_private_request_and_continues_public_request(self):
        class FakeContext:
            async def route(self, pattern, callback):
                self.pattern = pattern
                self.callback = callback

        class FakeRequest:
            def __init__(self, url):
                self.url = url

        class FakeRoute:
            def __init__(self, url):
                self.request = FakeRequest(url)
                self.aborted = False
                self.continued = False

            async def abort(self):
                self.aborted = True

            async def continue_(self):
                self.continued = True

        context = FakeContext()
        await install_public_network_guard(context)
        self.assertEqual(context.pattern, "**/*")

        blocked = FakeRoute("http://127.0.0.1/private")
        allowed = FakeRoute("https://news.example/story")
        with patch("utils.url_safety.validate_public_http_url", side_effect=lambda value: (
            (_ for _ in ()).throw(ValueError("not public")) if "127.0.0.1" in value else value
        )):
            await context.callback(blocked)
            await context.callback(allowed)

        self.assertTrue(blocked.aborted)
        self.assertFalse(blocked.continued)
        self.assertTrue(allowed.continued)
        self.assertFalse(allowed.aborted)

    async def test_allows_browser_local_resource_schemes(self):
        class FakeContext:
            async def route(self, pattern, callback):
                self.callback = callback

        class FakeRequest:
            url = "data:text/plain,news"

        class FakeRoute:
            request = FakeRequest()
            continued = False

            async def continue_(self):
                self.continued = True

        context = FakeContext()
        await install_public_network_guard(context)
        route = FakeRoute()
        await context.callback(route)
        self.assertTrue(route.continued)


if __name__ == "__main__":
    unittest.main()
