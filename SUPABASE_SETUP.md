# Supabase setup for NewsTrace

NewsTrace uses Supabase for the **durable discovery-job and article-result store** in production. The backend keeps the Supabase service-role key server-side; it is never sent to the Next.js browser.

## 1. Create the project

Create a Supabase project and copy:

- Project URL
- **service_role** secret key (not the anon/publishable key)

Store these values in your local root `.env` file or Render service environment:

~~~env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-private-service-role-key
NEWSTRACE_REQUIRE_DURABLE_STORE=true
~~~

Never put the service-role key in `frontend/.env`, a `NEXT_PUBLIC_*` variable, Git or client-side JavaScript.

## 2. Create the required discovery-job table

In the Supabase SQL Editor, run the migration committed in this repository:

`supabase/migrations/20261106_newstrace_discovery_jobs.sql`

It creates `public.newstrace_discovery_jobs` with:

- Job ID, outlet and source URL.
- Status, stage, real current/total progress counts and detail.
- JSONB event history, request parameters, statistics and warnings.
- JSONB article-result snapshots.
- Error and created/updated/finished timestamps.
- Indexes for status and recent-job ordering.

Row-level security is enabled. The migration deliberately creates no anon/authenticated policies. NewsTrace accesses this internal table with the server-side service-role key. Do not expose that key to the frontend.

## 3. Optional supplementary article and journalist tables

The current production archive and job status are persisted in `newstrace_discovery_jobs`. The legacy supplementary save helpers can also populate `articles` and `journalists` tables. They are optional and are not required for the Next.js archive, which reads article snapshots from the durable job store.

When you want those supplementary tables, run this SQL as well:

~~~sql
CREATE TABLE IF NOT EXISTS public.articles (
  id BIGSERIAL PRIMARY KEY,
  outlet TEXT NOT NULL,
  author TEXT,
  title TEXT,
  section TEXT,
  date TEXT,
  url TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.journalists (
  id BIGSERIAL PRIMARY KEY,
  outlet TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT,
  email TEXT,
  bio TEXT,
  twitter TEXT,
  linkedin TEXT,
  instagram TEXT,
  facebook TEXT,
  article_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(outlet, name)
);

CREATE INDEX IF NOT EXISTS idx_articles_outlet ON public.articles(outlet);
CREATE INDEX IF NOT EXISTS idx_articles_author ON public.articles(author);
CREATE INDEX IF NOT EXISTS idx_journalists_outlet ON public.journalists(outlet);
CREATE INDEX IF NOT EXISTS idx_journalists_name ON public.journalists(name);
~~~

## 4. Configure Render

The root `render.yaml` defines one canonical Next.js + FastAPI web service. When syncing the Blueprint, provide:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

It sets `NEWSTRACE_REQUIRE_DURABLE_STORE=true`. If the table or credentials are missing, the service fails its startup/health check instead of silently using the ephemeral local filesystem.

Open `/api/health` after deployment. A production-ready storage response should report:

~~~json
{
  "storage": {
    "backend": "supabase",
    "durable": true,
    "ok": true
  }
}
~~~

The API health response also reports service time and active investigation count.

## 5. Local development

For local development without Supabase, leave `NEWSTRACE_REQUIRE_DURABLE_STORE=false`. The job store will use `data/newstrace.sqlite3`. This is for development and tests only; do not rely on a container-local SQLite file for production history.

To use Supabase locally, set the same three environment variables in the root `.env` file.

## 6. Optional SerpAPI enrichment

Search enrichment is independent from job storage. To enable it, add:

~~~env
SERP_API_KEY=your-serpapi-key
~~~

The application continues to function when this optional key is absent.
