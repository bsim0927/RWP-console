-- Confirming a run's disposition (decision F5). Every disposition is a draft until an analyst confirms it, and
-- "Reviewed and not covered" also needs the CIO's sign-off. Append-only: the newest row is in force. Each row
-- keeps the disposition it confirmed, so a later gate review that changes the disposition reopens the draft.
create table public.disposition_confirmations (
  id          bigint generated always as identity primary key,
  run_id      uuid not null references public.runs (id) on delete cascade,
  disposition text not null,
  reviewer_id text not null references public.reviewers (id),
  sign_off    boolean not null default false,  -- the CIO signing off a "not covered"
  reason      text,
  created_at  timestamptz not null default now()
);
create index disposition_confirmations_run_idx on public.disposition_confirmations (run_id, id desc);
alter table public.disposition_confirmations enable row level security;
