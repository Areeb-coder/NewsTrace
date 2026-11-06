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

# Page Config
st.set_page_config(page_title="NewsTrace · Media Intelligence", page_icon="🔎", layout="wide", initial_sidebar_state="expanded")

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
        urls = await collect_article_urls(
            start_url,
            max_articles,
            progress_callback=update_progress,
            max_pages=18,
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
        marker=dict(color='#67DDB5', line=dict(color='rgba(103,221,181,0.18)', width=1)),
        hovertemplate='%{y}: %{x} articles<extra></extra>'
    )])
    
    fig.update_layout(
        title='Top 10 Authors by Article Count',
        height=400,
        showlegend=False,
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#DCE7F2', family='Inter, ui-sans-serif, sans-serif'),
        xaxis=dict(title='Articles', tickmode='linear', dtick=1, gridcolor='rgba(168,185,205,0.12)', zeroline=False, color='#9BAFC3'),
        yaxis=dict(title='', autorange='reversed', color='#DCE7F2'),
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
        line=dict(width=1.5, color='rgba(103,221,181,0.30)'),  # Increased width and opacity
        hoverinfo='none', mode='lines'
    )

    # Section nodes
    sx, sy, stext = [], [], []
    for s in sections:
        x, y = section_pos[s]
        sx.append(x); sy.append(y); stext.append(f"Section: {s}")

    section_trace = go.Scatter(
        x=sx, y=sy, mode='markers+text',
        marker=dict(size=18, color='rgba(113,151,255,0.92)', line=dict(color='rgba(235,242,250,0.8)', width=1)),
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
        marker=dict(size=asize, color='rgba(103,221,181,0.92)', line=dict(color='rgba(235,242,250,0.8)', width=1)),
        hovertext=atext, hoverinfo='text',
        name='Authors'
    )

    fig = go.Figure(data=[edge_trace, section_trace, author_trace])
    fig.update_layout(
        title='Author–Section Network (node size = article count)',
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        showlegend=False, height=520, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#DCE7F2', family='Inter, ui-sans-serif, sans-serif'),
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
            '👤 Name': author,
            '📰 Articles': len(group)
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
    profiles_df = pd.DataFrame(profiles).sort_values('📰 Articles', ascending=False).head(15)
    st.dataframe(profiles_df, width='stretch', height=500, hide_index=True)



# ==================== NEWSROOM WORKSPACE ====================

def inject_newsroom_styles():
    st.markdown(
        """
        <style>
        :root {
            --nt-bg: #080F1B;
            --nt-panel: #101B2A;
            --nt-panel-soft: #132235;
            --nt-border: rgba(157, 180, 205, .14);
            --nt-text: #EAF1F8;
            --nt-muted: #93A6BA;
            --nt-accent: #67DDB5;
            --nt-blue: #87A9FF;
            --nt-amber: #F2C879;
        }

        html, body, [class*="css"] {
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        .stApp {
            background:
                radial-gradient(900px 480px at 78% -8%, rgba(58, 112, 133, .16), transparent 62%),
                radial-gradient(720px 420px at -8% 18%, rgba(37, 82, 125, .12), transparent 58%),
                var(--nt-bg);
            color: var(--nt-text);
        }
        [data-testid="stAppViewContainer"] { background: transparent; }
        [data-testid="stHeader"] { background: rgba(8, 15, 27, .76); }
        [data-testid="stToolbar"] { right: 1.2rem; }
        .block-container {
            max-width: 1480px;
            padding-top: 2.1rem;
            padding-bottom: 4rem;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0B1625 0%, #0A1421 100%);
            border-right: 1px solid var(--nt-border);
        }
        [data-testid="stSidebar"] > div:first-child { padding-top: 1.25rem; }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #A9B9C9; }
        [data-testid="stSidebar"] hr { border-color: var(--nt-border); }

        .nt-brand {
            display: flex; align-items: center; gap: 12px;
            padding: 10px 4px 22px;
        }
        .nt-brand-mark {
            width: 42px; height: 42px; border-radius: 13px;
            display: grid; place-items: center;
            color: #06140F; font-weight: 900; font-size: 19px;
            background: linear-gradient(145deg, #8BF0CB, #40B995);
            box-shadow: 0 8px 28px rgba(70, 202, 157, .18);
        }
        .nt-brand-name { color: #F1F6FB; font-size: 18px; font-weight: 750; letter-spacing: -.55px; }
        .nt-brand-sub { color: #7F96AB; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 9px; letter-spacing: 1.45px; margin-top: 3px; }
        .nt-side-label {
            color: #627B92; text-transform: uppercase; letter-spacing: 1.55px;
            font: 700 9px "JetBrains Mono", ui-monospace, monospace;
            margin: 10px 0 8px;
        }
        .nt-side-item {
            color: #B9C8D6; font-size: 13px; padding: 9px 10px;
            border-radius: 9px; margin: 2px 0; background: rgba(255,255,255,.025);
        }
        .nt-side-item.active {
            color: #DDF9EF; background: rgba(103,221,181,.09);
            border: 1px solid rgba(103,221,181,.16);
        }
        .nt-side-note { color: #748BA0; font-size: 11px; line-height: 1.55; }

        .nt-kicker {
            color: #80A2B5; text-transform: uppercase; letter-spacing: 2px;
            font: 700 10px "JetBrains Mono", ui-monospace, monospace;
        }
        .nt-hero {
            position: relative; overflow: hidden;
            border: 1px solid rgba(126, 166, 190, .17);
            border-radius: 22px; padding: 27px 30px 26px;
            background: linear-gradient(125deg, rgba(19, 36, 54, .96), rgba(12, 26, 41, .92));
            box-shadow: 0 22px 65px rgba(0,0,0,.18);
            margin-bottom: 22px;
        }
        .nt-hero:after {
            content: ""; position: absolute; width: 290px; height: 290px;
            right: -82px; top: -150px; border-radius: 50%;
            border: 1px solid rgba(103,221,181,.13);
            box-shadow: 0 0 0 28px rgba(103,221,181,.025), 0 0 0 58px rgba(103,221,181,.018);
            pointer-events: none;
        }
        .nt-hero-title {
            color: #F3F7FB; font-size: clamp(27px, 3.4vw, 39px);
            font-weight: 760; letter-spacing: -1.5px; line-height: 1.12;
            margin: 10px 0 9px;
        }
        .nt-hero-copy { max-width: 720px; color: #A6B8C8; font-size: 13px; line-height: 1.7; }
        .nt-hero-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
        .nt-chip {
            color: #C4D2DF; border: 1px solid rgba(167,190,212,.17);
            background: rgba(4,14,25,.30); border-radius: 999px;
            padding: 5px 10px; font: 10px "JetBrains Mono", ui-monospace, monospace;
        }
        .nt-status {
            display: inline-flex; align-items: center; gap: 7px;
            border-radius: 999px; padding: 6px 10px;
            border: 1px solid rgba(103,221,181,.22);
            background: rgba(103,221,181,.08); color: #A6EBD1;
            font: 10px "JetBrains Mono", ui-monospace, monospace;
            letter-spacing: .4px; white-space: nowrap;
        }
        .nt-status-dot {
            width: 6px; height: 6px; border-radius: 50%;
            background: #67DDB5; box-shadow: 0 0 10px rgba(103,221,181,.7);
        }
        .nt-section-head { margin: 25px 0 12px; }
        .nt-section-title { color: #EAF1F8; font-weight: 700; font-size: 17px; letter-spacing: -.35px; }
        .nt-section-copy { color: var(--nt-muted); font-size: 11px; margin-top: 4px; }
        .nt-overline {
            color: #7892A9; font: 700 9px "JetBrains Mono", ui-monospace, monospace;
            text-transform: uppercase; letter-spacing: 1.45px;
        }
        .nt-card {
            border: 1px solid var(--nt-border); background: rgba(16, 27, 42, .82);
            border-radius: 16px; padding: 17px 18px;
        }
        .nt-empty {
            text-align: center; padding: 44px 22px; margin-top: 8px;
            border-radius: 18px; border: 1px dashed rgba(145,174,199,.25);
            background: rgba(16,27,42,.45);
        }
        .nt-empty-icon { font-size: 28px; margin-bottom: 10px; }
        .nt-empty-title { color: #E7F0F7; font-size: 17px; font-weight: 700; }
        .nt-empty-copy { color: #91A5B8; font-size: 12px; max-width: 500px; margin: 8px auto 0; line-height: 1.65; }
        .nt-footer {
            border-top: 1px solid var(--nt-border); margin-top: 36px; padding-top: 15px;
            display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
            color: #70869B; font: 10px "JetBrains Mono", ui-monospace, monospace;
        }

        [data-testid="stMetric"] {
            background: linear-gradient(145deg, rgba(19,34,51,.96), rgba(14,26,40,.96));
            border: 1px solid var(--nt-border); border-radius: 15px;
            padding: 17px 17px 14px; min-height: 112px;
        }
        [data-testid="stMetricLabel"] p {
            color: #91A8BC !important; font-size: 11px !important;
            letter-spacing: .25px;
        }
        [data-testid="stMetricValue"] {
            color: #EFF6FB !important; font-size: 26px !important;
            font-weight: 740 !important; letter-spacing: -.8px;
        }
        [data-testid="stMetricDelta"] { font-size: 10px !important; }
        [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] { gap: 1rem; }

        [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
        [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            background: #0D1928 !important; border-color: rgba(143,169,193,.22) !important;
            color: #EAF1F8 !important; border-radius: 10px !important;
        }
        [data-testid="stTextInput"] input:focus {
            border-color: rgba(103,221,181,.65) !important;
            box-shadow: 0 0 0 1px rgba(103,221,181,.18) !important;
        }
        [data-testid="stCheckbox"] label, [data-testid="stSlider"] label { color: #C1CFDB !important; }
        [data-testid="stExpander"] {
            border: 1px solid var(--nt-border); border-radius: 12px;
            background: rgba(13,25,40,.55);
        }
        .stButton > button, [data-testid="stFormSubmitButton"] button, .stDownloadButton > button {
            border-radius: 10px !important; min-height: 42px;
            font-weight: 650 !important; transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
        }
        [data-testid="stFormSubmitButton"] button[kind="primary"], .stButton > button[kind="primary"] {
            color: #06150F !important; border: 1px solid #67DDB5 !important;
            background: linear-gradient(135deg, #86EBC8, #53C9A4) !important;
            box-shadow: 0 8px 22px rgba(66,196,149,.13);
        }
        .stButton > button:hover, [data-testid="stFormSubmitButton"] button:hover,
        .stDownloadButton > button:hover { transform: translateY(-1px); border-color: rgba(103,221,181,.65) !important; }
        [data-testid="stTabs"] button[role="tab"] {
            color: #94A9BC; font-size: 12px; font-weight: 650;
            padding: 11px 16px; border-radius: 9px 9px 0 0;
        }
        [data-testid="stTabs"] button[aria-selected="true"] {
            color: #BFF4DD !important; border-bottom-color: #67DDB5 !important;
        }
        [data-testid="stDataFrame"], [data-testid="stPlotlyChart"] {
            border: 1px solid var(--nt-border); border-radius: 14px; overflow: hidden;
            background: rgba(16,27,42,.62);
        }
        [data-testid="stAlert"] { border-radius: 12px; }
        hr { border-color: var(--nt-border) !important; }

        @media (max-width: 760px) {
            .block-container { padding: 1.1rem .85rem 2.5rem; }
            .nt-hero { padding: 22px 19px; border-radius: 17px; }
            .nt-hero-title { font-size: 29px; }
            [data-testid="stMetric"] { padding: 13px; min-height: 100px; }
            [data-testid="stMetricValue"] { font-size: 22px !important; }
            [data-testid="stTabs"] button[role="tab"] { padding: 9px 9px; font-size: 11px; }
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; scroll-behavior: auto !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=60, show_spinner=False)
def get_database_status():
    try:
        return check_connection()
    except Exception as exc:
        return False, str(exc)


inject_newsroom_styles()

# Sidebar: quiet product navigation and system context.
with st.sidebar:
    st.markdown(
        """
        <div class="nt-brand">
          <div class="nt-brand-mark">N</div>
          <div>
            <div class="nt-brand-name">NewsTrace</div>
            <div class="nt-brand-sub">MEDIA INTELLIGENCE</div>
          </div>
        </div>
        <div class="nt-side-label">Workspace</div>
        <div class="nt-side-item active">◈ &nbsp; Investigations</div>
        <div class="nt-side-item">▤ &nbsp; Coverage analysis</div>
        <div class="nt-side-item">◎ &nbsp; Journalist intelligence</div>
        <div class="nt-side-item">⌘ &nbsp; Data exports</div>
        <br/>
        <div class="nt-side-label">Pipeline</div>
        <div class="nt-side-note">01 &nbsp; Discover article URLs<br/>02 &nbsp; Extract metadata<br/>03 &nbsp; Enrich journalist profiles<br/>04 &nbsp; Explore coverage patterns</div>
        <br/>
        <div class="nt-side-label">About this workspace</div>
        <div class="nt-side-note">A research workspace for mapping newsroom coverage, journalist activity and article-level signals.</div>
        """,
        unsafe_allow_html=True,
    )

db_connected, db_message = get_database_status()
db_label = "DATABASE CONNECTED" if db_connected else "LOCAL SESSION"
db_class = "nt-status"

st.markdown(
    f"""
    <div class="nt-hero">
      <div class="nt-kicker">Journalist intelligence / Research workspace</div>
      <div class="nt-hero-title">See the people behind<br/>the coverage.</div>
      <div class="nt-hero-copy">
        Discover articles, identify journalists and map the topics shaping a publication.
        Start with a news outlet or a direct website URL.
      </div>
      <div class="nt-hero-meta">
        <span class="nt-chip">ARTICLE DISCOVERY</span>
        <span class="nt-chip">AUTHOR INTELLIGENCE</span>
        <span class="nt-chip">COVERAGE MAPPING</span>
        <span class="nt-status"><span class="nt-status-dot"></span>{db_label}</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# A clear single-step entry point, with optional controls kept out of the way.
st.markdown(
    """
    <div class="nt-section-head">
      <div class="nt-section-title">Start an investigation</div>
      <div class="nt-section-copy">Enter a publication name or its official website to begin collecting coverage data.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.container(border=True):
    with st.form("newstrace_investigation", clear_on_submit=False):
        outlet = st.text_input(
            "News outlet",
            placeholder="e.g. Reuters, The Guardian or https://www.example.com",
            help="Use a publication name or paste the full website URL.",
        )
        with st.expander("Collection settings", expanded=False):
            setting1, setting2, setting3 = st.columns(3)
            with setting1:
                max_articles = st.slider("Maximum articles", 50, 1000, 300, 50)
            with setting2:
                enable_profiles = st.checkbox(
                    "Author profile enrichment",
                    value=False,
                    help="Visit journalist profile pages for role, biography and social links.",
                )
            with setting3:
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
        df_result, stats_result = run_unified_pipeline(outlet, max_articles, enable_profiles, enable_google)

        if df_result is not None and not df_result.empty:
            st.session_state["df"] = df_result
            st.session_state["outlet"] = outlet.strip()
            st.session_state["stats"] = stats_result or {}

            extraction_report = (stats_result or {}).get("extraction_diagnostics", {})
            if extraction_report.get("failed"):
                reasons = extraction_report.get("failure_reasons", {})
                reason_text = ", ".join(
                    f"{reason}: {count}"
                    for reason, count in sorted(reasons.items(), key=lambda item: item[1], reverse=True)[:4]
                )
                st.warning(
                    f"{extraction_report['failed']} of {extraction_report.get('processed', 0)} "
                    f"article pages could not be parsed. "
                    + (f"Most common causes: {reason_text}." if reason_text else "")
                )
                with st.expander("View extraction diagnostics"):
                    for sample in extraction_report.get("failure_samples", []):
                        st.markdown(
                            f"- **{sample.get('host', 'Unknown host')}** — "
                            f"{sample.get('reason', 'unknown')}: "
                            f"{sample.get('detail') or 'No additional details'} "
                            f"(browser HTTP: {sample.get('browser_http_status')}, "
                            f"HTTP fallback: {sample.get('requests_http_status')})"
                        )

            # Persistence is optional; analysis remains available when no DB is configured.
            if db_connected:
                with st.spinner("Saving this investigation…"):
                    articles_result = save_articles(df_result, outlet)
                    profiles_result = save_journalist_profiles(df_result, outlet)
                if articles_result.get("success") or profiles_result.get("success"):
                    st.success(
                        f"Saved {articles_result.get('count', 0)} articles and "
                        f"{profiles_result.get('count', 0)} journalist profiles."
                    )
                else:
                    st.warning("The analysis completed, but database storage was unavailable.")
            else:
                st.caption("Investigation is available in this session. Configure Supabase to enable persistent storage.")
        else:
            if not st.session_state.get("_pipeline_error_displayed", False):
                st.warning(
                    "No articles were returned. Try a direct section URL or a different publication."
                )

# Render results in focused workspaces rather than one very long page.
if "df" in st.session_state and st.session_state["df"] is not None:
    df = st.session_state["df"].copy()
    stats = st.session_state.get("stats", {})
    outlet_label = st.session_state.get("outlet", "Current investigation")
    safe_outlet_label = escape(str(outlet_label))
    safe_file_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", str(outlet_label)).strip("_") or "newstrace"
    if "author" not in df.columns:
        df["author"] = "Unknown"
    df["author"] = df["author"].fillna("Unknown")
    author_count = df.loc[df["author"] != "Unknown", "author"].nunique()
    article_count = len(df)
    unknown_count = int((df["author"] == "Unknown").sum())
    unknown_pct = (unknown_count / article_count * 100) if article_count else 0
    social_count = sum(
        int(df[col].notna().sum()) for col in ["twitter", "linkedin", "instagram", "facebook"] if col in df.columns
    )
    email_count = int(df["author_email"].notna().sum()) if "author_email" in df.columns else 0

    st.markdown(
        f"""
        <div class="nt-section-head">
          <div class="nt-overline">Current investigation</div>
          <div class="nt-section-title">{safe_outlet_label}</div>
          <div class="nt-section-copy">Collected records are grouped into overview, coverage, journalist and dataset views.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    overview_tab, coverage_tab, journalists_tab, dataset_tab = st.tabs(
        ["Overview", "Coverage", "Journalists", "Dataset"]
    )

    with overview_tab:
        st.markdown('<div class="nt-overline">At a glance</div>', unsafe_allow_html=True)
        metric_cols = st.columns(4)
        metric_cols[0].metric("Identified journalists", f"{author_count:,}")
        metric_cols[1].metric("Articles collected", f"{article_count:,}")
        metric_cols[2].metric("Public profile links", f"{social_count:,}")
        metric_cols[3].metric("Unidentified authors", f"{unknown_pct:.1f}%")

        st.markdown(
            """
            <div class="nt-section-head">
              <div class="nt-section-title">Collection summary</div>
              <div class="nt-section-copy">A quick readout of what the pipeline found in this run.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        summary_left, summary_right = st.columns([1.2, 1])
        with summary_left:
            with st.container(border=True):
                st.markdown("**Pipeline stages**")
                stage_names = [
                    ("Article URLs discovered", stats.get("urls_found", 0)),
                    ("Articles successfully parsed", stats.get("articles_scraped", article_count)),
                    ("Journalist profiles enriched", stats.get("profiles_found", 0)),
                    ("Search-enriched profiles", stats.get("google_enriched", 0)),
                ]
                for stage_name, stage_value in stage_names:
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;gap:14px;padding:9px 0;border-bottom:1px solid rgba(157,180,205,.10);">'
                        f'<span style="color:#9DB0C2;font-size:12px;">{stage_name}</span>'
                        f'<strong style="color:#EAF1F8;font-size:13px;font-variant-numeric:tabular-nums;">{stage_value:,}</strong></div>',
                        unsafe_allow_html=True,
                    )
        with summary_right:
            with st.container(border=True):
                st.markdown("**Data quality signal**")
                known_pct = 100 - unknown_pct
                st.markdown(
                    f'<div style="font-size:30px;font-weight:760;color:#A8EBD2;margin:12px 0 4px;">{known_pct:.1f}%</div>'
                    '<div style="font-size:11px;color:#93A6BA;">of collected articles have an identified author</div>',
                    unsafe_allow_html=True,
                )
                st.progress(max(0.0, min(1.0, known_pct / 100)))
                st.caption(f"{unknown_count:,} article(s) currently have an unknown author.")

        st.markdown(
            """
            <div class="nt-section-head">
              <div class="nt-section-title">What to explore next</div>
              <div class="nt-section-copy">Move from the collection summary into the evidence behind it.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        next_cols = st.columns(3)
        next_items = [
            ("01", "Coverage", "Compare the most active authors and the sections they cover."),
            ("02", "Journalists", "Review identified reporters and any extracted public profile details."),
            ("03", "Dataset", "Search, filter and export the article-level records."),
        ]
        for col, item in zip(next_cols, next_items):
            with col:
                st.markdown(
                    f'<div class="nt-card"><div class="nt-overline">{item[0]}</div>'
                    f'<div style="color:#EAF1F8;font-size:14px;font-weight:700;margin:8px 0 5px;">{item[1]}</div>'
                    f'<div style="color:#93A6BA;font-size:11px;line-height:1.6;">{item[2]}</div></div>',
                    unsafe_allow_html=True,
                )

    with coverage_tab:
        st.markdown(
            """
            <div class="nt-section-head">
              <div class="nt-section-title">Coverage intelligence</div>
              <div class="nt-section-copy">Understand who is publishing and how journalist activity maps to coverage sections.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        chart_col, network_col = st.columns([1, 1.15])
        with chart_col:
            st.markdown("**Most active journalists**")
            chart = create_chart(df)
            if chart:
                chart.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#DCE7F2", family="Inter, sans-serif"),
                    title=None, height=430,
                )
                st.plotly_chart(chart, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Author activity will appear after journalists have been identified.")
        with network_col:
            st.markdown("**Author–section relationships**")
            network = create_author_section_network(df)
            if network:
                network.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#DCE7F2", family="Inter, sans-serif"),
                )
                st.plotly_chart(network, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("The network needs multiple identified authors and coverage sections.")

        if "section" in df.columns:
            st.markdown("**Section distribution**")
            section_counts = (
                df["section"].fillna("Unclassified").replace("", "Unclassified")
                .value_counts().head(12).rename_axis("Section").reset_index(name="Articles")
            )
            st.dataframe(section_counts, use_container_width=True, hide_index=True)

    with journalists_tab:
        st.markdown(
            """
            <div class="nt-section-head">
              <div class="nt-section-title">Journalist intelligence</div>
              <div class="nt-section-copy">Consolidated author records with the profile attributes available from the source pages.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if author_count:
            display_journalist_profiles(df)
        else:
            st.markdown(
                '<div class="nt-empty"><div class="nt-empty-icon">◎</div>'
                '<div class="nt-empty-title">No journalist profiles identified yet</div>'
                '<div class="nt-empty-copy">The article records were collected, but the source pages did not expose usable author names. Try another outlet or enable author profile enrichment.</div></div>',
                unsafe_allow_html=True,
            )

    with dataset_tab:
        st.markdown(
            """
            <div class="nt-section-head">
              <div class="nt-section-title">Article dataset</div>
              <div class="nt-section-copy">Search the collected records, narrow by section, then export the current investigation.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        filter_col, section_col = st.columns([1.6, 1])
        with filter_col:
            record_query = st.text_input("Search records", placeholder="Search author, headline, URL or date…", key="dataset_search")
        with section_col:
            if "section" in df.columns:
                section_options = sorted(
                    set(df["section"].fillna("Unclassified").replace("", "Unclassified").astype(str).tolist())
                )
                chosen_section = st.selectbox("Coverage section", ["All sections"] + section_options, key="dataset_section")
            else:
                chosen_section = "All sections"

        filtered_df = df.copy()
        if chosen_section != "All sections" and "section" in filtered_df.columns:
            section_values = filtered_df["section"].fillna("Unclassified").replace("", "Unclassified").astype(str)
            filtered_df = filtered_df.loc[section_values == chosen_section]
        if record_query.strip():
            mask = filtered_df.astype(str).apply(
                lambda column: column.str.contains(record_query.strip(), case=False, na=False, regex=False)
            ).any(axis=1)
            filtered_df = filtered_df.loc[mask]

        st.caption(f"Showing {len(filtered_df):,} of {len(df):,} article records")
        preferred_cols = [
            "author", "title", "section", "date", "url",
            "author_role", "author_email", "twitter", "linkedin",
        ]
        display_cols = [col for col in preferred_cols if col in filtered_df.columns]
        column_config = {}
        if "url" in display_cols:
            column_config["url"] = st.column_config.LinkColumn("Article", display_text="Open source")
        if "author_email" in display_cols:
            column_config["author_email"] = st.column_config.TextColumn("Email")
        if display_cols:
            st.dataframe(
                filtered_df[display_cols],
                use_container_width=True,
                height=520,
                hide_index=True,
                column_config=column_config,
            )
        else:
            st.dataframe(filtered_df, use_container_width=True, height=520, hide_index=True)

        export_left, export_csv, export_json = st.columns([2, 1, 1])
        with export_left:
            st.caption("Exports include the filtered records currently shown above.")
        with export_csv:
            st.download_button(
                "↓  Export CSV",
                filtered_df.to_csv(index=False).encode("utf-8"),
                f"{safe_file_stem}_newstrace.csv",
                "text/csv",
                use_container_width=True,
            )
        with export_json:
            st.download_button(
                "↓  Export JSON",
                filtered_df.to_json(orient="records", indent=2).encode("utf-8"),
                f"{safe_file_stem}_newstrace.json",
                "application/json",
                use_container_width=True,
            )

else:
    st.markdown(
        """
        <div class="nt-empty">
          <div class="nt-empty-icon">⌕</div>
          <div class="nt-empty-title">Your next investigation starts here</div>
          <div class="nt-empty-copy">
            Enter a publication above to collect its articles and surface journalist activity.
            Your results will appear in a focused workspace with coverage charts, journalist profiles and searchable exports.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <div class="nt-footer">
      <span>NEWSTRACE · JOURNALIST INTELLIGENCE</span>
      <span>Research with context. Data with provenance.</span>
    </div>
    """,
    unsafe_allow_html=True,
)
