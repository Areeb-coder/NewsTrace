"""
Concurrent article extraction using one shared Chromium browser.

Each worker owns a reusable page. Failed requests are categorized so a run
that returns zero articles exposes the actual transport/parser problem.
"""

import asyncio
import time
from collections import Counter
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from scrapers.article_scraper import scrape_journalist_info
from utils.url_safety import install_public_network_guard


def _notify(callback, current, total, detail):
    if callback:
        callback("Article extraction", current, total, detail)


def _safe_host(url):
    try:
        return urlparse(url).netloc or "unknown host"
    except Exception:
        return "unknown host"


def _safe_path(url):
    """Retain the path for diagnostics but never expose query strings/tokens."""
    try:
        return (urlparse(url).path or "/")[:140]
    except Exception:
        return "/"


async def scrape_articles_parallel(
    article_urls,
    max_workers=6,
    target_authors=200,
    progress_callback=None,
    diagnostics_out=None,
):
    """
    Extract articles while reusing one Chromium process.

    A valid article is retained even when its author is unavailable. Only
    inaccessible, interstitial, or unparseable responses count as failures.
    diagnostics_out, when supplied, receives aggregate failure reasons.
    """
    urls = list(dict.fromkeys(url for url in article_urls if url))
    total = len(urls)
    if diagnostics_out is not None:
        diagnostics_out.clear()

    if not urls:
        _notify(progress_callback, 0, 0, "No article URLs were available to extract")
        if diagnostics_out is not None:
            diagnostics_out.update({"processed": 0, "succeeded": 0, "failed": 0, "failure_reasons": {}})
        return []

    worker_count = max(1, min(int(max_workers), 6, total))
    results = []
    unique_authors = set()
    failure_reasons = Counter()
    failure_samples = []
    failed_count = 0
    processed_count = 0
    started_count = 0
    started = time.monotonic()
    stop_event = asyncio.Event()
    queue = asyncio.Queue()

    for index, url in enumerate(urls):
        queue.put_nowait((index, url))

    _notify(
        progress_callback,
        0,
        total,
        f"Starting {worker_count} reusable browser pages for {total} article URLs",
    )

    async with async_playwright() as playwright:
        browser = None
        context = None
        try:
            browser = await playwright.chromium.launch(headless=True, timeout=20000)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                ignore_https_errors=True,
            )
            await install_public_network_guard(context)
            context.set_default_navigation_timeout(12000)
            context.set_default_timeout(5000)

            async def worker(worker_number):
                nonlocal failed_count, processed_count, started_count
                page = await context.new_page()
                try:
                    while not stop_event.is_set():
                        try:
                            index, url = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                        started_count += 1
                        _notify(
                            progress_callback,
                            processed_count,
                            total,
                            f"Fetching article {started_count}/{total} with worker {worker_number + 1}/{worker_count}: {_safe_host(url)}{_safe_path(url)}",
                        )
                        diagnostics = {}
                        try:
                            data = await scrape_journalist_info(
                                url,
                                page=page,
                                diagnostics=diagnostics,
                            )
                            if data:
                                results.append((index, data))
                                author = data.get("author")
                                if author and author != "Unknown":
                                    unique_authors.add(author)
                            else:
                                failed_count += 1
                                reason = diagnostics.get("reason", "unknown_failure")
                                failure_reasons[reason] += 1
                                if len(failure_samples) < 4:
                                    failure_samples.append({
                                        "host": _safe_host(url),
                                        "path": _safe_path(url),
                                        "reason": reason,
                                        "detail": diagnostics.get("detail")
                                            or diagnostics.get("requests_error")
                                            or diagnostics.get("browser_error")
                                            or "",
                                        "browser_http_status": diagnostics.get("browser_http_status"),
                                        "requests_http_status": diagnostics.get("requests_http_status"),
                                    })
                                print(
                                    f"Article failed: host={_safe_host(url)} "
                                    f"reason={reason} diagnostics={diagnostics}"
                                )
                        except Exception as exc:
                            failed_count += 1
                            reason = type(exc).__name__
                            failure_reasons[reason] += 1
                            if len(failure_samples) < 4:
                                failure_samples.append({
                                    "host": _safe_host(url),
                                    "path": _safe_path(url),
                                    "reason": reason,
                                    "detail": str(exc)[:240],
                                })
                            print(
                                f"Worker {worker_number} failed for {_safe_host(url)}: "
                                f"{type(exc).__name__}: {exc}"
                            )
                        finally:
                            processed_count += 1
                            elapsed = time.monotonic() - started
                            top_failure = (
                                ", ".join(
                                    f"{reason}: {count}"
                                    for reason, count in failure_reasons.most_common(2)
                                )
                                if failure_reasons else "no failures"
                            )
                            _notify(
                                progress_callback,
                                processed_count,
                                total,
                                (
                                    f"Processed {processed_count}/{total} · "
                                    f"{len(results)} articles retained · "
                                    f"{len(unique_authors)} journalists · "
                                    f"{failed_count} failed ({top_failure}) · {elapsed:.0f}s"
                                ),
                            )
                            queue.task_done()

                        if target_authors and len(unique_authors) >= target_authors:
                            stop_event.set()
                            break
                finally:
                    await page.close()

            await asyncio.gather(
                *(worker(worker_number) for worker_number in range(worker_count))
            )
        except Exception as exc:
            raise RuntimeError(
                "The article browser could not start. Verify the repository Docker image "
                "and Playwright Chromium installation. Original error: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()

    results.sort(key=lambda item: item[0])
    articles = [item[1] for item in results]
    elapsed = time.monotonic() - started
    stopped_early = stop_event.is_set() and processed_count < total

    final_detail = (
        f"Extraction finished: {len(articles)}/{total} articles retained, "
        f"{len(unique_authors)} journalists, {failed_count} failures in {elapsed:.1f}s"
    )
    if failure_reasons:
        final_detail += " · " + ", ".join(
            f"{reason}: {count}" for reason, count in failure_reasons.most_common(4)
        )
    if stopped_early:
        final_detail += " · stopped after reaching the journalist target"

    _notify(progress_callback, processed_count, total, final_detail)
    print(final_detail)

    if diagnostics_out is not None:
        diagnostics_out.update({
            "processed": processed_count,
            "succeeded": len(articles),
            "failed": failed_count,
            "journalists": len(unique_authors),
            "failure_reasons": dict(failure_reasons),
            "failure_samples": failure_samples,
            "elapsed_seconds": round(elapsed, 1),
        })

    return articles
