#!/usr/bin/env python3
"""Put a local data root where a hosted console reads it: files in the private Storage bucket; rooms, page text
and the file list in the database (DATABASE_URL); each room's catalog built.

    uv run python scripts/upload_data_root.py <data-root>              # show the plan
    uv run python scripts/upload_data_root.py <data-root> --yes        # upload
    uv run python scripts/upload_data_root.py <data-root> --yes --db-only    # database only, no Storage

Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (in .env) unless --db-only. Re-running uploads only files that
are new or changed (by size and modified time), and each file is recorded as soon as it lands, so an
interrupted run picks up where it stopped. Catalogs are built here, from the files on disk, because the hosted
console has none. Files and rooms gone from the data root are dropped from the database; their Storage objects
are left in place and reported.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sg import db, storage  # noqa: E402
from sg.catalog import build as build_catalog  # noqa: E402
from sg.datasource import LocalSource  # noqa: E402


def scan(root):
    """{path under the root: (size, mtime)} for every file a console shows (no _index, nothing hidden)."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and "_index" not in rel.parts and not any(part.startswith(".") for part in rel.parts):
            st = p.stat()
            out[str(rel)] = (st.st_size, round(st.st_mtime, 3))
    return out


def known():
    with db.tx() as c:
        return {
            r["path"]: (r["size"], round(r["mtime"], 3)) for r in c.execute("select path, size, mtime from data_files")
        }


def record(path, size, mtime):
    with db.tx() as c:
        c.execute(
            """insert into data_files (path, object_key, size, mtime) values (%s, %s, %s, %s)
               on conflict (path) do update set object_key = excluded.object_key, size = excluded.size,
                 mtime = excluded.mtime""",
            (path, storage.object_key(path), size, mtime),
        )


def save_room(room, pages):
    with db.tx() as c:
        c.execute(
            "insert into data_rooms (room_id, name, path) values (%s, %s, %s) "
            "on conflict (room_id) do update set name = excluded.name, path = excluded.path",
            (room.id, room.name, room.path),
        )
        c.execute("delete from room_pages where room_id = %s", (room.id,))
        with c.cursor() as cur:
            cur.executemany(
                "insert into room_pages (room_id, file, page, chars, text) values (%s, %s, %s, %s, %s)",
                [(room.id, p["file"], p["page"], p.get("chars", len(p["text"])), p["text"]) for p in pages],
            )


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("data_root", type=Path)
    ap.add_argument("--yes", action="store_true", help="upload (default: show the plan only)")
    ap.add_argument("--db-only", action="store_true", help="fill the database but leave Storage alone")
    ap.add_argument("--skip-catalogs", action="store_true", help="do not build catalogs")
    a = ap.parse_args()
    root = a.data_root.resolve()
    src = LocalSource(root)
    rooms = src.rooms()
    files, have = scan(root), known()
    todo = [p for p, meta in files.items() if have.get(p) != meta]
    gone = sorted(set(have) - set(files))
    target = urlsplit(db.url())
    size = sum(files[p][0] for p in todo)
    print(f"database: {target.hostname}:{target.port}{target.path}")
    print(f"storage:  {'skipped (--db-only)' if a.db_only else f'bucket {storage.BUCKET}'}")
    print(f"rooms:    {len(rooms)} indexed, {sum(len(src.pages(r)) for r in rooms.values()):,} pages")
    print(
        f"files:    {len(todo)} to upload ({size / 1e6:,.0f} MB), {len(files) - len(todo)} unchanged, {len(gone)} gone"
    )
    if not a.yes:
        print("dry run; re-run with --yes to upload")
        return
    if not a.db_only:
        storage.ensure_bucket()
    t0, done = time.time(), 0
    for i, path in enumerate(todo, 1):
        if not a.db_only:
            storage.upload(storage.object_key(path), root / path)
        record(path, *files[path])
        done += files[path][0]
        print(f"  [{i}/{len(todo)}] {done / 1e6:,.0f} of {size / 1e6:,.0f} MB  {path}", flush=True)
    for room in rooms.values():
        save_room(room, src.pages(room))
    with db.tx() as c:
        c.execute("delete from data_files where path = any(%s)", (gone,))
        dropped = c.execute("delete from data_rooms where not (room_id = any(%s))", (list(rooms),)).rowcount
    if not a.skip_catalogs:
        for n, room in enumerate(rooms.values(), 1):
            print(f"  catalog {n}/{len(rooms)}: {room.name}", flush=True)
            build_catalog(src.folder(room))
    print(
        json.dumps(
            {
                "uploaded_files": len(todo),
                "rooms": len(rooms),
                "rooms_dropped": dropped,
                "files_dropped": len(gone),
                "seconds": round(time.time() - t0),
            }
        )
    )
    if gone and not a.db_only:
        print(f"{len(gone)} files left the data root; their objects stay in {storage.BUCKET} until deleted there.")


if __name__ == "__main__":
    main()
