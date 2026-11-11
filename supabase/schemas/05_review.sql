-- Analyst review of screen runs (decisions G1, G2, C3, C4). Reviews and checks are append-only: the newest
-- row for a gate is in force and the older rows are its history.

-- Who reviews. A named role, so a second analyst can be added beside the CIO.
create table public.reviewers (
  id         text primary key check (id ~ '^[a-z][a-z0-9_]{1,30}$'),
  name       text not null check (length(btrim(name)) > 0),
  role       text not null check (role in ('analyst', 'cio')),
  active     boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.reviewers enable row level security;

-- An analyst's call on one gate of one run: agree, or override with the document and page relied on.
create table public.gate_reviews (
  id          bigint generated always as identity primary key,
  run_id      uuid not null references public.runs (id) on delete cascade,
  gate_id     text not null,
  reviewer_id text not null references public.reviewers (id),
  verdict     text not null check (verdict in ('agree', 'override')),
  result      text check (result in ('Pass', 'Fail', 'Incomplete')),
  reason      text not null check (length(btrim(reason)) > 0),
  document    text,
  page        integer check (page > 0),
  created_at  timestamptz not null default now(),
  check (verdict = 'agree' or (result is not null and document is not null and page is not null))
);
create index gate_reviews_run_idx on public.gate_reviews (run_id, gate_id, id desc);
alter table public.gate_reviews enable row level security;

-- An analyst's answer to a gate's manual check (custody, pricing). A "no" fails the gate.
create table public.gate_checks (
  id          bigint generated always as identity primary key,
  run_id      uuid not null references public.runs (id) on delete cascade,
  gate_id     text not null,
  check_id    text not null,
  ok          boolean not null,
  note        text,
  reviewer_id text not null references public.reviewers (id),
  created_at  timestamptz not null default now()
);
create index gate_checks_run_idx on public.gate_checks (run_id, gate_id, check_id, id desc);
alter table public.gate_checks enable row level security;
