"""
API-first article discovery.

All network calls have connect/read timeouts and report progress so the
Streamlit interface does not appear frozen while endpoints are probed.
"""

import math
import time
import requests
from urllib.parse import urlparse


def find_api_endpoints(website_url):
    """Return common JSON API endpoints for the publication."""
    domain = urlparse(website_url).netloc
    base = website_url.rstrip("/")
    return [
        f"{base}/api/articles",
        f"{base}/api/v1/content",
        f"{base}/wp-json/wp/v2/posts",
        f"{base}/graphql",
        f"{base}/api/search",
        f"{base}/feed/json",
        f"https://api.{domain}/articles",
    ]


def _notify(progress_callback, current, total, detail):
    if progress_callback:
        progress_callback("API discovery", current, total, detail)


def try_api_scraping(website_url, max_articles=500, progress_callback=None):
    """
    Probe common API routes and return normalized article dictionaries.

    Each probe has a short bounded timeout. If no endpoint yields usable
    records, the caller can continue with the HTML crawler.
    """
    endpoints = find_api_endpoints(website_url)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; NewsTrace/1.0)",
        "Accept": "application/json",
    })

    probe_deadline = time.monotonic() + 12.0
    try:
        for index, api_url in enumerate(endpoints, start=1):
            remaining = probe_deadline - time.monotonic()
            if remaining <= 0:
                break
            _notify(
                progress_callback,
                index - 1,
                len(endpoints),
                f"Checking endpoint {index}/{len(endpoints)}",
            )
            params = {"page": 1, "per_page": 100, "limit": 100, "size": 100}

            try:
                response = session.get(
                    api_url,
                    params=params,
                    timeout=(min(1.2, remaining), min(1.8, remaining)),
                )
                content_type = response.headers.get("Content-Type", "").lower()

                if response.status_code != 200 or "json" not in content_type:
                    continue

                try:
                    first_page = response.json()
                except ValueError:
                    continue

                articles = extract_articles_from_json(first_page)
                if not articles:
                    continue

                print(f"API discovery found a candidate endpoint: {api_url}")
                all_articles = list(articles)
                page_limit = min(10, max(1, math.ceil(max_articles / 100)))

                for page_number in range(2, page_limit + 1):
                    if len(all_articles) >= max_articles:
                        break

                    _notify(
                        progress_callback,
                        min(len(endpoints), index),
                        len(endpoints),
                        f"Fetching API page {page_number}/{page_limit}",
                    )
                    params["page"] = page_number
                    try:
                        page_response = session.get(
                            api_url,
                            params=params,
                            timeout=(1.2, 1.8),
                        )
                        if page_response.status_code != 200:
                            break
                        more_articles = extract_articles_from_json(page_response.json())
                    except (requests.RequestException, ValueError):
                        break

                    if not more_articles:
                        break
                    all_articles.extend(more_articles)

                _notify(
                    progress_callback,
                    len(endpoints),
                    len(endpoints),
                    f"API returned {min(len(all_articles), max_articles)} article records",
                )
                return all_articles[:max_articles]

            except requests.RequestException as exc:
                print(f"API probe failed for {api_url}: {type(exc).__name__}: {exc}")
                continue
    finally:
        session.close()

    _notify(
        progress_callback,
        len(endpoints),
        len(endpoints),
        "No compatible JSON API found; switching to HTML discovery",
    )
    return None


def extract_articles_from_json(data):
    """Extract article-like records from common JSON response shapes."""
    articles = []
    items = []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("articles", "posts", "data", "items", "results", "content"):
            if key not in data:
                continue
            value = data[key]
            if isinstance(value, list):
                items = value
            elif isinstance(value, dict):
                nested = value.get("articles") or value.get("items") or value.get("posts")
                items = nested if isinstance(nested, list) else [value]
            break

    for item in items[:100]:
        if not isinstance(item, dict):
            continue

        title = item.get("title") or item.get("headline") or ""
        url = item.get("url") or item.get("link") or item.get("permalink") or ""
        if not title or not url:
            continue

        articles.append({
            "title": title,
            "author": item.get("author") or item.get("byline") or "Unknown",
            "url": url,
            "date": item.get("date") or item.get("published") or item.get("created_at") or "",
            "section": item.get("section") or item.get("category") or item.get("topic") or "",
        })

    return articles
