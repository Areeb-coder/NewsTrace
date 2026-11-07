"""Regression tests for optional publication API endpoint discovery."""

import unittest
from unittest.mock import patch
from urllib.parse import urlparse

import requests

from scrapers.api_scraper import find_api_endpoints, try_api_scraping


class FakeResponse:
    def __init__(self, status_code=404, headers=None):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html"}

    def json(self):
        raise ValueError("not JSON")


class ApiEndpointDiscoveryTests(unittest.TestCase):
    def test_does_not_guess_api_subdomain_from_www_publication_host(self):
        endpoints = find_api_endpoints("https://www.thehindu.com")
        hosts = {urlparse(endpoint).hostname for endpoint in endpoints}

        self.assertEqual(len(endpoints), 6)
        self.assertEqual(hosts, {"www.thehindu.com"})
        self.assertNotIn("api.www.thehindu.com", hosts)

    def test_unresolvable_optional_api_host_does_not_abort_other_probes(self):
        candidates = [
            "https://www.thehindu.com/api/articles",
            "https://api.www.thehindu.com/articles",
            "https://www.thehindu.com/graphql",
        ]
        calls = []

        def fake_safe_get(url, **kwargs):
            calls.append(url)
            if "api.www.thehindu.com" in url:
                raise ValueError(
                    "The publication hostname could not be resolved: api.www.thehindu.com."
                )
            return FakeResponse()

        progress = []
        with (
            patch("scrapers.api_scraper.find_api_endpoints", return_value=candidates),
            patch("scrapers.api_scraper.safe_get", side_effect=fake_safe_get),
        ):
            result = try_api_scraping(
                "https://www.thehindu.com",
                max_articles=20,
                progress_callback=lambda *event: progress.append(event),
            )

        self.assertIsNone(result)
        self.assertEqual(calls, candidates)
        self.assertTrue(
            any("unavailable; checking the next candidate" in event[3] for event in progress)
        )

    def test_connection_failure_is_isolated_to_one_candidate(self):
        candidates = [
            "https://www.example.com/api/articles",
            "https://www.example.com/graphql",
        ]
        calls = []

        def fake_safe_get(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise requests.ConnectionError("temporary connection failure")
            return FakeResponse()

        with (
            patch("scrapers.api_scraper.find_api_endpoints", return_value=candidates),
            patch("scrapers.api_scraper.safe_get", side_effect=fake_safe_get),
        ):
            result = try_api_scraping("https://www.example.com", max_articles=20)

        self.assertIsNone(result)
        self.assertEqual(calls, candidates)


if __name__ == "__main__":
    unittest.main()
