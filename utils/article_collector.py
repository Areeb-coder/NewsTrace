"""
Bounded article discovery for news websites.

The collector probes lightweight JSON APIs first and falls back to a bounded
Playwright crawl. Progress callbacks are optional so this module can also be
used outside Streamlit.
"""

import asyncio
import re
import time
from collections import deque
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from playwright.async_api import async_playwright

from scrapers.api_scraper import try_api_scraping


TRACKING_PARAMS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "referrer",
    "source", "utm_campaign", "utm_content", "utm_medium",
    "utm_source", "utm_term",
}
SECTION_KEYWORDS = {
    "business", "entertainment", "health", "opinion", "politics",
    "science", "sports", "tech", "technology", "world",
}
SKIP_PATH_PARTS = {
    "about", "advertise", "author", "authors", "category", "contact",
    "login", "privacy", "search", "section", "sections", "subscribe",
    "tag", "terms", "topic", "topics",
}


def _notify(callback, stage, current, total, detail):
    if callback:
        callback(stage, current, total, detail)


def normalize_url(url):
    """Normalize a URL for queue de-duplication without dropping pagination."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None

        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMS
        ]
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")

        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            urlencode(query, doseq=True),
            "",
        ))
    except (TypeError, ValueError):
        return None


def same_domain(url1, url2):
    """Compare hostnames exactly, allowing only the optional www prefix."""
    try:
        host1 = (urlparse(url1).hostname or "").lower().removeprefix("www.")
        host2 = (urlparse(url2).hostname or "").lower().removeprefix("www.")
        return bool(host1 and host1 == host2)
    except (TypeError, ValueError):
        return False


def is_article_url(url, base_domain):
    """Identify likely article URLs while excluding static and navigation pages."""
    if not same_domain(url, base_domain):
        return False

    path = urlparse(url).path.lower()
    if not path or path == "/":
        return False

    if any(part in path for part in (
        ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif",
        ".xml", ".rss", "/feed", "/rss",
    )):
        return False

    parts = [part for part in path.split("/") if part]
    if not parts or any(part in SKIP_PATH_PARTS for part in parts):
        return False

    explicit_patterns = (
        r"/article/",
        r"/articles/",
        r"/story/",
        r"/stories/",
        r"/post/",
        r"/posts/",
        r"/news/",
        r"/20\d{2}/",
    )
    if any(re.search(pattern, path) for pattern in explicit_patterns):
        return True

    # A common newsroom pattern is /section/region/descriptive-headline-slug.
    # Require a substantial final slug to avoid classifying every category page.
    if len(parts) >= 3:
        leaf = parts[-1]
        if len(leaf) >= 24 and ("-" in leaf or re.search(r"\d", leaf)):
            return True

    return False


def is_section_page(url, base_domain):
    """Identify section pages worth following during a bounded crawl."""
    if not same_domain(url, base_domain):
        return False

    parsed = urlparse(url)
    parts = [part.lower() for part in parsed.path.split("/") if part]
    if not parts or is_article_url(url, base_domain):
        return False

    if any(part in {"author", "authors", "tag", "search", "about"} for part in parts):
        return False

    return any(part in SECTION_KEYWORDS for part in parts) or any(
        marker in parsed.path.lower()
        for marker in ("/section/", "/category/", "/topic/")
    )


async def collect_article_urls(
    website_url,
    max_articles=300,
    progress_callback=None,
    max_pages=18,
):
    """
    Discover article URLs with hard limits and user-visible progress.

    The API probe is deliberately time-bounded. The HTML fallback visits no
    more than max_pages pages and never waits on arbitrary network-idle events.
    """
    normalized_home = normalize_url(website_url)
    if not normalized_home:
        raise ValueError("Enter a valid http:// or https:// publication URL.")

    max_articles = max(1, int(max_articles))
    started = time.monotonic()

    _notify(progress_callback, "API discovery", 0, 7, "Checking common publication API endpoints")
    api_data = try_api_scraping(
        normalized_home,
        max_articles,
        progress_callback=progress_callback,
    )

    if api_data:
        api_urls = []
        seen = set()
        for item in api_data:
            raw_url = item.get("url") if isinstance(item, dict) else None
            absolute = normalize_url(urljoin(normalized_home, raw_url)) if raw_url else None
            if absolute and same_domain(absolute, normalized_home) and absolute not in seen:
                seen.add(absolute)
                api_urls.append(absolute)

        if api_urls:
            _notify(
                progress_callback,
                "Article discovery",
                len(api_urls),
                len(api_urls),
                f"Found {len(api_urls)} article URLs through the publication API",
            )
            return api_urls[:max_articles]

    _notify(progress_callback, "HTML discovery", 0, max_pages, "No compatible API found; opening the publication website")
    urls = await crawl_sections_parallel(
        normalized_home,
        max_articles,
        max_pages=max_pages,
        progress_callback=progress_callback,
    )

    elapsed = time.monotonic() - started
    _notify(
        progress_callback,
        "Article discovery",
        len(urls),
        max_articles,
        f"Collected {len(urls)} article URLs in {elapsed:.1f}s",
    )
    return urls[:max_articles]


async def crawl_sections_parallel(
    website_url,
    target,
    max_pages=24,
    progress_callback=None,
    navigation_timeout_ms=8000,
):
    """Crawl the homepage and discovered sections with strict page/time limits."""
    article_urls = set()
    visited_pages = set()
    failed_pages = 0

    homepage = normalize_url(website_url)
    pending = deque([homepage])
    queued_pages = {homepage}
    max_pages = max(1, int(max_pages))
    target = max(1, int(target))

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True, timeout=15000)
        except Exception as exc:
            raise RuntimeError(
                "Chromium could not start. Redeploy using the repository Dockerfile "
                "so Playwright's browser and system libraries are installed."
            ) from exc

        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                ignore_https_errors=False,
            )
            page = await context.new_page()
            page.set_default_navigation_timeout(navigation_timeout_ms)
            page.set_default_timeout(5000)

            while pending and len(article_urls) < target and len(visited_pages) < max_pages:
                current_url = pending.popleft()
                if current_url in visited_pages:
                    continue
                visited_pages.add(current_url)

                _notify(
                    progress_callback,
                    "HTML discovery",
                    len(visited_pages) - 1,
                    max_pages,
                    f"Visiting page {len(visited_pages)}/{max_pages}: {current_url}",
                )

                try:
                    response = await page.goto(
                        current_url,
                        timeout=navigation_timeout_ms,
                        wait_until="domcontentloaded",
                    )
                    if response is not None and response.status >= 400:
                        failed_pages += 1
                        continue

                    hrefs = await page.locator("a[href]").evaluate_all(
                        "(anchors) => anchors.map((anchor) => anchor.href)"
                    )

                    for href in hrefs:
                        absolute = normalize_url(urljoin(current_url, href))
                        if not absolute or not same_domain(absolute, homepage):
                            continue

                        if is_article_url(absolute, homepage):
                            article_urls.add(absolute)
                            if len(article_urls) >= target:
                                break
                        elif (
                            is_section_page(absolute, homepage)
                            and absolute not in queued_pages
                            and absolute not in visited_pages
                        ):
                            queued_pages.add(absolute)
                            pending.append(absolute)

                    # Follow a single explicit next-page link, if available.
                    next_locator = page.locator(
                        'a[rel="next"], a.next, a[aria-label*="next" i]'
                    ).first
                    next_href = (
                        await next_locator.get_attribute("href", timeout=800)
                        if await next_locator.count()
                        else None
                    )
                    if next_href:
                        next_url = normalize_url(urljoin(current_url, next_href))
                        if (
                            next_url
                            and same_domain(next_url, homepage)
                            and next_url not in queued_pages
                            and next_url not in visited_pages
                        ):
                            queued_pages.add(next_url)
                            pending.append(next_url)

                except Exception as exc:
                    failed_pages += 1
                    print(f"Discovery page failed ({current_url}): {type(exc).__name__}: {exc}")
                finally:
                    _notify(
                        progress_callback,
                        "HTML discovery",
                        len(visited_pages),
                        max_pages,
                        (
                            f"{len(article_urls)} article URLs found · "
                            f"{failed_pages} page failures · {len(pending)} queued"
                        ),
                    )

                # A short courtesy pause without the previous 1–3 second delay.
                await asyncio.sleep(0.15)

            await context.close()
        finally:
            await browser.close()

    print(
        f"Discovery completed: {len(article_urls)} URLs, "
        f"{len(visited_pages)} pages visited, {failed_pages} page failures."
    )
    return list(article_urls)
