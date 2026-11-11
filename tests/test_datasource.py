"""The hosted data source (database + Storage) answers exactly as the local one (disk) does."""

import io
import json
import time

import pytest

from sg import storage
from sg.datasource import HostedSource, LocalSource, slug

pytestmark = pytest.mark.usefixtures("db")

PPM = "01 Inbound/Monroe Capital OpCo - PPM.pdf"
ROWS = [
    {"file": PPM, "page": 1, "chars": 9, "text": "PRIVATE PLACEMENT MEMORANDUM\nMonroe Capital ABF OpCo"},
    {
        "file": PPM,
        "page": 64,
        "chars": 9,
        "text": "A purchase of our Shares is appropriate only for accredited investors.",
    },
    {"file": "01 Inbound/Dataroom/Term Sheet 50%_off.pdf", "page": 2, "chars": 9, "text": "Minimum purchase: $10,000."},
]


@pytest.fixture
def both(tmp_path):
    """The same data root on disk and in the database, as the upload script leaves it."""
    room = tmp_path / "Monroe Capital - ABF"
    (room / "_index").mkdir(parents=True)
    (room / "_index" / "pages.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ROWS))
    for rel in {r["file"] for r in ROWS} | {"03 Diligence/Model.xlsx"}:
        (room / rel).parent.mkdir(parents=True, exist_ok=True)
        (room / rel).write_text("x")
    (tmp_path / "Zeta - Credit II").mkdir()
    (tmp_path / "Zeta - Credit II" / "Teaser.pdf").write_text("xy")
    from sg import db

    with db.tx() as c:
        c.execute("insert into data_rooms values (%s, %s, %s)", (slug(room.name), room.name, room.name))
        for r in ROWS:
            c.execute(
                "insert into room_pages values (%s, %s, %s, %s, %s)",
                (slug(room.name), r["file"], r["page"], r["chars"], r["text"]),
            )
        for p in tmp_path.rglob("*"):
            if p.is_file() and "_index" not in p.parts:
                rel = str(p.relative_to(tmp_path))
                c.execute(
                    "insert into data_files values (%s, %s, %s, %s)",
                    (rel, storage.object_key(rel), p.stat().st_size, p.stat().st_mtime),
                )
    return LocalSource(tmp_path), HostedSource()


def test_rooms_and_pages_match(both):
    local, hosted = both
    assert local.rooms() == hosted.rooms()
    room = next(iter(hosted.rooms().values()))
    assert [dict(p) for p in hosted.pages(room)] == sorted(local.pages(room), key=lambda p: (p["file"], p["page"]))
    assert hosted.data_room(room).by_key.keys() == local.data_room(room).by_key.keys()
    assert hosted.folder(room) is None and local.folder(room).is_dir()


@pytest.mark.parametrize(
    "q", ["Monroe Capital OpCo - PPM.pdf", "opco ppm", "inbound", "accredited", "PPM term", "50%", "purchase", "x"]
)
def test_search_matches(both, q):
    local, hosted = both
    assert hosted.search(q) == local.search(q)
    assert hosted.search(q, only="nope") == local.search(q, only="nope") == []


@pytest.mark.parametrize(
    "v", ["", "Monroe Capital - ABF", "Monroe Capital - ABF/01 Inbound", "Zeta - Credit II", "nowhere"]
)
def test_listings_match_apart_from_folder_dates(both, v):
    local, hosted = both
    a, b = local.listing(v), hosted.listing(v)
    if a is None:
        assert b is None
        return
    strip = lambda es: [
        {k: e[k] for k in ("name", "dir", "path", "room")} | ({} if e["dir"] else {"size": e["size"]}) for e in es
    ]
    assert strip(a) == strip(b)


def test_a_hosted_file_is_a_signed_link(both, monkeypatch):
    _, hosted = both
    monkeypatch.setattr(storage, "signed_url", lambda key, seconds=3600: f"https://x.supabase.co/signed/{key}")
    kind, url = hosted.file("Zeta - Credit II/Teaser.pdf")
    assert kind == "url" and url == f"https://x.supabase.co/signed/{storage.object_key('Zeta - Credit II/Teaser.pdf')}"
    assert hosted.file("Zeta - Credit II/missing.pdf") is None


class FakeStorage:
    """Answers Storage's REST calls the way the docs describe, recording each one."""

    def __init__(self):
        self.calls = []
        self.offset = 0

    def __call__(self, req, timeout):
        url, method = req.full_url, req.get_method()
        self.calls.append((method, url, dict(req.header_items())))
        if url.endswith("/storage/v1/upload/resumable"):
            return self.reply(201, {"Location": "https://ref.storage.supabase.co/storage/v1/upload/resumable/abc"})
        if method == "PATCH":
            self.offset += len(req.data)
            return self.reply(204, {"Upload-Offset": str(self.offset)})
        if "/object/sign/" in url:
            return self.reply(200, body={"signedURL": "/object/sign/fund-files/k.pdf?token=t"})
        return self.reply(200, body={"Key": "fund-files/k"})

    def reply(self, status, headers=None, body=None):
        return Reply(status, headers or {}, json.dumps(body or {}).encode())


class Reply(io.BytesIO):
    """What urlopen returns: a readable body with a status and headers, usable in a with-block."""

    def __init__(self, status, headers, body):
        super().__init__(body)
        self.status, self.headers = status, headers


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret")
    f = FakeStorage()
    monkeypatch.setattr(storage.urllib.request, "urlopen", f)
    return f


def test_small_files_upload_in_one_request_and_large_ones_in_six_megabyte_chunks(fake, tmp_path, monkeypatch):
    small, big = tmp_path / "a.pdf", tmp_path / "b.pdf"
    small.write_bytes(b"x" * 10)
    big.write_bytes(b"y" * (2 * storage.CHUNK + 5))
    storage.upload("k1.pdf", small)
    assert [(m, u) for m, u, _ in fake.calls] == [
        ("POST", "https://ref.supabase.co/storage/v1/object/fund-files/k1.pdf")
    ]
    fake.calls.clear()
    storage.upload("k2.pdf", big)
    assert [m for m, _, _ in fake.calls] == ["POST", "PATCH", "PATCH", "PATCH"]
    assert fake.calls[0][1] == "https://ref.storage.supabase.co/storage/v1/upload/resumable"
    assert fake.offset == big.stat().st_size


def test_signed_links_are_absolute_and_only_https_is_spoken(fake, monkeypatch):
    assert storage.signed_url("k.pdf") == "https://ref.supabase.co/storage/v1/object/sign/fund-files/k.pdf?token=t"
    monkeypatch.setenv("SUPABASE_URL", "http://ref.supabase.co")
    with pytest.raises(storage.StorageError, match="non-https"):
        storage.signed_url("k.pdf")


def test_object_keys_are_safe_for_any_file_name():
    k = storage.object_key("F and FC - Fund IV/Cyera’s Role.PDF")
    assert k.endswith(".pdf") and k.isascii() and "/" not in k and len(k) == 44
    assert time.time()  # keeps the import list honest
