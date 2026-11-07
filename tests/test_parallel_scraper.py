"""Regression tests for visible in-flight article extraction progress."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scrapers import parallel_scraper


class FakePage:
    async def close(self):
        return None


class FakeContext:
    def __init__(self):
        self.pages = []

    async def route(self, pattern, callback):
        self.route_pattern = pattern
        self.route_callback = callback

    def set_default_navigation_timeout(self, value):
        self.navigation_timeout = value

    def set_default_timeout(self, value):
        self.timeout = value

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    async def close(self):
        return None


class FakeBrowser:
    def __init__(self):
        self.context = FakeContext()

    async def new_context(self, **kwargs):
        return self.context

    async def close(self):
        return None


class FakePlaywrightManager:
    def __init__(self):
        self.browser = FakeBrowser()
        self.playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch=self.launch)
        )

    async def launch(self, **kwargs):
        return self.browser

    async def __aenter__(self):
        return self.playwright

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class ParallelScraperProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_progress_is_reported_before_slow_article_finishes(self):
        manager = FakePlaywrightManager()
        started = asyncio.Event()
        finish = asyncio.Event()
        progress = []

        async def slow_scrape(url, page=None, diagnostics=None):
            started.set()
            await finish.wait()
            if diagnostics is not None:
                diagnostics["reason"] = "ok"
            return {"title": "Slow headline", "author": "A Reporter", "url": url}

        with (
            patch.object(parallel_scraper, "async_playwright", return_value=manager),
            patch.object(parallel_scraper, "scrape_journalist_info", side_effect=slow_scrape),
        ):
            task = asyncio.create_task(
                parallel_scraper.scrape_articles_parallel(
                    ["https://news.example/story"],
                    max_workers=1,
                    target_authors=0,
                    progress_callback=lambda *event: progress.append(event),
                )
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertTrue(
                any("fetching article" in str(event[-1]).lower() for event in progress),
                "The current article should be visible before the network/extraction completes.",
            )
            finish.set()
            articles = await task

        self.assertEqual(len(articles), 1)

    async def test_failed_article_does_not_discard_successful_article(self):
        manager = FakePlaywrightManager()
        progress = []

        async def scrape(url, page=None, diagnostics=None):
            if "bad" in url:
                if diagnostics is not None:
                    diagnostics.update({"reason": "http_503", "detail": "publisher unavailable"})
                return None
            if diagnostics is not None:
                diagnostics["reason"] = "ok"
            return {"title": "Good headline", "author": "A Reporter", "url": url}

        diagnostics = {}
        with (
            patch.object(parallel_scraper, "async_playwright", return_value=manager),
            patch.object(parallel_scraper, "scrape_journalist_info", side_effect=scrape),
        ):
            articles = await parallel_scraper.scrape_articles_parallel(
                ["https://news.example/good", "https://news.example/bad"],
                max_workers=1,
                target_authors=0,
                progress_callback=lambda *event: progress.append(event),
                diagnostics_out=diagnostics,
            )

        self.assertEqual([article["title"] for article in articles], ["Good headline"])
        self.assertEqual(diagnostics["processed"], 2)
        self.assertEqual(diagnostics["succeeded"], 1)
        self.assertEqual(diagnostics["failed"], 1)


if __name__ == "__main__":
    unittest.main()
