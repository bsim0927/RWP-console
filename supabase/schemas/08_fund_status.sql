-- Each fund's pipeline status, kept here instead of PIPELINE.md (decision G3: moving it is the CIO's alone).
-- Append-only: the newest row is the status and older rows are its history. Rows imported once from
-- PIPELINE.md carry no reviewer; every console change names the CIO who made it.
create table public.fund_status (
  id          bigint generated always as identity primary key,
  fund_id     text not null,                 -- data room folder slug, as runs.fund_id
  status      text not null check (status in ('Not reviewed', 'Triaged', 'Under review', 'Deep DD', 'IC ready',
                                              'Covered', 'Watch', 'Reviewed and not covered')),
  reviewer_id text references public.reviewers (id),
  source      text not null check (source in ('import', 'console')),
  note        text,
  created_at  timestamptz not null default now(),
  check (source = 'import' or reviewer_id is not null)
);
create index fund_status_fund_idx on public.fund_status (fund_id, id desc);
alter table public.fund_status enable row level security;
