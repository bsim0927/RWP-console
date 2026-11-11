-- What the analyst records when a fund is filed (decisions F2, B5, G4). One row per data room.
-- The screen clock runs five business days from filed_on.

create table public.intake (
  fund_id          text primary key,         -- data room folder slug, as runs.fund_id
  referred_by      text,
  owner            text,
  sponsor_deadline date,
  filed_on         date,
  share_class      text,                     -- the class RWP screens; the cost total is for this class
  updated_at       timestamptz not null default now()
);
alter table public.intake enable row level security;
