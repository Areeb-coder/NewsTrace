# NewsTrace — Next.js / FastAPI Migration

## What changed

NewsTrace now has a second, production-oriented web application alongside the legacy Streamlit app.

- frontend/ is a Next.js App Router application written in React and TypeScript.
- Tailwind CSS v4 provides the utility layer; the editorial layout is implemented with reusable CSS tokens and components.
- Motion for React handles the restrained masthead, story and modal transitions.
- backend/ is a FastAPI application which serves the API and the static Next.js export from one origin.
- Existing Python article discovery, Playwright extraction, author extraction, author-profile enrichment, SerpAPI enrichment and optional Supabase functions remain the business-logic layer.
- app.py and dashboard.py are retained as the legacy Streamlit interface.

The new service is configured as a separate Render web service (newstrace-web). The original newstrace service remains in render.yaml and continues to use the original Dockerfile.

## Repository audit findings

### Existing execution path

The legacy application resolved the source, called unified_scraping_pipeline, then used the Streamlit session state to render its DataFrame and analytics.

The discovery path was:

1. Source resolution.
2. API-first article discovery.
3. Bounded Playwright listing crawl when no compatible API was found.
4. Parallel Playwright article extraction using reusable pages.
5. Optional public author-profile extraction.
6. Optional SerpAPI enrichment.
7. Optional Supabase writes.
8. Streamlit rendering and session-state updates.

### Confirmed event-loop blocking issue

collect_article_urls is asynchronous, but it called try_api_scraping directly. That API-first function uses synchronous requests calls to probe publisher endpoints (bounded by its own deadline and request timeouts). Because those requests ran inside the async discovery coroutine, they blocked the event loop while waiting for endpoint responses. The same loop is responsible for driving asynchronous Playwright work and delivering progress to the UI. This could make the app appear stuck during the API discovery phase.

The collector now runs the bounded API probe through asyncio.to_thread. Its callback is marshalled back onto the event loop with call_soon_threadsafe, preserving the existing callback contract while allowing asynchronous discovery and extraction to continue.

### What was and was not established

The audit confirmed the blocking API-probe path above. It did not establish that all reports of a stuck screen came from that single cause: a publisher can still reject browser requests, expose no article links, time out or return non-article interstitial pages. Those cases are retained as extraction failures with diagnostics rather than represented as successful progress.

## New request / job lifecycle

The Next.js client never waits for article discovery inside the request that starts it.

    Next.js UI
       | POST /api/discovery/start
       v
    FastAPI creates SQLite job row
       | returns job_id immediately
       v
    in-process async job task
       +-- source resolution (off the event loop)
       +-- API-first / HTML article discovery
       +-- parallel Playwright extraction
       +-- optional author profile enrichment
       +-- optional SerpAPI enrichment
       +-- optional Supabase persistence
       +-- store article records + stats
       ^
       | GET /api/discovery/{job_id}
       | GET /api/discovery/{job_id}/results
    Next.js polls and displays actual job events and counts

### Job status

Statuses are queued, running, complete, partial, failed and interrupted.

Each progress event stores the stage name, detail string, current count, total count and timestamp. The UI displays those recorded values. It does not synthesize a progress percentage across unrelated phases.

If the API process restarts while a job is queued or running, startup recovery changes it to interrupted with a retry instruction. It is not left in a permanent running state.

## API endpoints

| Endpoint | Purpose |
|---|---|
| GET /api/health | Health check and active task count |
| POST /api/discovery/start | Start a background investigation and return a job ID |
| GET /api/discovery/{job_id} | Retrieve live status and event history |
| GET /api/discovery/{job_id}/results | Retrieve completed or partial article results |
| GET /api/jobs | Recent investigation list |
| GET /api/articles | Search/filter/sort the collected archive |
| GET /api/search | Alias for article search |
| GET /api/categories | Coverage section counts |
| GET /api/sources | Publication/source counts |
| GET /api/journalists | Aggregated journalist directory |
| GET /api/coverage | Article, journalist, source and section metrics |

The API validates the outlet input and bounds the requested article count (10–500). Errors returned to the UI are plain-language messages; detailed exceptions remain in the server logs.

## Data and persistence

backend/jobs.py stores job status, progress events, statistics, warnings and JSON article records in SQLite. The default path is data/newstrace.sqlite3. Set NEWSTRACE_DB_PATH to choose another path.

The new Render service uses a single Uvicorn worker because the first-phase scheduler and semaphore are process-local. Do not increase the worker count unless the scheduler and job store are moved to a shared service.

**Important deployment boundary:** the free Render service uses an ephemeral container filesystem. SQLite job results survive ordinary requests and process activity in the running container, but are not a durable archive across a container replacement/redeploy on an ephemeral filesystem. For durable production history, mount a persistent disk and point NEWSTRACE_DB_PATH to it, or move the job/result store to a shared database/queue. The optional Supabase article/journalist tables continue to be used when configured, but the job-status store is SQLite in this migration phase.

A single-process in-process task is appropriate for the first migration and keeps the code/deployment footprint small. A future multi-instance deployment should replace it with a durable queue (for example, Redis-backed workers) and a shared job store.

## Local development

### API

Commands:

    python -m venv .venv
    # Windows PowerShell:
    .venv\Scripts\Activate.ps1
    # macOS/Linux:
    # source .venv/bin/activate

    python -m pip install -r requirements.txt
    playwright install chromium
    uvicorn backend.main:app --reload --port 8000

### Next.js frontend

Commands:

    cd frontend
    npm install
    NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev

Open http://localhost:3000. The API remains at http://localhost:8000.

### Legacy Streamlit interface

The previous app remains available during the migration:

    streamlit run app.py

## Deployment

The existing Render newstrace service continues to use Dockerfile and the Streamlit health route. The separate newstrace-web service uses Dockerfile.web:

1. Node 26 builds the static Next.js export into frontend/out.
2. The Playwright Python image installs the original Python requirements plus FastAPI/Uvicorn.
3. FastAPI serves /api/* and the exported frontend from the same service.
4. Render checks /api/health.

The service defaults to one active investigation at a time on Render (NEWSTRACE_MAX_ACTIVE_JOBS=1). Change this only after reviewing the memory available for parallel Playwright browsers.

### Optional integrations on the new service

Render environment variables are scoped to each service. The new newstrace-web service does not automatically inherit secrets configured on the existing newstrace Streamlit service. To keep optional features enabled, copy the required values into the new service's Environment settings:

- SUPABASE_URL
- SUPABASE_KEY
- SERP_API_KEY

Do not commit the actual values. The root .env.example and frontend/.env.example show the non-secret local-development settings. In production, leave NEXT_PUBLIC_API_BASE_URL unset because the Next.js export and FastAPI API share the same origin.

## QA gates

The GitHub Actions workflow now checks both implementations:

- Install the frontend dependencies.
- Run TypeScript type checking.
- Build the static Next.js export.
- Confirm frontend/out/index.html exists.
- Install Python dependencies and Chromium.
- Compile all Python sources.
- Run article discovery, parser, image and job-store regression tests.
- Start FastAPI and check the health endpoint, homepage and archive endpoints.
- Start the legacy Streamlit app and check its original health endpoint.

The CI smoke test validates service startup and route responses. It does not prove that every publisher permits scraping; source-specific discovery still needs real publisher checks.
