"""Regression tests for NewsTrace discovery and article parsing."""

import ast
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup

from scrapers.api_scraper import extract_articles_from_json
from scrapers.article_scraper import (
    _extract_from_page,
    _extract_jsonld_author,
    _parse_article_html,
    extract_image,
)
from utils.article_collector import (
    _get_next_page_hrefs,
    collect_article_urls,
    is_article_url,
    is_section_page,
    normalize_url,
    same_domain,
)


class PaginationLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_next_link_returns_empty_list_without_waiting(self):
        class FakeLocator:
            called = False

            async def evaluate_all(self, expression):
                self.called = True
                self.asserted_expression = expression
                return []

        class FakePage:
            def __init__(self):
                self.fake_locator = FakeLocator()

            def locator(self, selector):
                self.selector = selector
                return self.fake_locator

        page = FakePage()
        result = await _get_next_page_hrefs(page)
        self.assertEqual(result, [])
        self.assertTrue(page.fake_locator.called)
        self.assertIn('a[rel="next"]', page.selector)

    async def test_optional_pagination_error_does_not_abort_crawl(self):
        class FakeLocator:
            async def evaluate_all(self, expression):
                raise RuntimeError("DOM was replaced during pagination inspection")

        class FakePage:
            def locator(self, selector):
                return FakeLocator()

        self.assertEqual(await _get_next_page_hrefs(FakePage()), [])

    async def test_pagination_evaluate_all_uses_supported_signature(self):
        class FakeLocator:
            def __init__(self):
                self.called = False

            async def evaluate_all(self, expression):
                self.called = True
                return ["/world/page/2"]

        class FakePage:
            def __init__(self):
                self.fake_locator = FakeLocator()

            def locator(self, selector):
                return self.fake_locator

        page = FakePage()
        result = await _get_next_page_hrefs(page)
        self.assertEqual(result, ["/world/page/2"])
        self.assertTrue(page.fake_locator.called)


class ProgressCallbackContractTests(unittest.TestCase):
    def test_article_collector_notify_calls_supply_all_five_arguments(self):
        source_path = Path(__file__).resolve().parents[1] / "utils" / "article_collector.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_notify"
        ]
        self.assertTrue(calls, "Expected article collector progress notifications")
        malformed = [
            (node.lineno, len(node.args))
            for node in calls
            if len(node.args) != 5
        ]
        self.assertEqual(
            malformed,
            [],
            "Every article_collector._notify call must pass "
            "(callback, stage, current, total, detail).",
        )


class UrlNormalizationTests(unittest.TestCase):
    def test_normalize_url_removes_tracking_parameters(self):
        self.assertEqual(
            normalize_url("https://WWW.Example.com/politics/story/?utm_source=news&x=1#top"),
            "https://www.example.com/politics/story?x=1",
        )

    def test_normalize_url_rejects_invalid_schemes(self):
        self.assertIsNone(normalize_url("javascript:alert(1)"))
        self.assertIsNone(normalize_url("not-a-url"))

    def test_same_domain_does_not_accept_suffix_spoof(self):
        self.assertTrue(same_domain("https://www.example.com/a", "https://example.com"))
        self.assertFalse(same_domain("https://example.com.attacker.test/a", "https://example.com"))

    def test_date_based_story_is_article(self):
        self.assertTrue(
            is_article_url(
                "https://example.com/world/2026/11/06/a-long-news-story",
                "https://example.com",
            )
        )

    def test_long_section_slug_is_article(self):
        self.assertTrue(
            is_article_url(
                "https://example.com/politics/region/a-substantial-headline-slug-here",
                "https://example.com",
            )
        )

    def test_two_segment_section_headline_is_article(self):
        self.assertTrue(
            is_article_url(
                "https://example.com/world/a-long-headline-about-the-latest-developments",
                "https://example.com",
            )
        )

    def test_root_level_headline_slug_is_article(self):
        self.assertTrue(
            is_article_url(
                "https://example.com/a-long-breaking-news-headline-with-a-descriptive-slug",
                "https://example.com",
            )
        )

    def test_category_navigation_is_not_article(self):
        self.assertFalse(
            is_article_url("https://example.com/category/politics", "https://example.com")
        )
        self.assertFalse(is_article_url("https://example.com/", "https://example.com"))

    def test_section_detection(self):
        self.assertTrue(is_section_page("https://example.com/politics", "https://example.com"))
        self.assertFalse(is_section_page("https://other.test/politics", "https://example.com"))


class ApiResponseTests(unittest.TestCase):
    def test_extracts_article_records_from_list(self):
        records = extract_articles_from_json([
            {
                "title": "A headline",
                "url": "/world/a-headline",
                "author": "A Reporter",
                "published": "2026-11-06",
            },
            {"title": "Missing URL"},
            "not-an-object",
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "A headline")
        self.assertEqual(records[0]["url"], "/world/a-headline")
        self.assertEqual(records[0]["author"], "A Reporter")

    def test_extracts_wordpress_style_list(self):
        records = extract_articles_from_json({
            "posts": [
                {
                    "title": "WordPress headline",
                    "link": "https://example.com/post",
                    "date": "2026-11-06",
                }
            ]
        })
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "WordPress headline")

    def test_extracts_lead_image_from_api_record(self):
        records = extract_articles_from_json({
            "articles": [
                {
                    "title": "Illustrated headline",
                    "url": "https://example.com/story",
                    "image": {"url": "https://example.com/lead.jpg"},
                }
            ]
        })
        self.assertEqual(records[0]["image_url"], "https://example.com/lead.jpg")


