"""Regression tests for public-source validation and discovery throttling."""

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.main import (
    _check_discovery_rate_limit,
    _start_attempts,
    _validate_public_http_url,
)


class PublicSourceValidationTests(unittest.TestCase):
    def test_accepts_public_http_and_https_urls(self):
        self.assertEqual(
            _validate_public_http_url("https://example.com/world"),
            "https://example.com/world",
        )
        self.assertEqual(
            _validate_public_http_url("http://example.com/news"),
            "http://example.com/news",
        )

    def test_rejects_non_http_schemes_and_missing_hosts(self):
        for value in ("ftp://example.com", "javascript:alert(1)", "https://"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _validate_public_http_url(value)

    def test_rejects_local_internal_and_private_ip_targets(self):
        targets = (
            "http://localhost",
            "http://service.local",
            "http://metadata.internal",
            "http://127.0.0.1",
            "http://10.0.0.5",
            "http://169.254.169.254",
            "http://192.168.1.10",
        )
        for value in targets:
            with self.subTest(value=value), self.assertRaises(ValueError):
                _validate_public_http_url(value)

    def test_rejects_credentials_and_nonstandard_ports(self):
        with self.assertRaises(ValueError):
            _validate_public_http_url("https://user:password@example.com/")
        with self.assertRaises(ValueError):
            _validate_public_http_url("http://example.com:8080/")


class DiscoveryRateLimitTests(unittest.TestCase):
    def setUp(self):
        _start_attempts.clear()

    def tearDown(self):
        _start_attempts.clear()

    def test_limits_discovery_starts_per_client(self):
        with patch("backend.main.DISCOVERY_START_LIMIT", 2):
            _check_discovery_rate_limit("198.51.100.10")
            _check_discovery_rate_limit("198.51.100.10")
            with self.assertRaises(HTTPException) as raised:
                _check_discovery_rate_limit("198.51.100.10")
            self.assertEqual(raised.exception.status_code, 429)

    def test_clients_have_independent_start_limits(self):
        with patch("backend.main.DISCOVERY_START_LIMIT", 1):
            _check_discovery_rate_limit("198.51.100.10")
            _check_discovery_rate_limit("198.51.100.11")
            with self.assertRaises(HTTPException):
                _check_discovery_rate_limit("198.51.100.10")


if __name__ == "__main__":
    unittest.main()
