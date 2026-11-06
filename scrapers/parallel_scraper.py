"""
Concurrent article extraction using one shared Chromium browser.

A small set of reusable pages replaces the previous pattern of launching a
new browser for every article. A progress callback reports each completed URL.
"""

import asyncio
import time

from playwright.async_api import async_playwright

from scrapers.article_scraper import scrape_journalist_info


def _notify(callback, current, total, detail):
    if callback:
        callback("Article extraction", current, total, detail)


async def scrape_articles_parallel(
    article_urls,
    max_workers=6,
    target_authors=200,
    progress_callback=None,
):
    """
    Extract article metadata concurrently while reusing one Chromium process.

    max_workers is intentionally capped to reduce memory pressure on small
    cloud instances. Failed article pages are counted and skipped, not silent.
    """
    urls = list(dict.fromkeys(url for url in article_urls if url))
    total = len(urls)
    if not urls:
        _notify(progress_callback, 0, 0, "No article URLs were available to extract")
        return []

    worker_count = max(1, min(int(max_workers), 8, total))
    results = []
    unique_authors = set()
    failed_count = 0
    processed_count = 0
    started = time.monotonic()
    stop_event = asyncio.Event()
    queue = asyncio.Queue()

    for index, url in enumerate(urls):
        queue.put_nowait((index, url))

    _notify(
        progress_callback,
        0,
        total,
        f"Starting {worker_count} workers for {total} article URLs",
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
                )
            )
            context.set_default_navigation_timeout(12000)
            context.set_default_timeout(5000)

            async def worker(worker_number):
                nonlocal failed_count, processed_count
                page = await context.new_page()
                try:
                    while not stop_event.is_set():
                        try:
                            index, url = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                        data = None
                        try:
                            data = await scrape_journalist_info(url, page=page)
                            if data:
                                results.append((index, data))
                                author = data.get("author")
                                if author and author != "Unknown":
                                    unique_authors.add(author)
                            else:
                                failed_count += 1
                        except Exception as exc:
                            failed_count += 1
                            print(
                                f"Worker {worker_number} failed for {url}: "
                                f"{type(exc).__name__}: {exc}"
                            )
                        finally:
                            processed_count += 1
                            elapsed = time.monotonic() - started
                            _notify(
                                progress_callback,
                                processed_count,
                                total,
                                (
                                    f"Processed {processed_count}/{total} · "
                                    f"{len(unique_authors)} journalists · "
                                    f"{failed_count} failed · {elapsed:.0f}s"
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
                "The article browser could not start. Verify that the deployed "
                "service uses the repository Dockerfile with Playwright Chromium."
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

    _notify(
        progress_callback,
        processed_count,
        total,
        (
            f"Extraction finished: {len(articles)} records, "
            f"{len(unique_authors)} identified journalists, {failed_count} failed "
            f"in {elapsed:.1f}s"
            + (" (author target reached)" if stopped_early else "")
        ),
    )
    print(
        f"Extraction completed: {len(articles)}/{total} records, "
        f"{len(unique_authors)} journalists, {failed_count} failures, "
        f"{elapsed:.1f}s."
    )
    return articles
