-- NewsTrace durable discovery jobs and article archive snapshots.
-- Apply this migration in the Supabase SQL editor before deploying the web service.
-- The backend uses SUPABASE_SERVICE_ROLE_KEY only. Do not add anon/authenticated
-- policies for this internal job table.

create table if not exists public.newstrace_discovery_jobs (
    id uuid primary key,
    outlet text not null,
    source_url text,
    status text not null check (status in ('queued', 'running', 'complete', 'partial', 'failed', 'interrupted')),
    stage text not null default 'Queued',
    detail text not null default '',
    current_count integer not null default 0 check (current_count >= 0),
    total_count integer not null default 0 check (total_count >= 0),
    events_json jsonb not null default '[]'::jsonb,
    parameters_json jsonb not null default '{}'::jsonb,
    stats_json jsonb not null default '{}'::jsonb,
    warnings_json jsonb not null default '[]'::jsonb,
    results_json jsonb not null default '[]'::jsonb,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    finished_at timestamptz
);

create index if not exists idx_newstrace_jobs_created
    on public.newstrace_discovery_jobs (created_at desc);

create index if not exists idx_newstrace_jobs_status_created
    on public.newstrace_discovery_jobs (status, created_at desc);

alter table public.newstrace_discovery_jobs enable row level security;

-- Deliberately no policies: only the backend service-role key may access this table.
