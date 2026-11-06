"""
NewsTrace - Unified Powerful Dashboard
Single pipeline with intelligent mode switching - Maximum code reusability
"""

import streamlit as st
import asyncio
import pandas as pd
import plotly.graph_objects as go
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from utils.article_collector import collect_article_urls, normalize_url
from scrapers.parallel_scraper import scrape_articles_parallel
from scrapers.author_profiles import get_author_profile_page, scrape_author_details
from utils.google_enrichment import SERPAPI_KEY, search_journalist_profile
from utils.supabase_backend import save_articles, save_journalist_profiles, check_connection
import os
import re
import time
from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo

# Page Config
st.set_page_config(page_title="NewsTrace — The Digital News Chronicle", page_icon="N", layout="wide", initial_sidebar_state="collapsed")

# (Landing page removed; app opens directly on the dashboard)


def resolve_outlet(user_input: str):
    """Resolve a user-provided outlet name or URL into a base website URL and label without using a predefined list.
    Strategy:
    - If it's a URL, normalize and return base domain.
    - Otherwise, query DuckDuckGo HTML results and pick the first non-social/news-looking domain.
    - Fallback: try slug-based domain guesses with common TLDs and validate by HTTP.
    Returns (base_url, label) or (None, None).
    """
    if not user_input:
        return None, None

    s = user_input.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"
    }

    # Accept full URLs and domain/path input without a scheme.
    # Return the site origin for profile lookups; the caller preserves the
    # full path separately as the discovery starting point.
    try:
        candidate = s if s.startswith(("http://", "https://")) else f"https://{s}"
        p = urlparse(candidate)
        if p.netloc and "." in (p.hostname or "") and not any(ch.isspace() for ch in s):
            base = f"{p.scheme}://{p.netloc}"
            return base, p.netloc
    except Exception:
        pass

    # Try DuckDuckGo HTML
    try:
        from urllib.parse import quote_plus
        q = quote_plus(f"{s} official site news")
        r = requests.get(f"https://duckduckgo.com/html/?q={q}", headers=headers, timeout=10)
        if r.ok:
            soup = BeautifulSoup(r.text, "html.parser")
            # DuckDuckGo often uses redirect links with uddg param
            candidates = []
            for a in soup.select("a.result__a, a[href]"):
                href = a.get("href")
                if not href:
                    continue
                if "duckduckgo.com/l/?uddg=" in href:
                    try:
                        u = urlparse(href)
                        qd = parse_qs(u.query)
                        redir = qd.get("uddg", [None])[0]
                        if redir:
                            href = redir
                    except Exception:
                        continue
                if href.startswith("http"):
                    candidates.append(href)
            # Filter out obvious non-official/social sites
            skip_hosts = ("wikipedia.org", "twitter.com", "x.com", "facebook.com", "linkedin.com", "youtube.com")
            for c in candidates:
                try:
                    u = urlparse(c)
                    host = u.netloc.lower()
                    if any(sh in host for sh in skip_hosts):
                        continue
                    base = f"{u.scheme}://{u.netloc}"
                    return base, host
                except Exception:
                    continue
    except Exception:
        pass

    # Fallback: slug guesses
    import re
    slug = re.sub(r"[^a-z0-9]+", "", s.lower())
    for tld in [".com", ".org", ".net", ".co", ".co.uk", ".in", ".news"]:
        test = f"https://{slug}{tld}"
        try:
            rr = requests.get(test, headers=headers, timeout=6, allow_redirects=True)
            if rr.status_code < 400:
                p = urlparse(rr.url)
                if p.netloc:
                    base = f"{p.scheme}://{p.netloc}"
                    return base, p.netloc
        except Exception:
            continue

    return None, None


