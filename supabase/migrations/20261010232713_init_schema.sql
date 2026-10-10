-- from supabase/schemas/01_config.sql
-- Screening configuration: the gates and the policy that combines them.
-- The app connects as the database owner; RLS with no policies keeps every table closed to
-- Supabase's public Data API (anon and authenticated roles).

-- One row per live gate. `yaml` is the definition exactly as the analyst wrote it, comments kept;
-- `position` is the order the pipeline runs gates and the console shows them.
create table public.gates (
  id         text primary key check (id ~ '^[a-z][a-z0-9_]{1,48}$'),
  position   integer not null check (position > 0),
  yaml       text not null,
  version    integer not null default 1,
  updated_at timestamptz not null default now()
);
alter table public.gates enable row level security;

-- The prior state of a gate, saved before every edit and delete, so any change can be restored.
create table public.gate_history (
  id         bigint generated always as identity primary key,
  gate_id    text not null,
  position   integer,
  yaml       text not null,
  version    integer,
  reason     text not null check (reason in ('edit', 'deleted')),
  created_at timestamptz not null default now()
);
create index gate_history_gate_id_idx on public.gate_history (gate_id, created_at desc);
alter table public.gate_history enable row level security;

-- Disposition policy, append-only: the newest row is in force, older rows are its history.
create table public.policies (
  id         bigint generated always as identity primary key,
  yaml       text not null,
  created_at timestamptz not null default now()
);
alter table public.policies enable row level security;

-- from supabase/schemas/02_runs.sql
-- Screening runs and the model calls behind them.
-- Payloads are `json`, not `jsonb`, on purpose: jsonb reorders object keys, and the console shows
-- gates, answers and flags in the order the pipeline wrote them.

create table public.runs (
  id          uuid primary key default gen_random_uuid(),
  fund_id     text not null,                 -- data room folder slug, e.g. Monroe_Capital_-_ABF
  stamp       text not null check (stamp ~ '^\d{8}T\d{6}$'),
  fund_name   text not null,
  extractor   text,
  judge       text,
  disposition text not null,
  policy_id   bigint references public.policies (id),
  summary     json not null,                 -- summary.json as the pipeline writes it
  report_md   text not null default '',
  created_at  timestamptz not null default now(),
  unique (fund_id, stamp)
);
create index runs_created_at_idx on public.runs (created_at desc);
alter table public.runs enable row level security;

-- One row per gate per run. `gate_yaml` is the exact definition the gate ran with.
create table public.run_gates (
  run_id         uuid not null references public.runs (id) on delete cascade,
  gate_id        text not null,
  position       integer not null,
  gate_version   integer,
  gate_yaml      text,
  result         text not null,
  review         boolean not null default false,
  min_confidence numeric,
  record         json not null,              -- the full gate record: brief, answers, timeline, calls
  primary key (run_id, gate_id)
);
alter table public.run_gates enable row level security;

-- Every model call, written as it happens so failed runs still leave a trail.
create table public.model_calls (
  id                text primary key,
  ts                timestamptz not null,
  fund              text,
  gate              text,
  step              text,
  provider          text not null,
  model             text,
  seconds           numeric,
  ok                boolean not null,
  error             text,
  attempts          integer,
  input_tokens      integer,
  output_tokens     integer,
  cache_read_tokens integer,
  input_chars       integer,
  output            text
);
create index model_calls_ts_idx on public.model_calls (ts desc);
alter table public.model_calls enable row level security;

-- from supabase/schemas/03_catalogs.sql
-- Document catalogs, rebuilt deterministically from the local data rooms (the files stay local).

create table public.catalogs (
  room_id   text primary key,                -- data room folder slug
  room_name text not null,
  summary   json not null,
  built_at  timestamptz not null default now()
);
alter table public.catalogs enable row level security;

create table public.catalog_documents (
  room_id  text not null references public.catalogs (room_id) on delete cascade,
  doc_id   text not null,
  ordinal  integer not null,                 -- catalog order
  doc      json not null,
  primary key (room_id, doc_id)
);
alter table public.catalog_documents enable row level security;
