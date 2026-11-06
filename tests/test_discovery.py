"""Regression tests for NewsTrace discovery and article parsing."""

import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers.api_scraper import extract_articles_from_json
from scrapers.article_scraper import (
    _extract_from_page,
    _extract_jsonld_author,
    _parse_article_html,
)
from utils.article_collector import (
    is_article_url,
    is_section_page,
    normalize_url,
    same_domain,
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


if __name__ == "__main__":
    unittest.main()
