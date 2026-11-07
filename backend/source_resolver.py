"""Source resolution shared by the web API and legacy Streamlit application."""

import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

from utils.url_safety import safe_get


def _report(progress_callback, detail: str) -> None:
    if progress_callback:
        try:
            progress_callback(detail)
        except Exception:
            # Status telemetry must never break source resolution.
            pass


def resolve_outlet(
    user_input: str,
    progress_callback=None,
    timeout_seconds: float = 12.0,
):
    """Resolve a publication name or URL into a base URL and display label.

    Direct URLs are returned without a network lookup. Name searches use one
    public web search and at most three short domain probes, all within a
    shared elapsed-time budget. Returns (base_url, label) or (None, None).
    """
    if not user_input:
        return None, None

    s = user_input.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"
    }

    # Accept full URLs and domain/path input without a scheme. The caller
    # validates DNS and preserves a direct section path for discovery.
    try:
        candidate = s if s.startswith(("http://", "https://")) else f"https://{s}"
        p = urlparse(candidate)
        if p.netloc and "." in (p.hostname or "") and not any(ch.isspace() for ch in s):
            base = f"{p.scheme}://{p.netloc}"
            _report(progress_callback, "Direct publication URL recognized; skipping name lookup.")
            return base, p.netloc
    except Exception:
        pass

    timeout_seconds = max(1.0, min(float(timeout_seconds), 15.0))
    deadline = time.monotonic() + timeout_seconds
    _report(progress_callback, "Searching for the publication's official website.")

    # Search once. Each connection/read timeout is derived from the remaining
    # total budget, and safe_get validates every redirect before fetching it.
    try:
        from urllib.parse import quote_plus
        remaining = deadline - time.monotonic()
        if remaining > 0:
            q = quote_plus(f"{s} official site news")
            response = safe_get(
                f"https://duckduckgo.com/html/?q={q}",
                headers=headers,
                timeout=(min(1.5, remaining), min(2.0, remaining)),
                max_redirects=3,
            )
            if response.ok:
                soup = BeautifulSoup(response.text, "html.parser")
                candidates = []
                for a in soup.select("a.result__a, a[href]"):
                    href = a.get("href")
                    if not href:
                        continue
                    if "duckduckgo.com/l/?uddg=" in href:
                        try:
                            parsed_link = urlparse(href)
                            query_values = parse_qs(parsed_link.query)
                            redirect = query_values.get("uddg", [None])[0]
                            if redirect:
                                href = redirect
                        except Exception:
                            continue
                    if href.startswith(("http://", "https://")):
                        candidates.append(href)

                skip_hosts = (
                    "wikipedia.org", "twitter.com", "x.com",
                    "facebook.com", "linkedin.com", "youtube.com",
                )
                for result_url in candidates:
                    try:
                        result = urlparse(result_url)
                        host = (result.hostname or "").lower()
                        if not host or any(host == item or host.endswith("." + item) for item in skip_hosts):
                            continue
                        base = f"{result.scheme}://{result.netloc}"
                        _report(progress_callback, "Found an official-site candidate; validating the source.")
                        return base, host
                    except Exception:
                        continue
            _report(progress_callback, "The web search returned no suitable publication; checking a few common domains.")
    except Exception as exc:
        _report(
            progress_callback,
            f"Official-site search did not resolve the name ({type(exc).__name__}); checking a few common domains.",
        )

    # Retain a short compatibility fallback, but cap it to three candidates.
    slug = re.sub(r"[^a-z0-9]+", "", s.lower())
    if not slug:
        return None, None

    for index, tld in enumerate((".com", ".org", ".in"), start=1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _report(progress_callback, "Source lookup reached its time limit.")
            break

        _report(progress_callback, f"Checking publication domain candidate {index}/3.")
        test = f"https://{slug}{tld}"
        try:
            response = safe_get(
                test,
                headers=headers,
                timeout=(min(1.2, remaining), min(1.5, remaining)),
                max_redirects=2,
            )
            if response.status_code < 400:
                final = urlparse(response.url)
                if final.hostname:
                    base = f"{final.scheme}://{final.netloc}"
                    _report(progress_callback, "Publication domain candidate validated.")
                    return base, final.netloc
        except Exception:
            continue

    _report(progress_callback, "Could not identify a public website for that publication name.")
    return None, None
