"""Streamlit-independent NewsTrace investigation pipeline.

This module reuses the production article discovery, Playwright extraction,
author profile and optional SerpAPI enrichment modules.
"""

import asyncio
import pandas as pd

from utils.article_collector import collect_article_urls
from scrapers.parallel_scraper import scrape_articles_parallel
from scrapers.author_profiles import get_author_profile_page, scrape_author_details
from utils.google_enrichment import SERPAPI_KEY, search_journalist_profile


async def run_investigation(url, outlet_name, max_articles, enable_profiles=False, enable_google=False, discovery_url=None, progress_callback=None):
    """
    Run discovery, extraction and optional enrichment with visible progress.
    """
    results = {"articles": [], "profiles": {}, "stats": {}, "warnings": []}

    phase_ranges = {
        "API discovery": (0.02, 0.09),
        "HTML discovery": (0.09, 0.29),
        "Article discovery": (0.29, 0.30),
        "Article extraction": (0.30, 0.86),
        "Author profiles": (0.86, 0.95),
        "Search enrichment": (0.95, 0.99),
    }

    def update_progress(stage, current, total, detail):
        if progress_callback:
            progress_callback(stage, current, total, detail)

    try:
        start_url = discovery_url or url
        api_article_metadata = []
        urls = await collect_article_urls(
            start_url,
            max_articles,
            progress_callback=update_progress,
            max_pages=18,
            article_metadata_out=api_article_metadata,
        )
        results["stats"]["urls_found"] = len(urls)

        if not urls:
            raise RuntimeError(
                "NewsTrace could not find article URLs on this publication. "
                "Try pasting a direct section URL (for example, its Politics or World page). "
                "Some sites block automated browsing or use URL patterns NewsTrace cannot identify."
            )

        update_progress(
            "Article discovery",
            len(urls),
            len(urls),
            f"Discovery complete · {len(urls)} URLs ready for extraction",
        )

        extraction_diagnostics = {}
        articles_data = await scrape_articles_parallel(
            urls,
            max_workers=6,
            target_authors=200,
            progress_callback=update_progress,
            diagnostics_out=extraction_diagnostics,
        )
        results["stats"]["extraction_diagnostics"] = extraction_diagnostics

        if not articles_data:
            reasons = extraction_diagnostics.get("failure_reasons", {})
            reason_summary = ", ".join(
                f"{reason}: {count}" for reason, count in sorted(
                    reasons.items(), key=lambda item: item[1], reverse=True
                )[:4]
            ) or "no failure details were recorded"
            samples = extraction_diagnostics.get("failure_samples", [])
            sample_detail = ""
            if samples:
                first = samples[0]
                sample_detail = (
                    f" Example: {first.get('host')} — {first.get('reason')}: "
                    f"{first.get('detail') or 'no further details'}."
                )
            raise RuntimeError(
                f"Found {len(urls)} article URLs, but could not retain any article pages. "
                f"Failure breakdown: {reason_summary}.{sample_detail} "
                "If the publisher is returning an access challenge (403/429/CAPTCHA), "
                "NewsTrace will report it rather than bypassing the site's controls."
            )

        results["articles"] = articles_data
        results["stats"]["articles_scraped"] = len(articles_data)
        results["stats"]["article_failures"] = extraction_diagnostics.get(
            "failed", max(0, len(urls) - len(articles_data))
        )

        # Publisher API thumbnails are a fallback only; image metadata
        # extracted from the article HTML takes precedence.
        api_images = {
            item.get("url"): item.get("image_url")
            for item in api_article_metadata
            if item.get("url") and item.get("image_url")
        }
        for article in articles_data:
            if not article.get("image_url") and article.get("url") in api_images:
                article["image_url"] = api_images[article["url"]]

        articles_df = pd.DataFrame(articles_data)
        if "author" not in articles_df.columns:
            articles_df["author"] = "Unknown"
        articles_df["author"] = articles_df["author"].fillna("Unknown")
        unique_authors = sorted({
            str(author).strip()
            for author in articles_df["author"].tolist()
            if author and str(author).strip().lower() != "unknown"
        })
        results["stats"]["unique_authors"] = len(unique_authors)

        if enable_profiles and unique_authors:
            profile_targets = unique_authors[:20]
            profiles = {}
            semaphore = asyncio.Semaphore(4)
            completed_profiles = 0

            async def get_profile(author):
                nonlocal completed_profiles
                async with semaphore:
                    try:
                        async def collect_profile():
                            profile_url = await get_author_profile_page(author, url)
                            if not profile_url:
                                return None
                            details = await scrape_author_details(profile_url)
                            if details:
                                details["profile_url"] = profile_url
                                return details
                            return None

                        details = await asyncio.wait_for(collect_profile(), timeout=22)
                        if details:
                            profiles[author] = details
                    except asyncio.TimeoutError:
                        print(f"Profile lookup timed out for {author}")
                    except Exception as exc:
                        print(f"Profile lookup failed for {author}: {type(exc).__name__}: {exc}")
                    finally:
                        completed_profiles += 1
                        update_progress(
                            "Author profiles",
                            completed_profiles,
                            len(profile_targets),
                            f"Checked {completed_profiles}/{len(profile_targets)} journalist profiles · {len(profiles)} found",
                        )

            await asyncio.gather(*(get_profile(author) for author in profile_targets))
            results["profiles"] = profiles
            results["stats"]["profiles_found"] = len(profiles)

        elif enable_profiles:
            update_progress("Author profiles", 1, 1, "No identified authors available for profile enrichment")

        if enable_google and unique_authors:
            if not SERPAPI_KEY:
                results["warnings"].append(
                    "Search enrichment was skipped because SERP_API_KEY is not configured."
                )
                results["stats"]["google_enriched"] = 0
            else:
                update_progress(
                    "Search enrichment", 0, 1,
                    f"Searching public profiles for up to {min(30, len(unique_authors))} journalists",
                )
                google_targets = unique_authors[:30]
                google_profiles = []
                google_semaphore = asyncio.Semaphore(3)
                completed_searches = 0

                async def search_profile(author):
                    nonlocal completed_searches
                    profile = None
                    async with google_semaphore:
                        try:
                            profile = await asyncio.to_thread(
                                search_journalist_profile,
                                author,
                                outlet_name,
                            )
                        except Exception as exc:
                            print(f"Search enrichment failed for {author}: {type(exc).__name__}: {exc}")
                        finally:
                            completed_searches += 1
                            update_progress(
                                "Search enrichment",
                                completed_searches,
                                len(google_targets),
                                f"Checked {completed_searches}/{len(google_targets)} journalists · "
                                f"{len(google_profiles)} profiles returned",
                            )
                    if profile:
                        google_profiles.append(profile)

                await asyncio.gather(*(search_profile(author) for author in google_targets))

                if not results["profiles"]:
                    results["profiles"] = {}
                for profile in google_profiles:
                    author = profile.get("name")
                    if not author:
                        continue
                    results["profiles"].setdefault(author, {})
                    for field in ("twitter", "linkedin", "instagram", "email", "workplace", "bio"):
                        if profile.get(field):
                            results["profiles"][author][field] = profile[field]

                results["stats"]["google_enriched"] = len(google_profiles)
                update_progress(
                    "Search enrichment", len(google_targets), len(google_targets),
                    f"Search enrichment complete · {len(google_profiles)} profiles returned",
                )

        profiles_map = results.get("profiles") or {}
        if profiles_map:
            all_keys = set()
            for profile in profiles_map.values():
                if isinstance(profile, dict):
                    all_keys.update(profile.keys())

            for key in sorted(all_keys):
                if key == "name" or key in articles_df.columns:
                    continue
                articles_df[key] = articles_df["author"].map(
                    lambda author: (
                        profiles_map.get(author, {}).get(key)
                        if isinstance(profiles_map.get(author, {}), dict)
                        else None
                    )
                )

        results["stats"]["articles_scraped"] = len(articles_df)
        update_progress(
            "Complete",
            len(articles_df),
            len(articles_df),
            f"Investigation complete · {len(articles_df)} articles · {len(unique_authors)} journalists",
        )
        return articles_df, results["stats"], results["warnings"]

    except Exception as exc:
        raise