async def unified_scraping_pipeline(url, outlet_name, max_articles, enable_profiles=False, enable_google=False, discovery_url=None):
    """
    Run discovery, extraction and optional enrichment with visible progress.
    """
    results = {"articles": [], "profiles": {}, "stats": {}}
    progress_bar = st.progress(0.0, text="Preparing the investigation…")
    status_box = st.status("Preparing NewsTrace pipeline", expanded=True)
    last_render = 0.0
    latest_fraction = 0.0

    phase_ranges = {
        "API discovery": (0.02, 0.09),
        "HTML discovery": (0.09, 0.29),
        "Article discovery": (0.29, 0.30),
        "Article extraction": (0.30, 0.86),
        "Author profiles": (0.86, 0.95),
        "Search enrichment": (0.95, 0.99),
    }

    def update_progress(stage, current, total, detail):
        nonlocal last_render, latest_fraction
        start_fraction, end_fraction = phase_ranges.get(stage, (latest_fraction, latest_fraction))
        fraction = end_fraction if not total else start_fraction + (
            (end_fraction - start_fraction) * max(0, min(1, current / total))
        )
        latest_fraction = max(latest_fraction, min(0.995, fraction))
        now = time.monotonic()
        is_stage_done = bool(total and current >= total)
        if now - last_render < 0.35 and not is_stage_done:
            return
        last_render = now
        safe_detail = str(detail).replace("\n", " ").strip()
        try:
            progress_bar.progress(
                latest_fraction,
                text=f"{stage} · {safe_detail[:180]}",
            )
            status_box.update(label=f"{stage}", state="running", expanded=False)
        except Exception:
            # Progress rendering must never abort the scraping pipeline.
            pass

    try:
        status_box.update(label="Discovering article URLs", state="running", expanded=True)
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
                st.warning(
                    "Search enrichment was skipped because SERP_API_KEY is not configured. "
                    "Add it in your hosting provider's environment settings to enable this option."
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
        progress_bar.progress(1.0, text="Investigation complete")
        status_box.update(
            label=f"Investigation complete · {len(articles_df)} articles · {len(unique_authors)} journalists",
            state="complete",
            expanded=False,
        )
        return articles_df, results["stats"]

    except Exception as exc:
        status_box.update(label="Investigation could not be completed", state="error", expanded=True)
        progress_bar.empty()
        raise


def run_unified_pipeline(user_query, max_articles, enable_profiles, enable_google):
    """Resolve the source, run the async pipeline and surface actionable errors."""
    st.session_state["_pipeline_error_displayed"] = False
    source_status = st.status("Resolving the news outlet…", expanded=False)
    try:
        url, outlet_label = resolve_outlet(user_query)
        if not url:
            st.session_state["_pipeline_error_displayed"] = True
            source_status.update(
                label="Could not resolve the publication",
                state="error",
                expanded=True,
            )
            st.error(
                "NewsTrace could not identify that publication. Paste its full website URL "
                "(including https://) and try again."
            )
            return None, None

        source_status.update(
            label=f"Source resolved · {outlet_label or url}",
            state="complete",
            expanded=False,
        )
        raw_input = user_query.strip()
        candidate_input = (
            raw_input
            if raw_input.startswith(("http://", "https://"))
            else f"https://{raw_input}"
        )
        parsed_input = urlparse(candidate_input)
        direct_start_url = (
            normalize_url(candidate_input)
            if parsed_input.netloc and "." in (parsed_input.hostname or "")
            and not any(ch.isspace() for ch in raw_input)
            else url
        )

        return asyncio.run(
            unified_scraping_pipeline(
                url,
                outlet_label or user_query,
                max_articles,
                enable_profiles,
                enable_google,
                discovery_url=direct_start_url,
            )
        )
    except Exception as exc:
        st.session_state["_pipeline_error_displayed"] = True
        source_status.update(label="Investigation failed", state="error", expanded=True)
        st.error(f"**NewsTrace could not complete this investigation.** {exc}")
        st.caption(
            "You can retry with a direct section URL or a smaller article limit. "
            "The pipeline now reports the stage and count reached before the failure."
        )
        print(f"NewsTrace pipeline error: {type(exc).__name__}: {exc}")
        return None, None

def create_chart(df):
    """Bar chart of top authors"""
    if 'author' not in df.columns:
        return None
    
    counts = df[df['author'] != 'Unknown']['author'].value_counts().head(10)
    if len(counts) == 0:
        return None
    
    fig = go.Figure(data=[go.Bar(
        x=counts.values,
        y=counts.index,
        orientation='h',
        text=counts.values,
        texttemplate='%{text}',
        marker=dict(color='#8B302B', line=dict(color='rgba(139,48,43,0.18)', width=1)),
        hovertemplate='%{y}: %{x} articles<extra></extra>'
    )])
    
    fig.update_layout(
        title='Top 10 Authors by Article Count',
        height=400,
        showlegend=False,
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#2B241E', family='Source Sans 3, Georgia, serif'),
        xaxis=dict(title='Articles', tickmode='linear', dtick=1, gridcolor='rgba(74,61,45,0.12)', zeroline=False, color='#675C4E'),
        yaxis=dict(title='', autorange='reversed', color='#2B241E'),
        margin=dict(l=150, r=20, t=40, b=40)
    )
    return fig


def create_author_section_network(df, max_authors=40):
    """Create a lightweight author-section network where author node size scales with article count."""
    if 'author' not in df.columns:
        return None

    # Prepare counts and main section per author
    clean = df[df['author'].notna() & (df['author'] != 'Unknown')].copy()
    if clean.empty:
        return None

    counts = clean['author'].value_counts().head(max_authors)
    top_authors = counts.index.tolist()

    # Determine dominant section per author (fallback to 'General')
    section_col = 'section' if 'section' in clean.columns else None
    author_section = {}
    for a in top_authors:
        sub = clean[clean['author'] == a]
        if section_col and sub[section_col].notna().any():
            sec = sub[section_col].fillna('General').value_counts().idxmax()
        else:
            sec = 'General'
        author_section[a] = sec

    sections = sorted(set(author_section.values()))
    if not sections:
        sections = ['General']

    import math
    # Layout: place sections on a circle, authors near their section with jitter
    R = 1.0
    section_pos = {}
    for i, s in enumerate(sections):
        angle = 2 * math.pi * i / max(len(sections), 1)
        section_pos[s] = (R * math.cos(angle), R * math.sin(angle))

    # Author node positions
    author_pos = {}
    for a in top_authors:
        sx, sy = section_pos[author_section[a]]
        # small radial offset based on hash for spread
        h = abs(hash(a)) % 1000 / 1000.0
        radius = 0.35 + 0.25 * h
        angle = (abs(hash(a + 'theta')) % 1000) / 1000.0 * 2 * math.pi
        ax = sx * 0.65 + radius * math.cos(angle)
        ay = sy * 0.65 + radius * math.sin(angle)
        author_pos[a] = (ax, ay)

    # Edge traces (author -> section)
    edge_x, edge_y = [], []
    for a in top_authors:
        x0, y0 = author_pos[a]
        x1, y1 = section_pos[author_section[a]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=1.25, color='rgba(111,77,61,0.38)'),  # Increased width and opacity
        hoverinfo='none', mode='lines'
    )

    # Section nodes
    sx, sy, stext = [], [], []
    for s in sections:
        x, y = section_pos[s]
        sx.append(x); sy.append(y); stext.append(f"Section: {s}")

    section_trace = go.Scatter(
        x=sx, y=sy, mode='markers+text',
        marker=dict(size=18, color='rgba(139,48,43,0.90)', line=dict(color='rgba(242,235,221,0.9)', width=1)),
        text=sections, textposition='top center',
        hovertext=stext, hoverinfo='text',
        name='Sections'
    )

    # Author nodes (size scaled by article count)
    ax, ay, asize, atext = [], [], [], []
    for a in top_authors:
        x, y = author_pos[a]
        ax.append(x); ay.append(y)
        c = counts[a]
        size = 8 + 4 * math.sqrt(c)
        asize.append(size)
        atext.append(f"{a} • {c} articles • {author_section[a]}")

    author_trace = go.Scatter(
        x=ax, y=ay, mode='markers',
        marker=dict(size=asize, color='rgba(67,73,61,0.88)', line=dict(color='rgba(242,235,221,0.9)', width=1)),
        hovertext=atext, hoverinfo='text',
        name='Authors'
    )

    fig = go.Figure(data=[edge_trace, section_trace, author_trace])
    fig.update_layout(
        title='Author–Section Network (node size = article count)',
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        showlegend=False, height=520, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#2B241E', family='Source Sans 3, Georgia, serif'),
        margin=dict(l=20, r=20, t=50, b=20)
    )
    return fig


def display_journalist_profiles(df):
    """Display top journalists with all available info"""
    if 'author' not in df.columns:
        return
    
    # Group by author
    author_groups = df[df['author'] != 'Unknown'].groupby('author')
    
    profiles = []
    for author, group in author_groups:
        profile = {
            'Name': author,
            'Articles': len(group)
        }
        
        # Add role if available
        if 'author_role' in group.columns:
            role = group['author_role'].dropna().iloc[0] if len(group['author_role'].dropna()) > 0 else None
            if role:
                profile['💼 Role'] = role
        
        # Add email if available
        if 'author_email' in group.columns:
            email = group['author_email'].dropna().iloc[0] if len(group['author_email'].dropna()) > 0 else None
            if email:
                profile['📧 Email'] = email
        
        # Add social media
        social_links = []
        for platform, emoji in [('twitter', '🐦'), ('linkedin', '💼'), ('instagram', '📸'), ('facebook', '👥')]:
            if platform in group.columns:
                handle = group[platform].dropna().iloc[0] if len(group[platform].dropna()) > 0 else None
                if handle:
                    social_links.append(f"{emoji} {handle}")
        
        if social_links:
            profile['🔗 Social'] = ' | '.join(social_links)
        
        # Add sample articles
        titles = group['title'].head(3).tolist()
        profile['📄 Recent'] = ' | '.join(titles)[:100] + ('...' if len(' | '.join(titles)) > 100 else '')
        
        profiles.append(profile)
    
    # Sort by article count
    profiles_df = pd.DataFrame(profiles).sort_values('Articles', ascending=False).head(15)
    st.dataframe(profiles_df, width='stretch', height=500, hide_index=True)



