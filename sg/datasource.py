"""Where the fund data comes from: a data root on disk, or the database and Supabase Storage when hosted.

RWP_DATA_SOURCE picks one. "local" (the default) reads the data root: one folder per fund, each indexed room
with its _index/pages.jsonl. "hosted" reads what scripts/upload_data_root.py put in the database (rooms, page
text, the file list) and serves files through short-lived signed links to the private Storage bucket, for a
console with no disk of its own (Vercel). Both answer the same questions in the same shapes, so the server and
the pipeline never ask which one they have.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import db, storage
from .dataroom import DataRoom

slug = lambda n: re.sub(r"[^\w.-]+", "_", n)  # a room's id, as runs.fund_id


@dataclass(frozen=True)
class Room:
    id: str
    name: str  # folder name, "Manager - Strategy"
    path: str  # folder path under the data root


def terms_of(q):
    return [t for t in re.findall(r"\w+", q.lower()) if len(t) > 1]


def _named(room, p):
    """A hit on the file's name or path: evidence cites files by name, words that rarely appear on the page."""
    return {
        "fund": room.id,
        "room": room.name,
        "file": p["file"],
        "page": p["page"],
        "path": f"{room.path}/{p['file']}",
        "snippet": re.sub(r"\s+", " ", p["text"][:320]).strip(),
        "score": 0,
        "by_name": True,
    }


def _hit(room, p, terms):
    t = p["text"].lower()
    i = t.find(terms[0])
    return {
        "fund": room.id,
        "room": room.name,
        "file": p["file"],
        "page": p["page"],
        "path": f"{room.path}/{p['file']}",
        "snippet": re.sub(r"\s+", " ", p["text"][max(0, i - 120) : i + 200]).strip(),
        "score": sum(t.count(term) for term in terms),
    }


def _ranked(named, hits, limit):
    """Name matches first, then pages by score; ties in a fixed order, so both sources answer alike."""
    named.sort(key=lambda r: (r["room"], r["file"]))
    hits.sort(key=lambda r: (-r["score"], r["room"], r["file"], r["page"]))
    return (named + hits)[:limit]


class LocalSource:
    """The data root on this machine."""

    def __init__(self, root):
        self.root = Path(root)
        self.label = str(self.root)
        self._pages: dict[Path, tuple[float, list[dict]]] = {}

    def rooms(self):
        """{room id: Room} for every indexed folder."""
        out = {}
        for idx in self.root.rglob("_index/pages.jsonl"):
            folder = idx.parent.parent
            out[slug(folder.name)] = Room(slug(folder.name), folder.name, str(folder.relative_to(self.root)))
        return out

    def folder(self, room):
        return self.root / room.path

    def pages(self, room):
        idx = self.folder(room) / "_index" / "pages.jsonl"
        m = idx.stat().st_mtime
        hit = self._pages.get(idx)
        if not hit or hit[0] != m:
            hit = (m, [json.loads(line) for line in idx.open()])
            self._pages[idx] = hit
        return hit[1]

    def data_room(self, room):
        return DataRoom(self.folder(room))

    def _inside(self, p):
        try:
            return p.resolve().is_relative_to(self.root.resolve())
        except OSError:
            return False

    def listing(self, v):
        """The entries of folder v (relative to the data root), folders first, or None if it is not one."""
        d = self.root / v
        if not self._inside(d) or not d.is_dir():
            return None
        out = []
        for c in d.iterdir():
            if c.name.startswith(".") or c.name == "_index":
                continue
            st = c.stat()
            path = f"{v}/{c.name}" if v else c.name
            out.append(
                {
                    "name": c.name,
                    "dir": c.is_dir(),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "path": path,
                    "real": path,
                    "room": c.is_dir() and (c / "_index" / "pages.jsonl").exists(),
                }
            )
        return sorted(out, key=lambda e: (not e["dir"], e["name"].lower()))

    def file(self, path):
        """("path", the file on disk), or None."""
        p = self.root / path.lstrip("/")
        return ("path", p) if self._inside(p) and p.is_file() else None

    def search(self, q, only=None, limit=80):
        terms = terms_of(q)
        if not terms:
            return []
        named, hits = [], []
        for room in self.rooms().values():
            if only and room.id != only:
                continue
            pages = self.pages(room)
            firsts: dict[str, dict] = {}
            for p in pages:
                firsts.setdefault(p["file"], p)
            named += [_named(room, p) for rel, p in firsts.items() if all(term in rel.lower() for term in terms)]
            hits += [_hit(room, p, terms) for p in pages if all(term in p["text"].lower() for term in terms)]
        return _ranked(named, hits, limit)


