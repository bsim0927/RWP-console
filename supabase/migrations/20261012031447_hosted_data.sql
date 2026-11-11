-- The data root in the database and Storage, for a console with no disk (Vercel port).
CREATE TABLE "public"."data_files" (
  "path"       text             NOT NULL,
  "object_key" text             NOT NULL,
  "size"       bigint           NOT NULL,
  "mtime"      double precision NOT NULL,
  CONSTRAINT "data_files_pkey" PRIMARY KEY (path)
);

ALTER TABLE "public"."data_files"
  ENABLE ROW LEVEL SECURITY;

CREATE TABLE "public"."data_rooms" (
  "room_id" text NOT NULL,
  "name"    text NOT NULL,
  "path"    text NOT NULL,
  CONSTRAINT "data_rooms_pkey" PRIMARY KEY (room_id)
);

ALTER TABLE "public"."data_rooms"
  ENABLE ROW LEVEL SECURITY;

CREATE TABLE "public"."room_pages" (
  "room_id" text    NOT NULL,
  "file"    text    NOT NULL,
  "page"    integer NOT NULL,
  "chars"   integer NOT NULL,
  "text"    text    NOT NULL,
  CONSTRAINT "room_pages_pkey" PRIMARY KEY (room_id, file, page)
);

ALTER TABLE "public"."room_pages"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."room_pages"
  ADD CONSTRAINT "room_pages_room_id_fkey" FOREIGN KEY (room_id) REFERENCES public.data_rooms(room_id) ON DELETE CASCADE;
