-- The data root for a console with no disk of its own (Vercel). scripts/upload_data_root.py fills these from a
-- local data root and puts each file in the private Storage bucket "fund-files", keyed by a hash of its path
-- (object keys cannot hold every character a file name can). With RWP_DATA_SOURCE=hosted the console reads
-- rooms, page text and the file list here, and serves files through short-lived signed links.

create table public.data_rooms (
  room_id text primary key,                 -- data room slug, as runs.fund_id
  name    text not null,                    -- folder name, "Manager - Strategy"
  path    text not null                     -- folder path under the data root
);
alter table public.data_rooms enable row level security;

-- One row per indexed page: what _index/pages.jsonl holds on disk.
create table public.room_pages (
  room_id text not null references public.data_rooms (room_id) on delete cascade,
  file    text not null,                    -- path inside the room
  page    integer not null,
  chars   integer not null,
  text    text not null,
  primary key (room_id, file, page)
);
alter table public.room_pages enable row level security;

-- Every file under the data root, for the Files view and for finding a file's Storage object.
create table public.data_files (
  path       text primary key,              -- path under the data root
  object_key text not null,                 -- its object in the fund-files bucket
  size       bigint not null,
  mtime      double precision not null      -- epoch seconds, from the local copy it was uploaded from
);
alter table public.data_files enable row level security;
