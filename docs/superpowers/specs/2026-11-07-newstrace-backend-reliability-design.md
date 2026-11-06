# NewsTrace Backend Reliability Reconstruction — Design

**Date:** 2026-11-07  
**Repository:** `Areeb-coder/NewsTrace`  
**Base:** `feat/nextjs-fastapi-migration` at `3f5b06b35cbda9262a6ff7ac832cfa98d12c2b3a`  
**Working branch:** `fix/newstrace-backend-reconstruction`

## Intent

Make the existing NewsTrace product reliably complete its real user workflow: accept a publication or section URL, discover article links, extract public article metadata and bylines, persist a job and its records, and show accurate progress/results in the existing Next.js newspaper interface. Preserve the existing product and reusable Python investigation/extraction modules. Do not substitute mock results or add features the product does not expose.

## Evidence from repository reconnaissance

The target branch is `feat/nextjs-fastapi-migration`; the exact branch name in the handoff, `nextje-fastqpi-migratiom`, does not exist.

The README, migration notes and frontend source agree on four desks: Front Page, Archive, Coverage Desk and Bylines. The visible API contract is:
- `GET /api/health`
- `POST /api/discovery/start`
- `GET /api/discovery/{job_id}`
- `GET /api/discovery/{job_id}/results`
- `GET /api/articles` and `GET /api/search`
- `GET /api/categories`, `GET /api/sources`, `GET /api/journalists`, `GET /api/coverage`

The implemented investigation sequence is source resolution → API discovery → bounded HTML discovery → bounded parallel article extraction → optional journalist profile/SerpAPI enrichment → result persistence. The frontend polls job state and reconnects to the job ID saved by that browser. It does not currently expose a separate LLM summary, sentiment, related-story or timeline feature; do not invent one.

The current backend uses an in-process async task plus semaphore. The production deployment intentionally uses one Uvicorn worker and one service instance; jobs/results are durable in Supabase, while local development uses SQLite. Active work is not resumable after process restart and is marked interrupted. Preserve that explicit single-process boundary unless the owner separately approves new queue infrastructure.

Initial risk findings requiring focused verification:
1. `backend/source_resolver.py` makes synchronous outbound requests for a publication name: a DuckDuckGo query (10-second timeout) followed by up to six domain guesses (each with a 6-second timeout). This can leave the job in the source-resolution stage for an extended period with no finer progress detail.
2. `backend/main.py` validates a URL before discovery, but its own docstring calls this an “obvious” local/private-target filter. It does not by itself validate DNS results or every redirect destination.
3. `utils/article_collector.py` and the Playwright extraction path follow redirects. Redirect and browser subresource handling must be examined as part of the outbound URL safety boundary.
4. Archive/filter/facet endpoints load article snapshots from up to 100 completed investigations and perform aggregation/filtering in Python. The README calls this a current-scale boundary; do not silently treat it as an indexed large-archive implementation.
5. Existing tests cover parser behavior, the SQLite job store, selected API lifecycle behavior and basic URL validation. They do not establish live external publisher reliability or prove deployment secrets/database configuration are correct.

These are code-inspection findings, not yet a reproduced runtime failure. No source code has been changed and no tests/build have been run in a local project runtime during reconnaissance.

## Technical references reviewed

- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) says in-process background work is appropriate for work that can stay with the same application process, while heavier work that benefits from multiple processes/servers may need a separate worker/queue. This supports retaining the documented single-process design for this targeted repair, not pretending that it survives restarts.
- [Python asyncio tasks and timeouts](https://docs.python.org/3/library/asyncio-task.html) documents `asyncio.timeout()` / `wait_for()` cancellation and `asyncio.to_thread()`. An async deadline around a thread wait does not prove the underlying blocking function stopped; the blocking HTTP calls must also have their own connect/read timeouts.
- [Playwright Python Page API](https://playwright.dev/python/docs/api/class-page) documents navigation timeouts and that `page.goto()` returns the last non-redirect response. [Playwright Network](https://playwright.dev/python/docs/network) specifically says route handlers run only for the first URL in a redirect chain, after which the browser follows redirects itself. Therefore, adding `browser_context.route()` alone is not a complete redirect-target security check.
- [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) warns that domain validation alone does not prevent DNS rebinding: validation must cover resolved destination addresses and the actual connection destination. When users may investigate arbitrary public publishers, a strict hostname allowlist is not compatible with the product; network egress isolation or a controlled outbound proxy is the stronger deployment boundary.

## Goals

- Make discovery and extraction bounded, observable and failure-isolated.
- Ensure slow/blocking source resolution and API probes do not starve FastAPI status polling.
- Give users useful, truthful stage/detail/error messages; never fabricate progress.
- Keep the job lifecycle and frontend contract consistent across queued, running, complete, partial, failed and interrupted states.
- Harden source URL handling across resolution, redirects and browser navigation, within the hosting environment's available controls.
- Preserve job and article provenance, Supabase durability, and the local SQLite test/development path.
- Keep Next.js visual design and working desk interactions intact.
- Add deterministic regression tests for each reproduced defect and update operational documentation.

## Non-goals

- No new LLM summarization, sentiment, topic intelligence or generated article content.
- No redesign or replacement of the four existing newspaper desks.
- No Redis/Celery/Kafka or multi-instance execution in this repair unless repository evidence proves it necessary and the infrastructure is explicitly approved.
- No automatic resumption of active browser tasks after a process restart under the current in-process scheduler.
- No deletion of Streamlit-era scraper utilities or production data merely for cleanup.
- No claim that every publisher can be scraped; paywalls, CAPTCHA and publisher access controls remain respected.

## Approaches considered

### A. Targeted reliability reconstruction around the current architecture — recommended

Retain FastAPI, the Next.js static export, the existing article discovery/extraction modules, Supabase/SQLite stores and the one-process scheduler. Trace and reproduce the visible failure, then repair the narrow failure paths: bounded source resolution, progress/event propagation, request-level deadlines, browser/network failure isolation, job persistence and frontend terminal-state handling. Add tests before each behavior change.

**Trade-off:** active jobs can still be interrupted by process restarts and the archive remains snapshot-backed. Those constraints are already documented and are preferable to adding unconfigured infrastructure in a bug-fix pass.

### B. Introduce a durable external queue now

Move investigation execution to a worker/queue system and keep FastAPI as an API layer.

**Trade-off:** this improves restart recovery and horizontal scaling, but adds infrastructure, deployment secrets, operational monitoring and migration complexity. The repository is explicitly designed around one in-process worker and no queue is configured. It is not the smallest safe response to an as-yet-unreproduced stall.

### C. Replace the backend wholesale

Rebuild routes, data model and scraper orchestration as a new subsystem.

**Trade-off:** could simplify architecture, but discards substantial existing parser, crawler, enrichment, persistence and test coverage. It risks regressions and is not justified before pinpointing the failure.

**Decision proposed:** Approach A.

## Proposed implementation shape

1. **Reproduce and instrument the failure.** Use existing unit/integration tests as a baseline; add focused tests around source resolution timing/failures, progress callback delivery, job terminal transitions and frontend polling failures. Inspect the precise stage and event history rather than inferring from a spinner.
2. **Bound source resolution.** Use explicit connect/read timeouts and an overall deadline; stop the repeated TLD guess sequence from consuming an unbounded user wait; provide meaningful progress stages and useful input guidance. Prefer direct URLs or a controlled search result when appropriate. A lookup failure should set a terminal job error rather than leave it running. Do not rely only on cancelling an `asyncio.to_thread()` await to stop a synchronous HTTP call.
3. **Harden outbound source navigation.** Validate HTTP(S), credentials, ports and resolved addresses. Handle redirects explicitly for HTTP clients. Do not assume a Playwright route handler is invoked for each redirect hop; use a proven redirect policy and document any residual DNS-rebinding risk. Validate browser requests where interception applies and use hosting-level egress restrictions or a controlled proxy for the actual network boundary where available. Do not bypass publisher protections.
4. **Protect the async job lifecycle.** Keep blocking I/O off the event loop, bound concurrency and request times, preserve ordered progress writes, handle task cancellation/shutdown, and ensure storage errors cannot silently yield a false successful result.
5. **Validate extraction and partial success.** Retain valid article metadata when individual pages fail, record bounded diagnostics, enforce per-page deadlines, and classify complete vs partial consistently.
6. **Preserve API/frontend contract.** Confirm the existing response fields and status values used by `frontend/lib/api.ts` and `frontend/app/page.tsx`. Ensure polling continues during transient network errors but stops on terminal states, shows errors and allows the existing retry interaction.
7. **Verify data and deployment.** Test SQLite and mocked Supabase behavior, health checks, static export serving, one-worker deployment assumptions, required Render environment variables and migration instructions. Do not change Render plan, add queue infrastructure or mutate production data.

## Acceptance criteria

- A valid supported test publication can be submitted and returns a job ID promptly.
- The job records real progress events for resolution, discovery and extraction; slow source resolution has a bounded, visible outcome.
- A single failed page/source does not discard other valid records.
- A zero-result run ends in a useful failed state with actionable diagnostics, not a perpetual running state or fabricated success.
- Successful and partial runs persist actual articles and return them via the existing results endpoint.
- The frontend renders active, complete, partial, failed and interrupted job states and recovers the locally saved job ID after refresh.
- Archive, search, filters, article details, coverage and bylines preserve their existing API shapes and work with fixtures.
- Security tests cover unsafe hosts, redirect targets and browser navigation boundaries to the level supported by the runtime.
- Unit/integration tests, Next.js typecheck/build, API smoke checks and Playwright browser checks pass in an actual project runtime before the work is described as verified.
- README/deployment docs clearly state remaining single-worker, process-restart, storage and publisher-access limitations.

## Calls left to the implementer

The exact failing branch must be proven through targeted tests/log evidence before changing behavior. The implementer may split the work into independently reviewable source-resolution/security, job/progress lifecycle and archive/API integration tasks. Keep each change minimal and test-backed. If investigation shows a queue or schema migration is unavoidable, stop and present its operational cost before introducing it.
