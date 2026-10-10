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
