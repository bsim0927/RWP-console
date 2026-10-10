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
