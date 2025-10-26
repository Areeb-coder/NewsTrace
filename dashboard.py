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
from utils.article_collector import collect_article_urls
from scrapers.parallel_scraper import scrape_articles_parallel
from scrapers.author_profiles import get_author_profile_page, scrape_author_details
from utils.google_enrichment import enrich_journalists_batch
from utils.supabase_backend import save_articles, save_journalist_profiles, check_connection
import os
import time

# Page Config
st.set_page_config(page_title="NewsTrace", page_icon="🔍", layout="wide", initial_sidebar_state="collapsed")

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

    # If already a URL
    try:
        if s.startswith("http://") or s.startswith("https://"):
            p = urlparse(s)
            if p.netloc:
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


async def unified_scraping_pipeline(url, outlet_name, max_articles, enable_profiles=False, enable_google=False):
    """
    UNIFIED PIPELINE - One function for all modes
    - Basic mode: Just article scraping
    - Profile mode: + Author profile enrichment
    - Full mode: + Google enrichment
    """
    results = {'articles': [], 'profiles': {}, 'stats': {}}
    progress = st.progress(0)
    step_count = 3 + int(enable_profiles) + int(enable_google)  # Total steps based on enabled features
    step = 0

    # STEP 1: Collect Article URLs (shared by all modes)
    start_time = time.time()
    urls = await collect_article_urls(url, max_articles)
    if not urls:
        return None
    step += 1
    progress.progress(step / step_count)
    elapsed = time.time() - start_time
    st.info(f"Step {step}/{step_count}: Collected {len(urls)} article URLs in {elapsed:.2f} seconds.")

    results['stats']['urls_found'] = len(urls)

    # STEP 2: Scrape Articles in Parallel (shared by all modes)
    start_time = time.time()
    articles_data = await scrape_articles_parallel(urls, max_workers=10, target_authors=200)
    if not articles_data:
        return None
    step += 1
    progress.progress(step / step_count)
    elapsed = time.time() - start_time
    st.info(f"Step {step}/{step_count}: Scraped {len(articles_data)} articles in {elapsed:.2f} seconds.")

    results['articles'] = articles_data
    results['stats']['articles_scraped'] = len(articles_data)

    # Get unique authors
    unique_authors = list(set(a['author'] for a in articles_data if a.get('author') != 'Unknown'))
    results['stats']['unique_authors'] = len(unique_authors)

    # STEP 3: Profile Enrichment (optional - only if enabled)
    if enable_profiles and unique_authors:
        start_time = time.time()
        profiles = {}

        # Scrape author profile pages (5 concurrent)
        semaphore = asyncio.Semaphore(5)

        async def get_profile(author):
            async with semaphore:
                profile_url = await get_author_profile_page(author, url)
                if profile_url:
                    details = await scrape_author_details(profile_url)
                    if details:
                        details['profile_url'] = profile_url
                        return author, details
                return author, None

        tasks = [get_profile(a) for a in unique_authors[:50]]
        profile_results = await asyncio.gather(*tasks)

        for author, details in profile_results:
            if details:
                profiles[author] = details

        results['profiles'] = profiles
        results['stats']['profiles_found'] = len(profiles)
        step += 1
        progress.progress(step / step_count)
        elapsed = time.time() - start_time
        st.info(f"Step {step}/{step_count}: Enriched {len(profiles)} author profiles in {elapsed:.2f} seconds.")

    # STEP 4: Google Enrichment (optional - only if enabled)
    if enable_google and unique_authors:
        start_time = time.time()
        google_profiles = enrich_journalists_batch(unique_authors[:30], news_outlet=outlet_name, delay=1.0)

        # Merge Google data into profiles
        if not results['profiles']:
            results['profiles'] = {}

        for gprofile in google_profiles:
            author = gprofile['name']
            if author not in results['profiles']:
                results['profiles'][author] = {}

            # Merge social media
            for field in ['twitter', 'linkedin', 'instagram', 'email', 'workplace', 'bio']:
                if gprofile.get(field):
                    results['profiles'][author][field] = gprofile[field]

        results['stats']['google_enriched'] = len(google_profiles)
        step += 1
        progress.progress(step / step_count)
        elapsed = time.time() - start_time
        st.info(f"Step {step}/{step_count}: Enriched {len(google_profiles)} profiles with Google data in {elapsed:.2f} seconds.")

    # STEP 5: Build final DataFrame directly and merge profile fields
    articles_df = pd.DataFrame(results['articles']) if results['articles'] else pd.DataFrame()
    if articles_df.empty:
        return None

    if 'author' not in articles_df.columns:
        articles_df['author'] = 'Unknown'

    # Merge profile fields from results['profiles']
    profiles_map = results.get('profiles') or {}
    if profiles_map:
        # Collect all possible keys from profiles
        all_keys = set()
        for _, p in profiles_map.items():
            if isinstance(p, dict):
                all_keys.update(p.keys())
        # For each key, map values by author
        for key in sorted(all_keys):
            if key == 'name':
                continue
            if key not in articles_df.columns:
                articles_df[key] = articles_df['author'].map(
                    lambda a: profiles_map.get(a, {}).get(key) if isinstance(profiles_map.get(a, {}), dict) else None
                )

    progress.progress(1.0)  # Complete progress bar
    st.success("✅ Scraping pipeline completed successfully!")

    return articles_df, results['stats']


