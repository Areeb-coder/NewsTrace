# NewsTrace

**NewsTrace is a source-led digital newspaper and news-intelligence application.** It discovers publicly accessible article pages, extracts article metadata and available bylines, and presents the records in a searchable editorial archive.

The production application is a **Next.js / React / TypeScript frontend served by a FastAPI backend**. The existing Python discovery and Playwright extraction modules remain the investigation engine.

## Product

The current frontend contains four desks:

- **Front page** — lead story and latest source-linked article records.
- **Archive** — article search, section/publication/date filters, sorting, pagination and CSV/JSON export.
- **Coverage desk** — article totals, identified journalists, publication counts and section distribution.
- **Bylines** — journalist directory aggregated from extracted author metadata.

A user can start an investigation with a publication name or a direct section URL. The API returns a job ID immediately; discovery and extraction continue in the background, and the UI displays real server-reported stages, counts, warnings and results.

NewsTrace extracts public article metadata. The original publisher remains the authoritative source for full article text. Optional SerpAPI enrichment supplements publicly available journalist-profile data; the current frontend does not expose a separate LLM summary, sentiment, related-story or timeline service.

## Architecture

~~~text
Next.js static export
        |
        | same-origin HTTP
        v
FastAPI / Uvicorn
        |
        +-- discovery job lifecycle
        +-- source resolution
        +-- API-first / HTML article discovery
        +-- bounded Playwright extraction
        +-- optional public byline enrichment
        |
        v
Supabase Postgres (durable production jobs/results)
SQLite (local development fallback)
~~~

The frontend is exported by Next.js and served by FastAPI from the same Render service. This keeps the editorial UI and API on one origin and avoids a production CORS dependency.

## Local development

Requirements: Python 3.12, Node.js 26, npm, and a working Chromium installation.

### 1. Clone and install the backend

~~~bash
git clone https://github.com/Areeb-coder/NewsTrace.git
cd NewsTrace

python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
~~~

### 2. Start FastAPI

~~~bash
uvicorn backend.main:app --reload --port 8000
~~~

The API is available at [http://localhost:8000](http://localhost:8000). Health: [/api/health](http://localhost:8000/api/health). API documentation: [/docs](http://localhost:8000/docs).

### 3. Start Next.js

In a second terminal:

~~~bash
cd frontend
npm install
~~~

Windows PowerShell:

~~~powershell
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
npm run dev
~~~

macOS / Linux:

~~~bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
~~~

Open [http://localhost:3000](http://localhost:3000).

For local development, jobs are stored in `data/newstrace.sqlite3`. SQLite is not a production durability strategy on Render's free filesystem.

## Production configuration

Production uses the single FastAPI/Next.js Docker service defined in `render.yaml` and `Dockerfile.web`.

Apply the SQL migration in [`supabase/migrations/20261106_newstrace_discovery_jobs.sql`](supabase/migrations/20261106_newstrace_discovery_jobs.sql) to your Supabase project, then configure these Render environment variables:

| Variable | Required | Purpose |
|---|---:|---|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Server-only access to the private job/results table |
| `SERP_API_KEY` | No | Optional SerpAPI journalist enrichment |
| `NEWSTRACE_MAX_ACTIVE_JOBS` | Set to `1` initially | Concurrent in-process investigations |
| `NEWSTRACE_REQUIRE_DURABLE_STORE` | `true` in production | Fail startup rather than silently use ephemeral SQLite |

**Never expose `SUPABASE_SERVICE_ROLE_KEY` through a `NEXT_PUBLIC_*` variable or commit it to Git.** The service-role key must exist only in the backend environment. The legacy `SUPABASE_KEY` variable remains an optional compatibility fallback for the existing supplementary article/journalist tables.

See [DEPLOYMENT.md](DEPLOYMENT.md) and [SUPABASE_SETUP.md](SUPABASE_SETUP.md) for deployment and database steps.

## API contract

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | API and job-store health |
| POST | `/api/discovery/start` | Create a background investigation; returns `202` and `job_id` |
| GET | `/api/discovery/{job_id}` | Job status, actual stage counts and event history |
| GET | `/api/discovery/{job_id}/results` | Completed or partial article results |
| GET | `/api/articles` | Search, filter, sort and paginate the archive |
| GET | `/api/search` | Alias for article search |
| GET | `/api/categories` | Section/category counts |
| GET | `/api/sources` | Publication counts |
| GET | `/api/journalists` | Aggregated journalist directory |
| GET | `/api/coverage` | Article, journalist, publication and section metrics |

The browser retains only the job ID it started in local storage, then reconnects directly to that job after refresh. The API does not expose a global list of all visitors' jobs.

## Job lifecycle and operational boundaries

Statuses are `queued`, `running`, `complete`, `partial`, `failed` and `interrupted`. The backend stores real stage names, counts, event history, warnings, errors and results. It does not synthesize progress percentages across unrelated stages.

The first production release uses one FastAPI process and an in-process asynchronous worker/semaphore. This is intentionally simpler than adding Redis/Celery/Kafka before the product needs them. **Do not increase Uvicorn workers or scale to multiple API instances** with this scheduler: job execution and concurrency limits are process-local.

Job state and article-result snapshots are stored in Supabase in production, so completed records survive a container replacement. If the API process restarts during an active investigation, the job is marked `interrupted`; its execution is not automatically resumed. The user can start it again. A durable external task queue is a future requirement if jobs must survive process restarts without interruption.

The archive currently reads a bounded recent window of stored jobs (up to 100 investigations) and de-duplicates records when assembling the feed. This is appropriate for the current product scale; a larger archive should move filtering and pagination into indexed article-level database queries.

## Research and responsible use

NewsTrace uses bounded request timeouts and concurrency, rejects obvious local/private URL targets, and retains source links. It cannot guarantee access to every publisher: sites may block automation, require authentication, use paywalls or return non-article interstitial pages. Respect publisher terms, applicable laws, robots policies and rate limits. The system must not bypass access controls.

## Validation

GitHub Actions checks:

- Next.js TypeScript type-check and static production build.
- Python compilation and discovery/parser/job-store tests.
- FastAPI health, homepage and API route responses.
- Browser navigation, discovery submission/result rendering, refresh recovery and responsive overflow.

These tests verify application integration and controlled test fixtures. They do not prove that every external publisher permits scraping.

## Recognition

**Runner-Up — Hack of Thrones Hackathon**, organized by Google Developer Group (GDG) JMI.
