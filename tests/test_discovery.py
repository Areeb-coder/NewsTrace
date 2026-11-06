"""Regression tests for NewsTrace article discovery helpers."""

import unittest

from scrapers.api_scraper import extract_articles_from_json
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
            is_article_url(
                "https://example.com/category/politics",
                "https://example.com",
            )
        )
        self.assertFalse(
            is_article_url("https://example.com/", "https://example.com")
        )

    def test_section_detection(self):
        self.assertTrue(
            is_section_page("https://example.com/politics", "https://example.com")
        )
        self.assertFalse(
            is_section_page("https://other.test/politics", "https://example.com")
        )


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


if __name__ == "__main__":
    unittest.main()
