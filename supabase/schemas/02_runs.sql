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
