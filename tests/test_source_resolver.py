"""Regression tests for bounded publication-name resolution."""

import unittest
from unittest.mock import patch

import requests

from backend.source_resolver import resolve_outlet


class FakeResponse:
    def __init__(self, status_code=200, url="https://news.example", text="", headers=None):
        self.status_code = status_code
        self.url = url
        self.text = text
        self.headers = headers or {}

    @property
    def ok(self):
        return self.status_code < 400

    def close(self):
        pass


class SourceResolverTests(unittest.TestCase):
    def test_direct_url_returns_without_network_and_reports_progress(self):
        progress = []
        with patch("backend.source_resolver.safe_get", create=True) as fetch:
            result = resolve_outlet(
                "https://news.example/world",
                progress_callback=progress.append,
            )
        self.assertEqual(result, ("https://news.example", "news.example"))
        fetch.assert_not_called()
        self.assertTrue(progress)

    def test_name_resolution_uses_at_most_three_domain_fallbacks(self):
        progress = []
        def fail_search(url, **kwargs):
            if "duckduckgo.com" in url:
                raise requests.Timeout("search timed out")
            return FakeResponse(status_code=404, url=url)

        with patch("backend.source_resolver.safe_get", side_effect=fail_search, create=True) as fetch:
            result = resolve_outlet(
                "The Example Daily",
                progress_callback=progress.append,
                timeout_seconds=6,
            )

        self.assertEqual(result, (None, None))
        self.assertLessEqual(fetch.call_count, 4)
        self.assertTrue(any("search" in item.lower() for item in progress))
        self.assertTrue(any("candidate" in item.lower() for item in progress))

    def test_search_result_is_returned_and_fallback_is_skipped(self):
        html = """
        <html><body><a class="result__a" href="https://example-news.org/">Example News</a></body></html>
        """
        progress = []
        with patch(
            "backend.source_resolver.safe_get",
            return_value=FakeResponse(text=html, url="https://duckduckgo.com/html/"),
            create=True,
        ) as fetch:
            result = resolve_outlet(
                "Example News",
                progress_callback=progress.append,
                timeout_seconds=6,
            )
        self.assertEqual(result, ("https://example-news.org", "example-news.org"))
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(progress)


if __name__ == "__main__":
    unittest.main()