# ==================== NEWSROOM WORKSPACE ====================

def inject_newsroom_styles():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Source+Sans+3:wght@400;500;600;700&display=swap');

        :root {
            --paper: #F2EBDD;
            --paper-light: #F8F3E9;
            --paper-deep: #E5D9C5;
            --ink: #29231D;
            --ink-soft: #5B5145;
            --ink-faint: #827665;
            --rule: rgba(58, 46, 34, .34);
            --rule-light: rgba(58, 46, 34, .16);
            --red: #852F2A;
            --red-deep: #67231F;
            --olive: #4F5947;
            --serif: 'Cormorant Garamond', 'Bodoni MT', Georgia, serif;
            --sans: 'Source Sans 3', 'Segoe UI', sans-serif;
            --mono: 'IBM Plex Mono', 'Courier New', monospace;
        }

        html, body, [class*="css"], .stApp {
            font-family: var(--sans);
            color: var(--ink);
            background: var(--paper);
        }
        .stApp {
            background:
                radial-gradient(ellipse at 12% 5%, rgba(255,255,255,.45), transparent 34%),
                radial-gradient(ellipse at 88% 24%, rgba(154,118,73,.07), transparent 30%),
                repeating-linear-gradient(0deg, rgba(82,65,45,.018) 0, rgba(82,65,45,.018) 1px, transparent 1px, transparent 4px),
                var(--paper);
        }
        [data-testid="stAppViewContainer"] { background: transparent; }
        [data-testid="stHeader"] { background: rgba(242,235,221,.9); }
        [data-testid="stToolbar"] { right: 1rem; }
        .block-container {
            max-width: 1370px;
            padding: 1.1rem 2.2rem 4.5rem;
        }
        [data-testid="stSidebar"] {
            background: #E8DECD;
            border-right: 1px solid var(--rule);
        }
        [data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }
        [data-testid="stSidebar"] p, [data-testid="stSidebar"] label { color: var(--ink-soft); }
        [data-testid="stSidebar"] hr { border-color: var(--rule-light); }

        /* Fine paper grain, kept light enough for long-form reading. */
        .stApp::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            opacity: .13;
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.92' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.22'/%3E%3C/svg%3E");
            mix-blend-mode: multiply;
        }
        .block-container { position: relative; z-index: 1; }

        .nt-masthead-wrap {
            width: 100%;
            margin: 0 auto 1.15rem;
            border-top: 1px solid var(--rule);
            border-bottom: 3px double var(--ink);
            background: rgba(248,243,233,.28);
        }
        .nt-topline {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            padding: 8px 0 7px;
            color: var(--ink-soft);
            border-bottom: 1px solid var(--rule-light);
            font: 10px var(--mono);
            letter-spacing: .1em;
            text-transform: uppercase;
        }
        .nt-masthead {
            text-align: center;
            padding: 14px 0 11px;
        }
        .nt-wordmark {
            color: var(--ink);
            font: 700 clamp(56px, 9.2vw, 118px)/.78 var(--serif);
            letter-spacing: -.075em;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .nt-masthead-deck {
            margin-top: 13px;
            color: var(--red);
            font: 600 11px var(--mono);
            text-transform: uppercase;
            letter-spacing: .34em;
        }
        .nt-masthead-bottom {
            display: flex;
            justify-content: center;
            gap: 16px;
            flex-wrap: wrap;
            padding-top: 9px;
            color: var(--ink-soft);
            font: 9px var(--mono);
            letter-spacing: .16em;
            text-transform: uppercase;
        }
        .nt-nav {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 0;
            border-top: 1px solid var(--rule);
            border-bottom: 1px solid var(--rule);
            margin-bottom: 1.15rem;
        }
        .nt-nav span {
            color: var(--ink);
            padding: 9px 18px 8px;
            font: 600 10px var(--mono);
            letter-spacing: .11em;
            text-transform: uppercase;
            border-right: 1px solid var(--rule-light);
        }
        .nt-nav span:last-child { border-right: 0; }
        .nt-edition-label {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid var(--rule);
            color: var(--red);
            font: 600 10px var(--mono);
            letter-spacing: .17em;
            text-transform: uppercase;
        }
        .nt-front-intro {
            display: grid;
            grid-template-columns: 1fr 220px;
            gap: 26px;
            align-items: end;
            padding: 24px 0 19px;
            border-bottom: 3px double var(--ink);
        }
        .nt-front-kicker {
            color: var(--red);
            font: 600 10px var(--mono);
            letter-spacing: .18em;
            text-transform: uppercase;
        }
        .nt-front-title {
            margin: 7px 0 7px;
            max-width: 1050px;
            color: var(--ink);
            font: 600 clamp(42px, 6vw, 80px)/.91 var(--serif);
            letter-spacing: -.045em;
        }
        .nt-front-copy {
            max-width: 740px;
            margin-top: 9px;
            color: var(--ink-soft);
            font: 16px/1.55 var(--serif);
        }
        .nt-edition-note {
            border-left: 1px solid var(--rule);
            padding-left: 18px;
            color: var(--ink-soft);
            font: 11px/1.65 var(--mono);
            text-transform: uppercase;
            letter-spacing: .06em;
        }
        .nt-edition-note strong {
            display: block;
            color: var(--red);
            font: 600 23px/1.1 var(--serif);
            letter-spacing: 0;
            text-transform: none;
            margin-bottom: 5px;
        }

        .nt-section-cap {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: baseline;
            margin: 26px 0 9px;
            padding-bottom: 6px;
            border-bottom: 2px solid var(--ink);
        }
        .nt-section-cap h2 {
            margin: 0;
            color: var(--ink);
            font: 700 21px/1 var(--serif);
            letter-spacing: -.015em;
            text-transform: uppercase;
        }
        .nt-section-cap span {
            color: var(--red);
            font: 9px var(--mono);
            letter-spacing: .15em;
            text-transform: uppercase;
        }
        .nt-rule { border-top: 1px solid var(--rule); margin: 12px 0; }

        .nt-lead {
            display: grid;
            grid-template-columns: minmax(0, 1.28fr) minmax(260px, .72fr);
            gap: 0;
            border-bottom: 1px solid var(--rule);
            padding-bottom: 22px;
        }
        .nt-lead-copy {
            padding: 4px 26px 4px 0;
            border-right: 1px solid var(--rule);
        }
        .nt-story-section {
            color: var(--red);
            font: 600 9px var(--mono);
            text-transform: uppercase;
            letter-spacing: .17em;
        }
        .nt-lead-headline {
            margin: 8px 0 9px;
            color: var(--ink);
            font: 600 clamp(32px, 4.3vw, 58px)/.94 var(--serif);
            letter-spacing: -.035em;
        }
        .nt-lead-dek {
            max-width: 760px;
            color: var(--ink-soft);
            font: 17px/1.5 var(--serif);
            margin: 9px 0 13px;
        }
        .nt-byline {
            color: var(--ink-faint);
            font: 9px var(--mono);
            letter-spacing: .08em;
            text-transform: uppercase;
        }
        .nt-lead-media {
            min-height: 250px;
            margin: 3px 0 0 24px;
            overflow: hidden;
            position: relative;
            isolation: isolate;
            background:
                linear-gradient(135deg, rgba(75,63,50,.12), rgba(75,63,50,.02)),
                repeating-linear-gradient(135deg, rgba(65,53,42,.08) 0, rgba(65,53,42,.08) 1px, transparent 1px, transparent 5px),
                #D8CBB5;
            border: 1px solid rgba(75,58,42,.35);
        }
        .nt-lead-media img, .nt-story-media img {
            position: relative;
            z-index: 0;
            width: 100%;
            height: 100%;
            min-height: inherit;
            display: block;
            object-fit: cover;
            filter: grayscale(100%) sepia(17%) contrast(1.13);
            transition: filter .65s cubic-bezier(.2,.7,.2,1), transform .85s cubic-bezier(.2,.7,.2,1);
        }
        .nt-lead-media::after, .nt-story-media::after {
            content: "";
            position: absolute;
            z-index: 1;
            inset: 0;
            pointer-events: none;
            opacity: .18;
            background-image: radial-gradient(rgba(38,31,24,.56) .55px, transparent .75px);
            background-size: 3px 3px;
            mix-blend-mode: multiply;
            transition: opacity .65s ease;
        }
        .nt-lead-media:hover::after, .nt-story-card:hover .nt-story-media::after { opacity: .06; }
        .nt-lead-media .nt-image-caption, .nt-story-media .nt-image-caption { z-index: 2; }
        .nt-lead-media:hover img, .nt-story-card:hover .nt-story-media img {
            filter: grayscale(65%) sepia(10%) contrast(1.17);
            transform: scale(1.025);
        }
        .nt-image-caption {
            position: absolute;
            bottom: 0;
            right: 0;
            padding: 5px 8px;
            color: #F7F0E4;
            background: rgba(41,35,29,.82);
            font: 8px var(--mono);
            letter-spacing: .06em;
            text-transform: uppercase;
        }
        .nt-no-image {
            display: grid;
            place-items: center;
            height: 100%;
            min-height: 250px;
            color: rgba(54,43,33,.76);
            background:
                radial-gradient(circle at center, transparent 0 28%, rgba(92,68,45,.13) 28.4% 28.8%, transparent 29.2%),
                repeating-linear-gradient(45deg, rgba(70,54,37,.045) 0, rgba(70,54,37,.045) 1px, transparent 1px, transparent 4px),
                #D8CBB5;
            font: 600 58px var(--serif);
            letter-spacing: -.07em;
        }
        .nt-story-grid {
            display: grid;
            grid-template-columns: repeat(12, minmax(0,1fr));
            grid-auto-flow: dense;
            gap: 0;
            border-bottom: 2px solid var(--ink);
        }
        .nt-story-card {
            min-width: 0;
            grid-column: span 4;
            padding: 17px 17px 19px 0;
            border-right: 1px solid var(--rule);
            border-bottom: 1px solid var(--rule);
            transition: background .35s ease;
        }
        .nt-story-card:nth-child(3n+2) { padding-left: 17px; }
        .nt-story-card:nth-child(3n) {
            padding-left: 17px;
            padding-right: 0;
            border-right: 0;
        }
        .nt-story-card:hover { background: rgba(255,255,255,.18); }
        .nt-story-card.span-6 { grid-column: span 6; }
        .nt-story-card.span-12 { grid-column: span 12; }
        .nt-story-headline {
            margin: 7px 0 7px;
            color: var(--ink);
            font: 600 clamp(22px, 2.5vw, 33px)/.98 var(--serif);
            letter-spacing: -.025em;
        }
        .nt-story-dek {
            margin: 7px 0 10px;
            color: var(--ink-soft);
            font: 14px/1.48 var(--serif);
        }
        .nt-story-media {
            position: relative;
            isolation: isolate;
            height: 150px;
            margin: 11px 0 8px;
            overflow: hidden;
            border: 1px solid rgba(75,58,42,.35);
            background:
                repeating-linear-gradient(135deg, rgba(65,53,42,.07) 0, rgba(65,53,42,.07) 1px, transparent 1px, transparent 5px),
                #D8CBB5;
        }
        .nt-story-media img { min-height: 150px; height: 150px; }
        .nt-story-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 5px 11px;
            color: var(--ink-faint);
            font: 8px var(--mono);
            letter-spacing: .04em;
            text-transform: uppercase;
        }
        .nt-story-link {
            color: inherit;
            text-decoration: none;
            border-bottom: 1px solid transparent;
            transition: color .3s ease, border-color .3s ease;
        }
        .nt-story-link:hover { color: var(--red); border-color: var(--red); }

        .nt-investigation-shell {
            margin: 23px 0 18px;
            padding: 16px 18px 12px;
            border-top: 3px double var(--ink);
            border-bottom: 1px solid var(--ink);
            background: rgba(255,255,255,.18);
        }
        .nt-investigation-head {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 9px;
        }
        .nt-investigation-head h3 {
            margin: 0;
            color: var(--ink);
            font: 600 28px/1 var(--serif);
        }
        .nt-investigation-head span {
            color: var(--red);
            font: 9px var(--mono);
            letter-spacing: .14em;
            text-transform: uppercase;
        }

        .nt-metric-label {
            color: var(--red);
            font: 9px var(--mono);
            text-transform: uppercase;
            letter-spacing: .1em;
        }
        [data-testid="stMetric"] {
            background: rgba(255,255,255,.23);
            border: 0;
            border-top: 2px solid var(--ink);
            border-bottom: 1px solid var(--rule);
            border-radius: 0;
            padding: 11px 13px 10px;
            min-height: 92px;
        }
        [data-testid="stMetricLabel"] p {
            color: var(--ink-soft) !important;
            font: 9px var(--mono) !important;
            text-transform: uppercase;
            letter-spacing: .08em;
        }
        [data-testid="stMetricValue"] {
            color: var(--ink) !important;
            font: 600 30px/1 var(--serif) !important;
            letter-spacing: -.02em;
        }
        [data-testid="stMetricDelta"] { color: var(--red) !important; font: 10px var(--mono) !important; }

        [data-testid="stTextInput"] label,
        [data-testid="stSelectbox"] label,
        [data-testid="stSlider"] label,
        [data-testid="stCheckbox"] label {
            color: var(--ink-soft) !important;
            font: 10px var(--mono) !important;
            letter-spacing: .05em;
            text-transform: uppercase;
        }
        [data-testid="stTextInput"] input,
        [data-testid="stSelectbox"] [data-baseweb="select"] > div {
            color: var(--ink) !important;
            background: var(--paper-light) !important;
            border: 1px solid var(--rule) !important;
            border-radius: 0 !important;
        }
        [data-testid="stTextInput"] input:focus {
            border-color: var(--red) !important;
            box-shadow: 0 0 0 1px rgba(133,47,42,.15) !important;
        }
        [data-testid="stExpander"] {
            border: 1px solid var(--rule-light);
            border-radius: 0;
            background: rgba(255,255,255,.16);
        }
        .stButton > button, [data-testid="stFormSubmitButton"] button, .stDownloadButton > button {
            min-height: 38px;
            color: var(--paper-light) !important;
            background: var(--red) !important;
            border: 1px solid var(--red) !important;
            border-radius: 0 !important;
            font: 600 10px var(--mono) !important;
            letter-spacing: .08em;
            text-transform: uppercase;
            transition: background .3s ease, transform .3s cubic-bezier(.2,.7,.2,1);
        }
        .stButton > button:hover, [data-testid="stFormSubmitButton"] button:hover, .stDownloadButton > button:hover {
            background: var(--red-deep) !important;
            transform: translateY(-1px);
            border-color: var(--red-deep) !important;
        }
        .stDownloadButton > button {
            color: var(--ink) !important;
            background: transparent !important;
            border-color: var(--rule) !important;
        }
        .stDownloadButton > button:hover {
            color: var(--red) !important;
            background: rgba(255,255,255,.35) !important;
        }
        [data-testid="stTabs"] [role="tablist"] {
            gap: 0;
            border-bottom: 2px solid var(--ink);
        }
        [data-testid="stTabs"] button[role="tab"] {
            padding: 10px 17px;
            color: var(--ink-soft);
            font: 600 10px var(--mono);
            letter-spacing: .08em;
            text-transform: uppercase;
            border-radius: 0;
        }
        [data-testid="stTabs"] button[aria-selected="true"] {
            color: var(--red) !important;
            background: rgba(255,255,255,.22);
            border-bottom: 2px solid var(--red) !important;
        }
        [data-testid="stDataFrame"], [data-testid="stPlotlyChart"] {
            border: 1px solid var(--rule-light);
            border-radius: 0;
            background: rgba(255,255,255,.2);
        }
        [data-testid="stStatusWidget"], [data-testid="stAlert"] { border-radius: 0 !important; }
        [data-testid="stCaptionContainer"] { color: var(--ink-faint); }
        hr { border-color: var(--rule) !important; }
        .nt-footer {
            margin-top: 36px;
            padding: 11px 0 0;
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 10px;
            border-top: 3px double var(--ink);
            color: var(--ink-faint);
            font: 9px var(--mono);
            letter-spacing: .1em;
            text-transform: uppercase;
        }
        .nt-empty {
            padding: 28px 16px;
            text-align: center;
            border-top: 1px solid var(--rule);
            border-bottom: 1px solid var(--rule);
            background: rgba(255,255,255,.16);
        }
        .nt-empty h3 {
            color: var(--ink);
            font: 600 27px/1.05 var(--serif);
            margin: 0 0 6px;
        }
        .nt-empty p { color: var(--ink-soft); font: 14px/1.5 var(--serif); margin: 0; }

        @media (max-width: 900px) {
            .block-container { padding: 1rem 1.2rem 3rem; }
            .nt-front-intro { grid-template-columns: 1fr; }
            .nt-edition-note { display: none; }
            .nt-lead { grid-template-columns: 1fr; }
            .nt-lead-copy { border-right: 0; padding-right: 0; }
            .nt-lead-media { margin: 16px 0 0; min-height: 230px; }
            .nt-story-card { grid-column: span 6; }
            .nt-story-card:nth-child(3n) { padding-left: 0; padding-right: 17px; border-right: 1px solid var(--rule); }
            .nt-story-card:nth-child(2n) { padding-left: 17px; padding-right: 0; border-right: 0; }
            .nt-story-card:nth-child(3n+2) { padding-left: 17px; }
        }
        @media (max-width: 600px) {
            .block-container { padding: .7rem .8rem 2.2rem; }
            .nt-topline { font-size: 8px; }
            .nt-wordmark { font-size: clamp(42px, 13vw, 67px); }
            .nt-masthead-deck { font-size: 8px; letter-spacing: .2em; }
            .nt-nav span { padding: 8px 9px; font-size: 8px; }
            .nt-front-title { font-size: clamp(37px, 11vw, 53px); }
            .nt-lead-headline { font-size: 38px; }
            .nt-story-card, .nt-story-card.span-6, .nt-story-card.span-12 { grid-column: span 12; }
            .nt-story-card, .nt-story-card:nth-child(2n), .nt-story-card:nth-child(3n), .nt-story-card:nth-child(3n+2) {
                padding: 15px 0;
                border-right: 0;
            }
            .nt-story-media { height: 185px; }
            .nt-story-media img { height: 185px; }
            [data-testid="stMetricValue"] { font-size: 25px !important; }
            [data-testid="stTabs"] button[role="tab"] { padding: 8px 8px; font-size: 8px; }
        }
        @keyframes nt-column-reveal {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .nt-front-intro, .nt-lead { animation: nt-column-reveal .62s cubic-bezier(.2,.7,.2,1) both; }
        .nt-story-card { animation: nt-column-reveal .62s cubic-bezier(.2,.7,.2,1) both; }
        .nt-story-card:nth-child(2) { animation-delay: .07s; }
        .nt-story-card:nth-child(3) { animation-delay: .13s; }
        .nt-story-card:nth-child(4) { animation-delay: .19s; }
        .nt-story-card:nth-child(5) { animation-delay: .25s; }
        .nt-story-card:nth-child(6) { animation-delay: .31s; }
        .nt-story-card:nth-child(7) { animation-delay: .37s; }
        @media (prefers-reduced-motion: reduce) {
            .nt-front-intro, .nt-lead, .nt-story-card { animation: none !important; }
            *, *::before, *::after {
                animation-duration: .01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: .01ms !important;
                scroll-behavior: auto !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _local_edition_date():
    try:
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now()


def _safe_url(value):
    value = str(value or "").strip()
    return value if value.startswith(("https://", "http://")) else ""


def _date_label(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "DATE NOT REPORTED"
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(parsed):
            return escape(str(value)[:36])
        return parsed.strftime("%d %b %Y").upper()
    except Exception:
        return escape(str(value)[:36])


def _article_section(row):
    raw = row.get("section") if hasattr(row, "get") else None
    value = str(raw or "GENERAL").strip()
    return escape(value.upper()[:48])


def _story_image(url, alt, lead=False):
    safe_url = _safe_url(url)
    class_name = "nt-lead-media" if lead else "nt-story-media"
    if safe_url:
        return (
            f'<div class="{class_name}"><img src="{escape(safe_url, quote=True)}" '
            f'alt="{escape(str(alt), quote=True)}" loading="lazy">'
            '<span class="nt-image-caption">SOURCE IMAGE / EDITORIAL ARCHIVE</span></div>'
        )
    if lead:
        return (
            '<div class="nt-lead-media"><div class="nt-no-image">N</div>'
            '<span class="nt-image-caption">NEWS TRACE / RECORD NO IMAGE</span></div>'
        )
    return ""


def _story_card(row, variant=""):
    title = escape(str(row.get("title") or "Untitled report").strip())
    author = escape(str(row.get("author") or "Unknown").strip())
    section = _article_section(row)
    date = _date_label(row.get("date"))
    url = _safe_url(row.get("url"))
    image_url = row.get("image_url")
    raw_summary = row.get("description") or row.get("summary") or row.get("author_bio") or ""
    summary = escape(str(raw_summary).strip()[:210])
    if not summary:
        summary = "A source-linked report collected for this NewsTrace investigation."

    media = _story_image(image_url, title) if image_url else ""
    title_html = f'<a class="nt-story-link" href="{escape(url, quote=True)}" target="_blank" rel="noopener">{title}</a>' if url else title
    return (
        f'<article class="nt-story-card {variant}">'
        f'<div class="nt-story-section">{section}</div>'
        f'<h3 class="nt-story-headline">{title_html}</h3>'
        f'<p class="nt-story-dek">{summary}</p>'
        f'{media}'
        f'<div class="nt-story-meta"><span>BY {author}</span><span>{date}</span>'
        f'<span>{("READ SOURCE" if url else "SOURCE URL UNAVAILABLE")}</span></div>'
        '</article>'
    )


def _render_masthead(edition_date, edition_name="INDIA / WORLD EDITION"):
    date_text = edition_date.strftime("%A · %d %B %Y").upper()
    html = f"""
    <div class="nt-masthead-wrap">
      <div class="nt-topline">
        <span>VOL. 01 &nbsp; / &nbsp; ISSUE {edition_date.strftime('%j')}</span>
        <span>{escape(edition_name)}</span>
        <span>{date_text} &nbsp; · &nbsp; IST</span>
      </div>
      <div class="nt-masthead">
        <div class="nt-wordmark">NewsTrace</div>
        <div class="nt-masthead-deck">The Digital News Chronicle</div>
        <div class="nt-masthead-bottom">
          <span>WORLD</span><span>POLITICS</span><span>TECHNOLOGY</span>
          <span>SCIENCE</span><span>BUSINESS</span><span>CULTURE</span>
        </div>
      </div>
    </div>
    """
    motion_html = f"""
    <!doctype html><html><head><meta charset="utf-8">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
      *{{box-sizing:border-box}} body{{margin:0;background:transparent;color:#29231D}}
      .paper{{background:transparent;padding:0 0 2px;font-family:'IBM Plex Mono',monospace}}
      .top{{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;border-top:1px solid rgba(58,46,34,.5);border-bottom:1px solid rgba(58,46,34,.2);padding:8px 0;color:#5B5145;font-size:9px;letter-spacing:.1em;text-transform:uppercase}}
      .mast{{text-align:center;padding:17px 0 12px}}
      .word{{font:700 clamp(62px,9vw,116px)/.76 'Cormorant Garamond',Georgia,serif;letter-spacing:-.075em;text-transform:uppercase;white-space:nowrap}}
      .deck{{margin-top:13px;color:#852F2A;font:600 10px 'IBM Plex Mono',monospace;letter-spacing:.32em;text-transform:uppercase}}
      .topics{{display:flex;justify-content:center;gap:15px;flex-wrap:wrap;margin-top:11px;color:#5B5145;font:9px 'IBM Plex Mono',monospace;letter-spacing:.12em;text-transform:uppercase}}
      .bottom-rule{{height:3px;border-top:1px solid #29231D;border-bottom:1px solid #29231D;margin-top:8px}}
      .word,.deck,.topics,.top{{opacity:1;transform:none}}
      @media(max-width:600px){{.word{{font-size:clamp(46px,12vw,70px)}}.deck{{font-size:8px;letter-spacing:.18em}}.topics{{font-size:7px;gap:9px}}.top{{font-size:7px}}}}
      @media(prefers-reduced-motion:reduce){{*{{animation:none!important;transition:none!important}}}}
    </style></head><body><div class="paper">
      <div class="top"><span>VOL. 01 / ISSUE {edition_date.strftime('%j')}</span><span>{escape(edition_name)}</span><span>{date_text} · IST</span></div>
      <header class="mast"><div class="word">NewsTrace</div><div class="deck">The Digital News Chronicle</div>
        <nav class="topics"><span>World</span><span>Politics</span><span>Technology</span><span>Science</span><span>Business</span><span>Culture</span></nav>
      </header><div class="bottom-rule"></div>
    </div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
    <script>
      (function(){{
        if(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        if(!window.gsap) return;
        const gsap = window.gsap;
        gsap.fromTo('.top',{{opacity:0,y:-8}},{{opacity:1,y:0,duration:.45,ease:'power2.out'}});
        gsap.fromTo('.word',{{opacity:0,y:22,letterSpacing:'-.02em'}},{{opacity:1,y:0,letterSpacing:'-.075em',duration:.8,delay:.08,ease:'power3.out'}});
        gsap.fromTo('.deck, .topics',{{opacity:0,y:9}},{{opacity:1,y:0,duration:.42,delay:.36,stagger:.08,ease:'power2.out'}});
        gsap.fromTo('.bottom-rule',{{scaleX:0,transformOrigin:'left center'}},{{scaleX:1,duration:.75,delay:.18,ease:'power2.inOut'}});
      }})();
    </script></body></html>
    """
    st.components.v1.html(motion_html, height=204, scrolling=False)


def get_database_status():
    try:
        return check_connection()
    except Exception as exc:
        return False, str(exc)


inject_newsroom_styles()
edition_date = _local_edition_date()
_render_masthead(edition_date)

st.markdown(
    """
    <div class="nt-nav">
      <span>Front Page</span><span>World Desk</span><span>Politics</span>
      <span>Technology</span><span>Business</span><span>Culture</span>
      <span>Archive</span>
    </div>
    <div class="nt-edition-label">
      <span>THE DAILY INTELLIGENCE CHRONICLE</span>
      <span>REPORTS / SOURCES / PEOPLE / PATTERNS</span>
    </div>
    """,
    unsafe_allow_html=True,
)

db_connected, db_message = get_database_status()
connection_text = "ARCHIVE CONNECTED" if db_connected else "SESSION ARCHIVE"

if "df" in st.session_state and st.session_state["df"] is not None:
    df = st.session_state["df"].copy()
    if "author" not in df.columns:
        df["author"] = "Unknown"
    df["author"] = df["author"].fillna("Unknown")
    article_total = len(df)
    known_authors = df.loc[df["author"] != "Unknown", "author"].nunique()
    current_outlet = str(st.session_state.get("outlet", "Current investigation"))
    current_stats = st.session_state.get("stats", {})
    lead = df.iloc[0]
    lead_title = escape(str(lead.get("title") or "Untitled report"))
    lead_author = escape(str(lead.get("author") or "Unknown"))
    lead_section = _article_section(lead)
    lead_date = _date_label(lead.get("date"))
    lead_summary = escape(str(lead.get("description") or lead.get("summary") or "A report collected from the publication and retained with its source URL."))
    lead_url = _safe_url(lead.get("url"))
    lead_image = lead.get("image_url")
    lead_link = (
        f'<a href="{escape(lead_url, quote=True)}" target="_blank" rel="noopener">OPEN ORIGINAL REPORT ↗</a>'
        if lead_url else '<span>SOURCE LINK NOT AVAILABLE</span>'
    )
    st.markdown(
        f"""
        <div class="nt-front-intro">
          <div>
            <div class="nt-front-kicker">CURRENT INVESTIGATION / {escape(current_outlet.upper())}</div>
            <h1 class="nt-front-title">The stories. The sources. The people behind them.</h1>
            <p class="nt-front-copy">A source-led reading of the coverage gathered from {escape(current_outlet)}. Every result below remains connected to its original publication.</p>
          </div>
          <div class="nt-edition-note"><strong>{article_total:,}</strong> ARTICLES IN THIS EDITION<br><br>{known_authors:,} IDENTIFIED JOURNALISTS<br><br>{connection_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="nt-section-cap"><h2>Lead report</h2><span>THE FRONT PAGE / {lead_section}</span></div>
        <article class="nt-lead">
          <div class="nt-lead-copy">
            <div class="nt-story-section">{lead_section}</div>
            <h2 class="nt-lead-headline">{lead_title}</h2>
            <p class="nt-lead-dek">{lead_summary}</p>
            <div class="nt-byline">BY {lead_author} &nbsp; · &nbsp; {lead_date}</div>
            <div style="margin-top:15px;color:var(--red);font:600 9px var(--mono);letter-spacing:.12em">{lead_link}</div>
          </div>
          {_story_image(lead_image, lead_title, lead=True)}
        </article>
        """,
        unsafe_allow_html=True,
    )

else:
    st.markdown(
        """
        <div class="nt-front-intro">
          <div>
            <div class="nt-front-kicker">INDEPENDENT REPORTING / INTELLIGENCE / CONTEXT</div>
            <h1 class="nt-front-title">Follow the story. Find the source.</h1>
            <p class="nt-front-copy">NewsTrace turns publication coverage into a searchable record of articles, journalists and the subjects they report on. Every investigation begins with a source.</p>
          </div>
          <div class="nt-edition-note"><strong>THE RECORD</strong>ARTICLE DISCOVERY<br><br>JOURNALIST INTELLIGENCE<br><br>COVERAGE ANALYSIS</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Investigation entry point. Existing resolver, scraper and optional enrichment
# controls remain intact; only the presentation has changed.
st.markdown(
    """
    <div class="nt-section-cap"><h2>Open an investigation</h2><span>THE NEWSROOM DESK</span></div>
    """,
    unsafe_allow_html=True,
)
with st.container():
    with st.form("newstrace_investigation", clear_on_submit=False):
        outlet = st.text_input(
            "Publication name or website",
            placeholder="Enter a publication or paste its full URL",
            help="A direct section URL is also accepted.",
        )
        with st.expander("Collection settings", expanded=False):
            settings_left, settings_mid, settings_right = st.columns(3)
            with settings_left:
                max_articles = st.slider("Maximum articles", 50, 1000, 300, 50)
            with settings_mid:
                enable_profiles = st.checkbox(
                    "Author profile enrichment",
                    value=False,
                    help="Visit public journalist profile pages for additional details.",
                )
            with settings_right:
                enable_google = st.checkbox(
                    "Search enrichment",
                    value=False,
                    help="Use your configured SerpAPI key to look for additional public profile information.",
                )
        submitted = st.form_submit_button("Run investigation  →", type="primary", use_container_width=True)

if submitted:
    if not outlet.strip():
        st.error("Enter a publication name or website URL to continue.")
    else:
        os.makedirs("data", exist_ok=True)
        df_result, stats_result = run_unified_pipeline(
            outlet.strip(), max_articles, enable_profiles, enable_google
        )
        if df_result is not None and not df_result.empty:
            st.session_state["df"] = df_result
            st.session_state["outlet"] = outlet.strip()
            st.session_state["stats"] = stats_result or {}
            if db_connected:
                with st.spinner("Recording this edition in the archive…"):
                    articles_result = save_articles(df_result, outlet)
                    profiles_result = save_journalist_profiles(df_result, outlet)
                if articles_result.get("success") or profiles_result.get("success"):
                    st.success(
                        f"Archived {articles_result.get('count', 0)} articles and "
                        f"{profiles_result.get('count', 0)} journalist profiles."
                    )
                else:
                    st.warning("The analysis completed, but the database did not confirm storage.")
            else:
                st.caption("This edition is available in the current session. Configure Supabase for persistent storage.")
            st.rerun()
        else:
            st.warning("No article records were returned. The status above explains whether discovery or page extraction failed.")

if "df" in st.session_state and st.session_state["df"] is not None:
    df = st.session_state["df"].copy()
    stats = st.session_state.get("stats", {})
    outlet_label = str(st.session_state.get("outlet", "Current investigation"))
    safe_outlet_label = escape(outlet_label)
    if "author" not in df.columns:
        df["author"] = "Unknown"
    df["author"] = df["author"].fillna("Unknown")

    authors = int(df.loc[df["author"] != "Unknown", "author"].nunique())
    article_count = len(df)
    unknown_count = int((df["author"] == "Unknown").sum())
    unknown_pct = (unknown_count / article_count * 100) if article_count else 0.0
    social_count = sum(
        int(df[col].notna().sum())
        for col in ("twitter", "linkedin", "instagram", "facebook")
        if col in df.columns
    )
    email_count = int(df["author_email"].notna().sum()) if "author_email" in df.columns else 0

    st.markdown(
        '<div class="nt-section-cap"><h2>Inside this edition</h2><span>THE RECORD AT A GLANCE</span></div>',
        unsafe_allow_html=True,
    )
    metric_cols = st.columns(4)
    metric_cols[0].metric("Articles collected", f"{article_count:,}")
    metric_cols[1].metric("Identified journalists", f"{authors:,}")
    metric_cols[2].metric("Public profile links", f"{social_count:,}")
    metric_cols[3].metric("Unknown bylines", f"{unknown_pct:.1f}%")

    st.markdown(
        f'<div class="nt-section-cap"><h2>From the pages</h2><span>{article_count:,} RECORDS / {safe_outlet_label.upper()}</span></div>',
        unsafe_allow_html=True,
    )
    story_rows = [row for _, row in df.head(7).iterrows()]
    if story_rows:
        lead_rows = story_rows[1:]
        card_html = '<div class="nt-story-grid">' + "".join(
            _story_card(row, "span-4") for row in lead_rows
        ) + "</div>"
        st.markdown(card_html, unsafe_allow_html=True)

    coverage_tab, journalists_tab, archive_tab = st.tabs(
        ["Coverage & analysis", "Journalist directory", "Search the archive"]
    )

    with coverage_tab:
        st.markdown(
            '<div class="nt-section-cap"><h2>Who is writing the story?</h2><span>COVERAGE INTELLIGENCE</span></div>',
            unsafe_allow_html=True,
        )
        left, right = st.columns([1, 1.2])
        with left:
            st.markdown("**Most active journalists**")
            chart = create_chart(df)
            if chart:
                chart.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#29231D", family="Cormorant Garamond, Georgia, serif"),
                    title=None, height=430,
                    xaxis=dict(gridcolor="rgba(58,46,34,.13)", color="#665B4E"),
                    yaxis=dict(color="#29231D"),
                )
                st.plotly_chart(chart, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Author activity will appear when the source pages expose bylines.")
        with right:
            st.markdown("**Relationships between journalists and sections**")
            network = create_author_section_network(df)
            if network:
                network.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#29231D", family="Cormorant Garamond, Georgia, serif"),
                )
                st.plotly_chart(network, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("The relationship map needs multiple identified journalists and sections.")

        if "section" in df.columns:
            st.markdown(
                '<div class="nt-section-cap"><h2>Sections in this edition</h2><span>EDITORIAL DISTRIBUTION</span></div>',
                unsafe_allow_html=True,
            )
            section_counts = (
                df["section"].fillna("Unclassified").replace("", "Unclassified")
                .value_counts().head(12).rename_axis("Section").reset_index(name="Articles")
            )
            st.dataframe(section_counts, use_container_width=True, hide_index=True)

        if stats:
            st.markdown(
                '<div class="nt-section-cap"><h2>How this edition was assembled</h2><span>PIPELINE RECORD</span></div>',
                unsafe_allow_html=True,
            )
            progress_cols = st.columns(4)
            progress_cols[0].metric("URLs discovered", f"{stats.get('urls_found', 0):,}")
            progress_cols[1].metric("Articles parsed", f"{stats.get('articles_scraped', article_count):,}")
            progress_cols[2].metric("Profiles enriched", f"{stats.get('profiles_found', 0):,}")
            progress_cols[3].metric("Search matches", f"{stats.get('google_enriched', 0):,}")

    with journalists_tab:
        st.markdown(
            '<div class="nt-section-cap"><h2>Journalist directory</h2><span>PEOPLE BEHIND THE BYLINES</span></div>',
            unsafe_allow_html=True,
        )
        if authors:
            display_journalist_profiles(df)
            author_rows = (
                df[df["author"] != "Unknown"].groupby("author")
                .agg(Articles=("title", "count"))
                .sort_values("Articles", ascending=False)
                .reset_index()
            )
            st.dataframe(author_rows, use_container_width=True, hide_index=True)
        else:
            st.markdown(
                '<div class="nt-empty"><h3>No identified bylines yet</h3><p>Articles were collected, but this publisher did not expose usable author names. Try enabling profile enrichment or another section URL.</p></div>',
                unsafe_allow_html=True,
            )

    with archive_tab:
        st.markdown(
            '<div class="nt-section-cap"><h2>Search the archive</h2><span>FIND A REPORT / BYLINE / SECTION</span></div>',
            unsafe_allow_html=True,
        )
        query_col, section_col = st.columns([1.5, 1])
        with query_col:
            record_query = st.text_input(
                "Search the archive",
                placeholder="Search headlines, authors, links and dates…",
                key="dataset_search",
            )
        with section_col:
            if "section" in df.columns:
                section_options = sorted(
                    set(df["section"].fillna("Unclassified").replace("", "Unclassified").astype(str).tolist())
                )
                chosen_section = st.selectbox(
                    "Newspaper section",
                    ["All sections"] + section_options,
                    key="dataset_section",
                )
            else:
                chosen_section = "All sections"

        filtered_df = df.copy()
        if chosen_section != "All sections" and "section" in filtered_df.columns:
            section_values = filtered_df["section"].fillna("Unclassified").replace("", "Unclassified").astype(str)
            filtered_df = filtered_df.loc[section_values == chosen_section]
        if record_query.strip():
            mask = filtered_df.astype(str).apply(
                lambda column: column.str.contains(
                    record_query.strip(), case=False, na=False, regex=False
                )
            ).any(axis=1)
            filtered_df = filtered_df.loc[mask]

        st.caption(f"{len(filtered_df):,} RECORDS SHOWN / {len(df):,} TOTAL")
        preferred_cols = [
            "author", "title", "section", "date", "url",
            "author_role", "author_email", "twitter", "linkedin",
        ]
        display_cols = [col for col in preferred_cols if col in filtered_df.columns]
        column_config = {}
        if "url" in display_cols:
            column_config["url"] = st.column_config.LinkColumn("Original report", display_text="Open source")
        if "author_email" in display_cols:
            column_config["author_email"] = st.column_config.TextColumn("Public email")
        if display_cols:
            st.dataframe(
                filtered_df[display_cols],
                use_container_width=True,
                height=510,
                hide_index=True,
                column_config=column_config,
            )
        else:
            st.dataframe(filtered_df, use_container_width=True, height=510, hide_index=True)

        export_note, export_csv, export_json = st.columns([2, 1, 1])
        with export_note:
            st.caption("Downloads contain the filtered records currently shown.")
        with export_csv:
            st.download_button(
                "Export CSV",
                filtered_df.to_csv(index=False).encode("utf-8"),
                f"{re.sub(r'[^A-Za-z0-9_-]+', '_', outlet_label).strip('_') or 'newstrace'}_archive.csv",
                "text/csv",
                use_container_width=True,
            )
        with export_json:
            st.download_button(
                "Export JSON",
                filtered_df.to_json(orient="records", indent=2).encode("utf-8"),
                f"{re.sub(r'[^A-Za-z0-9_-]+', '_', outlet_label).strip('_') or 'newstrace'}_archive.json",
                "application/json",
                use_container_width=True,
            )

    if authors:
        st.markdown(
            '<div class="nt-section-cap"><h2>Byline notes</h2><span>PUBLIC PROFILE SIGNALS</span></div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"{authors:,} journalists identified · {email_count:,} public email fields · "
            f"{social_count:,} public social-profile fields."
        )

else:
    st.markdown(
        """
        <div class="nt-empty">
          <h3>Every story leaves a trail.</h3>
          <p>Start with a publication or section URL to gather article records, identify bylines and map coverage. Results remain linked to their original sources.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    f"""
    <footer class="nt-footer">
      <span>NEWSTRACE / THE DIGITAL NEWS CHRONICLE</span>
      <span>{edition_date.strftime('%d %B %Y').upper()} / INDIA EDITION</span>
      <span>FACTS WITH SOURCES. STORIES WITH CONTEXT.</span>
    </footer>
    """,
    unsafe_allow_html=True,
)
