-- The one-page screen note (decisions F1, F4). The tool drafts it; the analyst edits it. Append-only: each
-- draft or edit is a new version and the newest is the note.
create table public.screen_notes (
  id          bigint generated always as identity primary key,
  run_id      uuid not null references public.runs (id) on delete cascade,
  body        text not null,
  author      text not null check (author in ('tool', 'analyst')),
  reviewer_id text references public.reviewers (id),   -- who edited it, for an analyst version
  model       text,                                    -- the model that wrote the summary, for a tool draft
  created_at  timestamptz not null default now(),
  check (author = 'tool' or reviewer_id is not null)
);
create index screen_notes_run_idx on public.screen_notes (run_id, id desc);
alter table public.screen_notes enable row level security;
