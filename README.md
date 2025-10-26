# 🔍 NewsTrace - Journalist Intelligence System

**Fast, intelligent web scraping to discover journalists and their coverage patterns**

---

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run the dashboard
streamlit run dashboard.py
```

**Dashboard:** http://localhost:8501

---

## ✨ Features
# 🔍 NewsTrace — Minimal README

Fast web scraping to discover journalists and their coverage, in one simple dashboard.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run the app
streamlit run dashboard.py
```

Dashboard: http://localhost:8501

## How it works
- Enter any news outlet name or paste a website URL. No predefined URL list is used.
- The app resolves the official site, collects article links, and scrapes in parallel.
- Optional: enrich authors via profile pages and Google (social/contact). 
- Export full results as CSV/JSON.

## Key features
- Parallel article scraping (fast)
- Author extraction (name, role, email when found)
- Optional Google enrichment (social, bio)
- Top authors chart and author–section network
- Clickable article links in the table

## Options (in app)
- Author Profiles: on/off
- Google Enrichment: on/off (requires SERP_API_KEY if used)
- Max Articles: 50–1000

Set SERP_API_KEY (optional):

```bash
export SERP_API_KEY=your_key
```

## Troubleshooting
- Couldn’t resolve outlet: try full outlet name or paste the site URL.
- No articles found: increase Max Articles or try another outlet.
- Slow: reduce Max Articles; ensure stable internet.

## Notes
- Public websites only; be respectful of sites’ policies.
- Landing page removed; the dashboard opens directly.
- URLs in the table are clickable.

—

Built with Streamlit, Playwright, BeautifulSoup, and Pandas.
---


