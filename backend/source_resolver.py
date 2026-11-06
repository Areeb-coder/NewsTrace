"""Source resolution shared by the web API and legacy Streamlit application."""

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs


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
