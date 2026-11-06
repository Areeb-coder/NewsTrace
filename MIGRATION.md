# NewsTrace architecture and migration record

## Canonical production architecture

The migration is complete in the repository architecture:

- `frontend/` is the canonical Next.js App Router application (React + TypeScript).
- `backend/main.py` is the FastAPI application and serves the static Next.js export from the same origin.
- `backend/investigation.py` orchestrates the existing Python discovery, Playwright extraction and optional journalist enrichment modules.
- `backend/jobs.py` stores job states, progress events, warnings, statistics and article-result snapshots. Production uses Supabase Postgres; local development uses SQLite.
- The legacy Streamlit UI and its production startup path are removed.

## Frontend-to-backend contract

The actual frontend has four desks:

| Frontend feature | Request | Backend/data flow |
|---|---|---|
| Front page | `GET /api/articles?limit=60&sort=latest` | Read latest stored article records |
| Archive search | `GET /api/articles` | Filter by query, section, source, date range and sort; return offset/limit |
| Section filters | `GET /api/categories` | Aggregate section counts |
| Publication filters | `GET /api/sources` | Aggregate outlet counts |
| Coverage desk | `GET /api/coverage` | Aggregate article, author, section and outlet metrics |
| Byline directory | `GET /api/journalists?q=...` | Aggregate identified authors and public profile fields |
| Start investigation | `POST /api/discovery/start` | Validate input, create persistent job, start bounded background task; return job ID |
| Live job view | `GET /api/discovery/{job_id}` | Return current state, stage/count, event trail and errors |
| Results | `GET /api/discovery/{job_id}/results` | Return persisted article records and warnings |
| Refresh recovery | `GET /api/discovery/{job_id}` | Browser reconnects to its own UUID stored in local storage |

There is no separate AI summary, sentiment, related-story or timeline endpoint in the current frontend. The current product shows source-linked metadata, available descriptions/summaries and journalist/coverage aggregation; it does not invent AI analysis when no such result exists.

## Data flow

~~~text
Visitor
  |
  v
Next.js editorial UI
  |
  +-- GET article/archive/facet APIs
  |
  +-- POST /api/discovery/start
          |
          v
      FastAPI creates job row
          |
          v
      Background investigation task
          |
          +-- Resolve publication
          +-- API-first article discovery
          +-- Bounded HTML section crawl
          +-- URL de-duplication
          +-- Concurrent Playwright extraction
          +-- Metadata and byline parsing
          +-- Optional author profile enrichment
          +-- Optional SerpAPI enrichment
          |
          v
      Persist job, events, stats and article snapshots
          |
          v
      Next.js polls job status and displays results
~~~

Each source/page failure is isolated where possible. Valid article records are retained when a byline is unavailable; failed fetches are reported as failures. Optional search enrichment is not required for the archive to work.

## Background job model

The API returns `202 Accepted` with a UUID `job_id`; it does not wait for scraping inside the start request. The frontend polls status and displays actual backend stage labels, counts, details and warnings.

Statuses: `queued`, `running`, `complete`, `partial`, `failed`, `interrupted`.

The initial implementation uses one FastAPI process, an in-process async task and a semaphore. This avoids introducing Redis/Celery/Kafka before the application needs distributed execution. It is intentionally a single-instance architecture: do not add Uvicorn workers or scale to multiple API instances while the scheduler is process-local.

Job state and final article snapshots are stored durably in Supabase for production. An active task cannot survive a process restart; startup marks running jobs interrupted while retaining the last observed counts and events. The user can retry. If jobs must resume automatically after restarts or scale across several instances, introduce a durable queue and shared workers.

## Storage

- **Local development:** SQLite at `data/newstrace.sqlite3`.
- **Production:** `public.newstrace_discovery_jobs` (Supabase Postgres JSONB snapshots).
- **Supplementary persistence:** existing `articles` and `journalists` tables remain optional.

The production service uses `SUPABASE_SERVICE_ROLE_KEY` only on the backend. The migration enables RLS and defines no anonymous/authenticated policies for the internal jobs table. The durable store is required by the Render Blueprint; missing credentials/schema prevent startup instead of silently losing data to an ephemeral filesystem.

The archive reads a bounded recent window of completed jobs. For substantially larger datasets, the next data-model step is a normalized article table with indexed server-side filtering and pagination rather than loading recent JSON snapshots into Python.

## Security and operational boundaries

- Discovery accepts only HTTP(S) URLs, rejects embedded URL credentials, nonstandard ports and obvious local/private address forms.
- Start requests are rate-limited per client address.
- Browser article links are sanitized to HTTP(S) before rendering.
- Supabase service-role credentials remain server-only.
- The current UI has no account/authentication flow; do not expose private source credentials or sensitive personal data in scraped records.
- URL validation is a defensive first layer, not a complete network-level SSRF boundary. For higher-risk public use, enforce outbound egress controls at the hosting/network layer and validate redirect destinations.
- Respect publisher terms, rate limits and access controls. NewsTrace does not bypass paywalls or CAPTCHA challenges.

## Deployment

The root `render.yaml` defines one Docker web service using `Dockerfile.web`. Node builds the Next.js static export; a Playwright Python image runs FastAPI and serves the export. The service uses one Uvicorn worker and a durable Supabase store. The committed Blueprint selects Render Free for preview/testing only; upgrade to paid always-on compute before production because Free services spin down and can interrupt active in-process jobs. Completed Supabase records remain durable, but active tasks do not survive process restarts.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the exact Render and Supabase steps, and [SUPABASE_SETUP.md](SUPABASE_SETUP.md) for database configuration.
