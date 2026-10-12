-- Screen jobs and the console's event log. Deployed, every request may land on a different function
-- instance, so nothing one request leaves in memory reaches the next: both live here instead.

-- A screen from the moment it is asked for. The browser polls it; the request that runs it writes its steps.
create table public.screen_jobs (
  id          text primary key,
  fund_id     text not null,
  fund_name   text not null,
  extractor   text not null,
  judge       text not null,
  status      text not null check (status in ('queued', 'running', 'done', 'error')),
  gates       json not null,                -- gate ids in pipeline order, for the live view
  steps       json not null default '[]',   -- the pipeline's step timeline so far
  run_stamp   text,                         -- the run it produced, once done
  error       text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index screen_jobs_created_idx on public.screen_jobs (created_at desc);
alter table public.screen_jobs enable row level security;

-- What the agent monitor's server tab shows: jobs, catalog builds, gate and policy edits, sign-ins, errors.
create table public.console_events (
  id     bigint generated always as identity primary key,
  ts     timestamptz not null default now(),
  kind   text not null,
  level  text not null check (level in ('info', 'warn', 'error')),
  msg    text not null,
  extra  json not null default '{}'
);
alter table public.console_events enable row level security;
