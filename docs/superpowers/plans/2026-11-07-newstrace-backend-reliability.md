# NewsTrace Backend Reliability Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NewsTrace source resolution, network navigation and article extraction bounded and visibly progressive while preserving the current FastAPI/Next.js API contract.

**Architecture:** Keep the current one-process FastAPI job runner, SQLite/Supabase store, API-first discovery, bounded Playwright crawler and Next.js desks. Add a shared outbound URL safety layer for HTTP redirects and browser requests, bound publication-name resolution, and emit progress when article pages begin as well as when they finish.

**Tech Stack:** Python 3.12, FastAPI, Requests, asyncio, Playwright, unittest, GitHub Actions; existing Next.js static export.

**Spec:** `docs/superpowers/specs/2026-11-07-newstrace-backend-reliability-design.md`

## Global Constraints

- Preserve the existing discovery API routes and JSON response fields.
- Preserve the four existing frontend desks and visual design.
- Keep the current single FastAPI worker/service-instance model.
- Keep Supabase as production persistence and SQLite as local/test persistence.
- Do not add queue infrastructure or new product features.
- Do not bypass publisher access challenges, paywalls or CAPTCHAs.
- Do not claim tests/builds passed unless the relevant command or GitHub Actions run confirms it.

## Review Focus

- A hostname resolving to a private, loopback, link-local or reserved IP must be rejected before outbound HTTP/browser access; test a mixed public/private DNS answer.
- HTTP 3xx responses must not be followed before validating the redirect target; test private-target and excessive redirect chains.
- Browser navigations and subresource requests must pass through the public-network guard; test a private navigation URL is aborted.
- A publisher name lookup must stop after a bounded number of short requests and expose meaningful source-resolution progress; test no-result and timeout paths.
- A slow article must expose an in-flight fetch update before the scrape completes, and its failure must not erase other article results; test the progress callback ordering and existing partial-result contract.

---

### Task 1: Shared public URL validation and safe HTTP redirects

**Files:**
- Create: `utils/url_safety.py`
- Create: `tests/test_url_safety.py`
- Modify: `tests/test_api_security.py`

**Interfaces:**
- Produces `validate_public_http_url(value: str, *, resolve_dns: bool = True) -> str`.
- Produces `safe_get(url: str, *, session=None, max_redirects: int = 5, **request_kwargs)` returning a Requests `Response`.
- Produces `install_public_network_guard(context) -> None`, an async helper that routes all browser HTTP(S) requests through the validator and aborts unsafe destinations.
- Only HTTP and HTTPS are permitted; credentials and non-standard ports are rejected; every DNS answer must be globally routable.

- [ ] **Step 1: Write failing validation tests** in `tests/test_url_safety.py`: accept a hostname whose mocked DNS answer is a public IP; reject localhost, private/link-local/reserved IP literals, credentials, non-standard ports, and a hostname whose mocked answers include any private address.
- [ ] **Step 2: Run the focused test before implementation.** Run: `python -m unittest tests.test_url_safety -v`. Expected: FAIL because `utils.url_safety` does not exist.
- [ ] **Step 3: Implement `validate_public_http_url`** in `utils/url_safety.py` using `urllib.parse`, `ipaddress` and `socket.getaddrinfo`. Reject the URL if any returned A/AAAA address is not `is_global`; preserve the original URL string when valid. Provide `resolve_dns=False` only for the existing fast syntax-only API submission check.
- [ ] **Step 4: Add redirect tests**: verify `safe_get` follows a public redirect by validating each hop, refuses a redirect to `127.0.0.1`, and raises after more than five redirects.
- [ ] **Step 5: Implement `safe_get`** with redirects disabled on each underlying request, relative `Location` resolution, URL validation before every hop, a fixed maximum redirect count, and response cleanup for intermediate redirects.
- [ ] **Step 6: Add a browser-route test** with a fake Playwright context/route proving a private URL is aborted and a public URL is continued; implement `install_public_network_guard` without blocking `data:`, `blob:` or `about:` browser-local resources.
- [ ] **Step 7: Run focused tests.** Run: `python -m unittest tests.test_url_safety -v`. Expected: all URL, DNS, redirect and browser-route tests PASS.
- [ ] **Step 8: Run existing security tests.** Run: `python -m unittest tests.test_api_security -v`. Expected: existing API URL/rate-limit tests remain PASS.
- [ ] **Step 9: Commit** `test: cover public URL and redirect safety` followed by `fix: validate outbound URLs and redirect targets`.