class ArticleParsingTests(unittest.TestCase):
    def test_article_without_author_is_retained(self):
        html = """
        <!doctype html>
        <html><head><title>New policy announced</title></head>
        <body><main><article>
          <h1>New policy announced</h1>
          <p>The government announced a new policy today.</p>
        </article></main></body></html>
        """
        diagnostics = {}
        article = _parse_article_html("https://example.com/story", html, diagnostics)
        self.assertIsNotNone(article)
        self.assertEqual(article["title"], "New policy announced")
        self.assertEqual(article["author"], "Unknown")
        self.assertEqual(diagnostics["reason"], "ok")

    def test_jsonld_graph_person_author_is_extracted(self):
        html = """
        <html><head><title>Example story</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "NewsArticle",
              "headline": "Example story",
              "author": {"@id": "#reporter"}
            },
            {
              "@type": "Person",
              "@id": "#reporter",
              "name": "Asha Reporter"
            }
          ]
        }
        </script></head><body><article><h1>Example story</h1>
        <p>Story text that is long enough to count as a page body.</p></article></body></html>
        """
        diagnostics = {}
        article = _parse_article_html("https://example.com/story", html, diagnostics)
        self.assertIsNotNone(article)
        self.assertEqual(article["author"], "Asha Reporter")

    def test_jsonld_graph_with_embedded_person_author(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {
          "@graph": [{
            "@type": "NewsArticle",
            "headline": "Storm warning issued",
            "author": {"@type": "Person", "name": "Asha Reporter"}
          }]
        }
        </script></head>
        <body><article><h1>Storm warning issued</h1>
        <p>Long enough article text to identify the page as useful editorial content.</p></article></body></html>
        """
        author = _extract_jsonld_author(BeautifulSoup(html, "lxml"))
        self.assertEqual(author, "Asha Reporter")

    def test_legitimate_names_containing_generic_substrings_are_allowed(self):
        from scrapers.article_scraper import validate_author
        self.assertEqual(validate_author("Gavin Newsom", "Governor announces plan"), "Gavin Newsom")

    def test_http_fallback_recovers_article_after_browser_403(self):
        class BlockedResponse:
            status = 403

        class FakePage:
            async def goto(self, *args, **kwargs):
                return BlockedResponse()

        html = """
        <html><head><title>Fallback article</title></head>
        <body><article><h1>Fallback article</h1>
        <p>Article body returned by the standard HTTP request fallback.</p>
        </article></body></html>
        """
        diagnostics = {}
        with patch(
            "scrapers.article_scraper._fetch_article_with_requests",
            return_value=(200, "https://example.com/story", html, "text/html; charset=utf-8"),
        ):
            import asyncio
            article = asyncio.run(
                _extract_from_page(FakePage(), "https://example.com/story", diagnostics)
            )

        self.assertIsNotNone(article)
        self.assertEqual(article["title"], "Fallback article")
        self.assertEqual(article["author"], "Unknown")
        self.assertEqual(diagnostics["method"], "requests_fallback")
        self.assertEqual(diagnostics["browser_http_status"], 403)

    def test_access_challenge_is_not_saved_as_article(self):
        html = """
        <html><head><title>Attention Required</title></head>
        <body><h1>Verify you are human</h1><p>Checking your browser before accessing.</p></body></html>
        """
        diagnostics = {}
        article = _parse_article_html("https://example.com/story", html, diagnostics)
        self.assertIsNone(article)
        self.assertEqual(diagnostics["reason"], "anti_bot_challenge")

    def test_extract_image_uses_open_graph_metadata(self):
        html = """
        <html><head>
        <meta property="og:image" content="/images/lead-photo.jpg">
        </head><body><article><h1>Lead story</h1></article></body></html>
        """
        image = extract_image(BeautifulSoup(html, "lxml"), "https://example.com/world/story")
        self.assertEqual(image, "https://example.com/images/lead-photo.jpg")

    def test_extract_image_falls_back_to_article_figure(self):
        html = """
        <html><body><article>
          <figure><img data-src="/media/report.webp" alt="Report"></figure>
        </article></body></html>
        """
        image = extract_image(BeautifulSoup(html, "lxml"), "https://example.com/story")
        self.assertEqual(image, "https://example.com/media/report.webp")

    def test_extract_image_rejects_non_http_urls(self):
        html = '<html><head><meta property="og:image" content="javascript:alert(1)"></head><body></body></html>'
        image = extract_image(BeautifulSoup(html, "lxml"), "https://example.com/story")
        self.assertIsNone(image)





class ApiFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_api_discovery_error_falls_back_to_html_crawler(self):
        article_url = (
            "https://www.thehindu.com/world/a-long-headline-for-the-fallback-test"
        )
        progress = []

        with (
            patch(
                "utils.article_collector.try_api_scraping",
                side_effect=ValueError(
                    "The publication hostname could not be resolved: api.www.thehindu.com."
                ),
            ),
            patch(
                "utils.article_collector.crawl_sections_parallel",
                new=AsyncMock(return_value=[article_url]),
            ) as html_crawler,
        ):
            result = await collect_article_urls(
                "https://www.thehindu.com/world",
                max_articles=10,
                progress_callback=lambda *event: progress.append(event),
            )

        self.assertEqual(result, [article_url])
        html_crawler.assert_awaited_once()
        self.assertTrue(
            any(
                event[0] == "API discovery"
                and "switching to HTML discovery" in event[4]
                for event in progress
            )
        )

if __name__ == "__main__":
    unittest.main()