def _like(terms):
    """ILIKE patterns that match each term literally."""
    return ["%" + re.sub(r"([%_\\])", r"\\\1", t) + "%" for t in terms]


class HostedSource:
    """The database and the Storage bucket that scripts/upload_data_root.py filled."""

    label = f"Supabase Storage (bucket {storage.BUCKET})"

    def rooms(self):
        with db.tx() as c:
            rows = c.execute("select room_id, name, path from data_rooms order by name").fetchall()
        return {r["room_id"]: Room(r["room_id"], r["name"], r["path"]) for r in rows}

    def folder(self, room):
        return None  # no disk: catalogs are built by the upload script

    def pages(self, room):
        with db.tx() as c:
            return c.execute(
                "select file, page, chars, text from room_pages where room_id = %s order by file, page", (room.id,)
            ).fetchall()

    def data_room(self, room):
        return DataRoom(name=room.name, pages=self.pages(room))

    def listing(self, v):
        prefix = f"{v}/" if v else ""
        with db.tx() as c:
            files = c.execute(
                "select path, size, mtime from data_files where path like %s escape '\\' order by path",
                (re.sub(r"([%_\\])", r"\\\1", prefix) + "%",),
            ).fetchall()
            rooms = {r["path"] for r in c.execute("select path from data_rooms").fetchall()}
        if v and not files:
            return None
        entries: dict[str, dict] = {}
        for f in files:
            name, _, rest = f["path"][len(prefix) :].partition("/")
            path = prefix + name
            e = entries.setdefault(
                name,
                {
                    "name": name,
                    "dir": bool(rest),
                    "size": 0,
                    "mtime": 0.0,
                    "path": path,
                    "real": path,
                    "room": path in rooms,
                },
            )
            e["size"] += f["size"]
            e["mtime"] = max(e["mtime"], f["mtime"])
        return sorted(entries.values(), key=lambda e: (not e["dir"], e["name"].lower()))

    def file(self, path):
        """("url", a signed link to the file), or None."""
        with db.tx() as c:
            row = c.execute("select object_key from data_files where path = %s", (path.lstrip("/"),)).fetchone()
        return ("url", storage.signed_url(row["object_key"])) if row else None

    def search(self, q, only=None, limit=80):
        terms = terms_of(q)
        if not terms:
            return []
        rooms = self.rooms()
        with db.tx() as c:
            named_rows = c.execute(
                """select distinct on (room_id, file) room_id, file, page, text from room_pages
                   where file ilike all(%s) and (%s::text is null or room_id = %s) order by room_id, file, page""",
                (_like(terms), only, only),
            ).fetchall()
            # Rank in the database by the same count the local source makes (non-overlapping occurrences of
            # each term), so the cut to `limit` keeps the same pages.
            hit_rows = c.execute(
                """select p.room_id, p.file, p.page, p.text from room_pages p join data_rooms r using (room_id)
                   where p.text ilike all(%(like)s) and (%(only)s::text is null or p.room_id = %(only)s)
                   order by (select sum((length(lower(p.text)) - length(replace(lower(p.text), t, ''))) / length(t))
                             from unnest(%(terms)s::text[]) t) desc, r.name, p.file, p.page
                   limit %(limit)s""",
                {"like": _like(terms), "only": only, "terms": terms, "limit": limit},
            ).fetchall()
        named = [_named(rooms[r["room_id"]], r) for r in named_rows if r["room_id"] in rooms]
        hits = [_hit(rooms[r["room_id"]], r, terms) for r in hit_rows if r["room_id"] in rooms]
        return _ranked(named, hits, limit)


def source(root):
    """The data source RWP_DATA_SOURCE names; `root` is the data root a local source reads."""
    mode = os.environ.get("RWP_DATA_SOURCE", "local")
    if mode == "hosted":
        return HostedSource()
    if mode != "local":
        raise SystemExit(f"RWP_DATA_SOURCE must be local or hosted, not {mode!r}")
    return LocalSource(root)