### Task 2: Apply the network guard to discovery and extraction

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/source_resolver.py`
- Modify: `scrapers/api_scraper.py`
- Modify: `utils/article_collector.py`
- Modify: `scrapers/article_scraper.py`
- Modify: `scrapers/parallel_scraper.py`
- Test: `tests/test_url_safety.py`, `tests/test_discovery.py`

**Interfaces:**
- Consume the `utils.url_safety` APIs from Task 1.
- Keep `backend.main._validate_public_http_url(value)` as a compatibility wrapper with syntax-only DNS behavior for the request handler; perform DNS-aware validation off the event loop before actual outbound requests and in every network hop.
- Keep all current crawler and scraper function signatures compatible.

- [ ] **Step 1: Add tests** that verify requests-based discovery helpers use safe redirect handling and browser contexts install the network route guard.
- [ ] **Step 2: Run focused tests and confirm the new integration assertions fail** before changing production imports/calls.
- [ ] **Step 3: Replace direct `requests.get` calls** in the source resolver, API endpoint probe, listing-page fallback and article-page fallback with `safe_get`. Preserve existing headers, query parameters, timeouts and response handling.
- [ ] **Step 4: Install the browser guard** on each Playwright context in `utils/article_collector.py`, `scrapers/parallel_scraper.py` and the standalone context in `scrapers/article_scraper.py`. This must cover redirects and page subresources as well as top-level navigation.
- [ ] **Step 5: Make `backend.main._validate_public_http_url` delegate to the shared syntax validator** so current API error messages/tests remain compatible; call DNS-aware validation in the worker before the source is passed to investigation.
- [ ] **Step 6: Run** `python -m unittest tests.test_url_safety tests.test_api_security tests.test_discovery -v`. Expected: all focused tests PASS.
- [ ] **Step 7: Commit** `fix: apply outbound URL guard to discovery and browser extraction`.

### Task 3: Bound source resolution and report its progress

**Files:**
- Modify: `backend/source_resolver.py`
- Modify: `backend/main.py`
- Create or modify: `tests/test_source_resolver.py`
- Modify: `tests/test_api_jobs.py`

**Interfaces:**
- Extend `resolve_outlet(user_input: str, progress_callback=None, timeout_seconds: float = 12.0)` while preserving its `(base_url, label)` return value and existing first-argument callers.
- The callback receives one human-readable detail string.
- Source resolution is bounded to one search request and no more than three short TLD fallback probes within the remaining time budget. Do not follow an unchecked redirect while probing a guessed domain.

- [ ] **Step 1: Write tests** for direct URLs making no network call, publication-name lookup reporting a start/update, bounded fallback attempts, and failed lookup returning `(None, None)`.
- [ ] **Step 2: Run** `python -m unittest tests.test_source_resolver -v`. Expected: FAIL on missing progress/budget behavior.
- [ ] **Step 3: Implement the deadline and progress callback** in `resolve_outlet`; use short connect/read timeouts derived from remaining time, cap fallback probes at three, set `allow_redirects=False` via `safe_get`, and report the candidate count without exposing full URLs containing query strings.
- [ ] **Step 4: Move the job's progress writer initialization before source resolution** or persist source-resolution callback events serially from its worker thread; do not block the asyncio event loop or reorder progress events.
- [ ] **Step 5: Add an API lifecycle test** where resolution fails and the job becomes terminal `failed` with an actionable error rather than remaining `running`.
- [ ] **Step 6: Run** `python -m unittest tests.test_source_resolver tests.test_api_jobs tests.test_jobs -v`. Expected: all resolver and job lifecycle tests PASS.
- [ ] **Step 7: Commit** `fix: bound publication source resolution and report progress`.

### Task 4: Emit in-flight article extraction progress

**Files:**
- Modify: `scrapers/parallel_scraper.py`
- Test: `tests/test_parallel_scraper.py`

**Interfaces:**
- Preserve `scrape_articles_parallel(article_urls, max_workers=6, target_authors=200, progress_callback=None, diagnostics_out=None)`.
- Continue reporting processed/succeeded/failed counts after each completed URL.
- Add a progress event before each worker starts a page request; its detail must identify the number of the article being fetched and the configured active worker count, while `current` continues to count completed URLs.

- [ ] **Step 1: Write a fake-Playwright test** proving an “Fetching article …” progress event is emitted before a deliberately delayed page scrape returns.
- [ ] **Step 2: Run** `python -m unittest tests.test_parallel_scraper -v`. Expected: FAIL because no in-flight event is emitted today.
- [ ] **Step 3: Emit the in-flight progress event** immediately after dequeuing a URL and before calling `scrape_journalist_info`. Keep callback delivery bounded by the existing API throttle and never claim the page is complete until the extraction returns.
- [ ] **Step 4: Add a second test** proving a failed article still increments processed/failed counts while successful article data is retained.
- [ ] **Step 5: Run** `python -m unittest tests.test_parallel_scraper -v`. Expected: all progress ordering and partial-retention tests PASS.
- [ ] **Step 6: Commit** `fix: report article fetch activity while extraction is running`.

### Task 5: Full regression and deployment contract

**Files:**
- Modify if required: `README.md`, `DEPLOYMENT.md`
- Verify: `tests/`, `frontend/`, `.github/workflows/deploy-check.yml`, `Dockerfile.web`, `render.yaml`

- [ ] **Step 1: Run the complete Python suite.** Run: `python -m unittest discover -s tests -v`. Expected: all tests PASS.
- [ ] **Step 2: Compile Python source.** Run: `python -m compileall -q .`. Expected: exit code 0.
- [ ] **Step 3: Build/typecheck the Next.js frontend.** Run in `frontend/`: `npm run typecheck && npm run build`. Expected: both commands succeed and `frontend/out/index.html` exists.
- [ ] **Step 4: Run API and browser smoke checks** from `.github/workflows/deploy-check.yml`. Expected: health, static homepage, archive endpoints, navigation, refresh recovery, discovery submission and responsive widths all pass.
- [ ] **Step 5: Update docs** to state the bounded source resolver, guarded outbound navigation, in-flight progress and still-existing single-process restart limitation.
- [ ] **Step 6: Final review** against the design acceptance criteria and all Review Focus cases. Do not claim live publisher support solely from mocked CI tests.
- [ ] **Step 7: Commit** `docs: document NewsTrace backend reliability behavior`.

---

## Verification boundary

Repository access in this session is through GitHub file/branch operations; there is no local checkout, shell, browser, or direct deployment-log access. The plan includes exact commands and the repository's CI workflow. If no executable CI run can be triggered from this isolated branch, source changes remain unverified and must be reported as such; a passing historical workflow run is not evidence that these new changes pass.