def run_unified_pipeline(user_query, max_articles, enable_profiles, enable_google):
    """Wrapper to run async pipeline in Streamlit"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Resolve website live (no predefined mapping)
    with st.spinner("🔍 Resolving outlet website..."):
        url, outlet_label = resolve_outlet(user_query)
        if not url:
            st.error("❌ Could not resolve this outlet. Try a full name or paste the website URL directly.")
            return None, None
        st.success(f"✓ Found: {url}")
    
    # Build progress message
    steps = ["Article collection", "Parallel scraping"]
    if enable_profiles:
        steps.append("Author profiles")
    if enable_google:
        steps.append("Google enrichment")
    
    msg = f"⚡ Running: {' → '.join(steps)}..."
    
    # Run pipeline
    with st.spinner(msg):
        result = loop.run_until_complete(
            unified_scraping_pipeline(url, outlet_label or user_query, max_articles, enable_profiles, enable_google)
        )
        
        if result:
            df, stats = result
            return df, stats
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
        marker=dict(color='#1f77b4'),
        hovertemplate='%{y}: %{x} articles<extra></extra>'
    )])
    
    fig.update_layout(
        title='Top 10 Authors by Article Count',
        xaxis=dict(title='Articles', tickmode='linear', dtick=1),
        yaxis=dict(title='', autorange='reversed'),
        height=400,
        showlegend=False,
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
        line=dict(width=2, color='rgba(30,58,138,0.6)'),  # Increased width and opacity
        hoverinfo='none', mode='lines'
    )

    # Section nodes
    sx, sy, stext = [], [], []
    for s in sections:
        x, y = section_pos[s]
        sx.append(x); sy.append(y); stext.append(f"Section: {s}")

    section_trace = go.Scatter(
        x=sx, y=sy, mode='markers+text',
        marker=dict(size=18, color='rgba(99,102,241,0.9)', line=dict(color='white', width=1)),
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
        marker=dict(size=asize, color='rgba(16,185,129,0.9)', line=dict(color='white', width=1)),
        hovertext=atext, hoverinfo='text',
        name='Authors'
    )

    fig = go.Figure(data=[edge_trace, section_trace, author_trace])
    fig.update_layout(
        title='Author–Section Network (node size = article count)',
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        showlegend=False, height=520, margin=dict(l=20, r=20, t=50, b=20)
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


# ==================== MAIN UI ====================
st.title("🔍 NewsTrace")
st.markdown("**Unified Journalist Intelligence System**")

# Supabase connection status
try:
    connected, msg = check_connection()
    if connected:
        st.success("✅ Database connected")
    else:
        st.info("ℹ️ Database not configured (set SUPABASE_URL and SUPABASE_KEY in .env to enable)")
except:
    pass  # Silently skip if not configured

# Settings in expandable section
with st.expander("⚙️ Configuration", expanded=True):
    col1, col2, col3 = st.columns(3)
    
    with col1:
        enable_profiles = st.checkbox(
                "🎯 Author Profiles",
                value=False,
            help="Scrape author profile pages for detailed info (role, bio, social media)"
        )
    
    with col2:
        enable_google = st.checkbox(
                "🌐 Google Enrichment",
                value=False,
            help="Use Google search to find social media & contact info (slower)"
        )
    
    with col3:
        max_articles = st.slider(
            "Max Articles",
                50,
                1000,
                300,
            50,
            help="Maximum number of articles to scrape"
        )

st.markdown("---")

col1, col2 = st.columns([3, 1])
with col1:
    outlet = st.text_input("🏢 Enter news outlet name or website URL", "",
                           help="Type any outlet (worldwide) or paste its site URL. No predefined URLs are used.")

with col2:
    st.write("")
    st.write("")
    if st.button("🚀 Start Analysis", type="primary", width='stretch'):
        if not outlet.strip():
            st.error("⚠️ Please enter an outlet name or URL")
        else:
            os.makedirs('data', exist_ok=True)
            
            df, stats = run_unified_pipeline(outlet, max_articles, enable_profiles, enable_google)
            
            if df is not None and not df.empty:
                st.session_state['df'] = df
                st.session_state['outlet'] = outlet
                st.session_state['stats'] = stats
                
                # Save to Supabase backend (optional)
                try:
                    with st.spinner("💾 Saving to database..."):
                        articles_result = save_articles(df, outlet)
                        profiles_result = save_journalist_profiles(df, outlet)
                        
                        if articles_result['success'] or profiles_result['success']:
                            st.success(f"✅ Saved to database: {articles_result['count']} articles, {profiles_result['count']} profiles")
                        else:
                            st.info("ℹ️ Database save skipped (configure Supabase in .env to enable)")
                except Exception as e:
                    # Silently continue if Supabase not configured
                    pass
                
                st.rerun()
            else:
                st.warning("No articles were found or parsed. Try increasing Max Articles, enabling Google enrichment, or selecting a different outlet.")

# Display Results
if 'df' in st.session_state and st.session_state['df'] is not None:
    df = st.session_state['df']
    stats = st.session_state.get('stats', {})
    
    st.markdown("---")
    st.markdown("## 📊 Results")
    
    # Metrics Row
    col1, col2, col3, col4, col5 = st.columns(5)
    
    authors = len(df[df['author'] != 'Unknown']['author'].unique()) if 'author' in df.columns else 0
    articles = len(df)
    unknown_pct = (len(df[df['author'] == 'Unknown']) / articles * 100) if articles > 0 and 'author' in df.columns else 0
    
    # Count social media
    social_count = 0
    for col_name in ['twitter', 'linkedin', 'instagram', 'facebook']:
        if col_name in df.columns:
            social_count += df[col_name].notna().sum()
    
    # Count emails
    email_count = df['author_email'].notna().sum() if 'author_email' in df.columns else 0
    
    col1.metric("👥 Authors", authors)
    col2.metric("📰 Articles", articles)
    col3.metric("🔗 Social Links", social_count)
    col4.metric("📧 Emails", email_count)
    col5.metric("❓ Unknown", f"{unknown_pct:.1f}%")
    
    # Stats summary
    if stats:
        st.markdown("---")
        st.markdown("### 📈 Pipeline Stats")
        stat_cols = st.columns(4)
        
        if 'urls_found' in stats:
            stat_cols[0].metric("URLs Collected", stats['urls_found'])
        if 'articles_scraped' in stats:
            stat_cols[1].metric("Articles Scraped", stats['articles_scraped'])
        if 'profiles_found' in stats:
            stat_cols[2].metric("Profiles Enriched", stats['profiles_found'])
        if 'google_enriched' in stats:
            stat_cols[3].metric("Google Enriched", stats['google_enriched'])
    
    # Chart
    st.markdown("---")
    chart = create_chart(df)
    if chart:
        st.plotly_chart(chart, width='stretch')
    else:
        st.info("Not enough author data to plot the Top Authors chart.")

    # Author Network
    st.markdown("---")
    st.markdown("### 🕸️ Author Network")
    net = create_author_section_network(df)
    if net:
        st.plotly_chart(net, width='stretch')
    else:
        st.info("Network will appear once we have identified multiple authors and sections.")
    
    # Top Journalists
    if authors > 0:
        st.markdown("---")
        st.markdown("### 👤 Top Journalists")
        display_journalist_profiles(df)
    
    # Full Data Table
    st.markdown("---")
    st.markdown("### 📋 Complete Dataset")
    
    # Select columns to display
    available_cols = list(df.columns)
    default_cols = ['author', 'title', 'section', 'date', 'url']
    display_cols = [col for col in default_cols if col in available_cols]
    
    # Add enhanced columns if they exist
    for col in ['author_role', 'author_email', 'twitter', 'linkedin']:
        if col in available_cols:
            display_cols.append(col)
    
    # Make URL clickable if present
    column_config = {}
    if 'url' in display_cols:
        column_config['url'] = st.column_config.LinkColumn("URL", display_text="Open Article")
    if display_cols:
        st.dataframe(df[display_cols], width='stretch', height=400, hide_index=True, column_config=column_config)
    else:
        st.dataframe(df, width='stretch', height=400, hide_index=True)
    
    # Download Section
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.markdown("💡 **Tip**: All data includes enhanced fields (roles, emails, social media)")
    
    with col2:
        csv = df.to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            csv,
            f"{st.session_state.get('outlet', 'newstrace')}_complete.csv",
            "text/csv",
            use_container_width=True
        )
    
    with col3:
        json_data = df.to_json(orient='records', indent=2)
        st.download_button(
            "📥 Download JSON",
            json_data,
            f"{st.session_state.get('outlet', 'newstrace')}_complete.json",
            "application/json",
            use_container_width=True
        )

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <strong>NewsTrace</strong> • Unified Journalist Intelligence Platform<br>
    <small>Single pipeline • Maximum efficiency • Enhanced data extraction</small>
</div>
""", unsafe_allow_html=True)


