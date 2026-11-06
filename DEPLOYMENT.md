# NewsTrace production deployment

NewsTrace is deployed as **one Docker web service**: a statically exported Next.js editorial frontend served by FastAPI, with the existing Python/Playwright investigation pipeline behind the API.

## 1. Configure durable Supabase storage

Render's free web-service filesystem is ephemeral. Do not rely on the local SQLite database for production job/result history.

1. Open your Supabase project.
2. Run the SQL in `supabase/migrations/20261106_newstrace_discovery_jobs.sql`.
3. Copy the Supabase project URL.
4. Copy the **service_role** key from the Supabase API settings. It is a private server credential.

The migration creates `public.newstrace_discovery_jobs`, enables row-level security, and deliberately adds no anon/authenticated policies. The FastAPI backend accesses it with `SUPABASE_SERVICE_ROLE_KEY`.

The existing supplementary `articles` and `journalists` tables are described in [SUPABASE_SETUP.md](SUPABASE_SETUP.md). They are optional; the durable job table contains the authoritative job state and article-result snapshots used by the new API.

## 2. Deploy the canonical application

The root `render.yaml` now defines one service named `newstrace` and uses `Dockerfile.web`. The Dockerfile:

1. Builds the static Next.js export.
2. Installs the Python API and Playwright dependencies.
3. Copies the Next.js export into the FastAPI image.
4. Starts one Uvicorn worker serving both the frontend and `/api/*`.

In Render:

1. Open the existing NewsTrace Blueprint/service.
2. Sync the repository's latest `main` configuration.
3. When prompted, set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
4. Apply the Blueprint and wait for the Docker build and health check.
5. Open the existing `.onrender.com` service URL. The root path serves the newspaper UI; `/api/health` checks the API and durable store.

The Blueprint sets `NEWSTRACE_REQUIRE_DURABLE_STORE=true`. The service will fail its startup/health check instead of silently falling back to ephemeral SQLite if the migration or credentials are missing.

### Render Free plan is preview/test only

The committed `render.yaml` intentionally uses `plan: free` for a cost-free preview. Render explicitly says Free web services should not be used for production. They spin down after 15 minutes without inbound traffic, take about a minute to spin back up, lose local filesystem changes when they spin down/restart, and may be restarted at any time. That means an active Playwright investigation can be interrupted when the process stops. Supabase keeps completed job/result snapshots, but it cannot keep an in-process task running. Before production use, change the service to a paid always-on Render compute plan with resources appropriate for Python + Chromium; the documented 1 CPU / 2 GB plan (`1c-2g`, legacy `standard`) is a reasonable starting point to benchmark, not a guaranteed capacity target. Keep a single service instance and one Uvicorn worker until background execution moves to a durable shared queue.

## 3. Environment variables

| Variable | Value |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Private service-role key; backend only |
| `NEWSTRACE_REQUIRE_DURABLE_STORE` | `true` |
| `NEWSTRACE_MAX_ACTIVE_JOBS` | `1` |
| `SERP_API_KEY` | Optional; only for search enrichment |

Do not set `NEXT_PUBLIC_API_BASE_URL` in production. The Next.js export and API share the same origin.

## 4. Local production-like run

Backend:

~~~bash
python -m pip install -r requirements.txt
python -m playwright install chromium
uvicorn backend.main:app --host 0.0.0.0 --port 8000
~~~

Frontend build:

~~~bash
cd frontend
npm install
npm run typecheck
npm run build
~~~

When building the combined Docker image, `Dockerfile.web` performs the frontend build and copies `frontend/out` into the API image.

## 5. Health and troubleshooting

Open `/api/health`. A healthy production response reports `storage.backend = "supabase"`, `storage.durable = true`, and `storage.ok = true`.

- **Service fails to start / HTTP 503 health:** apply the Supabase SQL migration and verify `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
- **Homepage returns 503:** the Next.js static build did not produce `frontend/out/index.html`; inspect the Docker build logs.
- **Investigation becomes interrupted after deploy/restart:** this is expected for an in-process worker. Completed job/results remain in Supabase; active execution is marked interrupted and can be retried.
- **Publisher returns no results:** check job events and server logs. A successful application health check does not mean every publisher allows automated extraction.
- **Source resolution appears slow:** publication-name lookup reports its search and domain-check stages and uses a bounded number of requests. Prefer a direct publication or section URL when the name lookup cannot identify the correct official site.
- **Unsafe URL / redirect rejected:** NewsTrace checks DNS results and validates every HTTP redirect destination; Playwright requests to private or non-public addresses are aborted. This is defense in depth, not a replacement for network-level egress controls against DNS rebinding.
- **Optional enrichment warning:** set `SERP_API_KEY` only if search enrichment is required.

## 6. Scaling boundary

Keep one Uvicorn worker and one service instance. The job semaphore and task scheduler are process-local. If NewsTrace later needs multiple instances or jobs that resume after process restarts, move execution to a durable shared queue/worker system before scaling out.

## 7. Retired production path

The canonical service uses `Dockerfile.web`, `/api/health`, Next.js and FastAPI.


## Optional pagination

The crawler reads "next page" links with one immediate DOM evaluation. Pagination
is best-effort: no matching link or a DOM replacement returns an empty list and
does not discard the article links already collected from the current page.
