"""scripts/upload_data_root.py, database side (--db-only): rooms, pages and the file list, re-runs and removals."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from sg import db
from sg.datasource import HostedSource

pytestmark = pytest.mark.usefixtures("db")

spec = importlib.util.spec_from_file_location(
    "upload_data_root", Path(__file__).parent.parent / "scripts" / "upload_data_root.py"
)
upload = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(upload)  # type: ignore[union-attr]


def run(*argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["upload", *map(str, argv)])
    upload.main()


def test_a_data_root_lands_in_the_database_and_reruns_only_send_changes(tmp_path, monkeypatch, capsys):
    room = tmp_path / "Acme - Fund I"
    (room / "_index").mkdir(parents=True)
    (room / "_index" / "pages.jsonl").write_text(
        json.dumps({"file": "PPM.pdf", "page": 1, "chars": 4, "text": "Fees"}) + "\n"
    )
    (room / "PPM.pdf").write_text("pdf")
    (tmp_path / "Zeta - Credit II").mkdir()
    (tmp_path / "Zeta - Credit II" / "Teaser.pdf").write_text("teaser")
    (tmp_path / ".DS_Store").write_text("junk")

    run(tmp_path, monkeypatch=monkeypatch)
    assert "files:    2 to upload" in capsys.readouterr().out and HostedSource().rooms() == {}

    run(tmp_path, "--yes", "--db-only", "--skip-catalogs", monkeypatch=monkeypatch)
    hosted = HostedSource()
    assert list(hosted.rooms()) == ["Acme_-_Fund_I"]
    assert [p["text"] for p in hosted.pages(hosted.rooms()["Acme_-_Fund_I"])] == ["Fees"]
    assert [e["name"] for e in hosted.listing("")] == ["Acme - Fund I", "Zeta - Credit II"]

    capsys.readouterr()
    run(tmp_path, "--yes", "--db-only", "--skip-catalogs", monkeypatch=monkeypatch)
    assert "files:    0 to upload (0 MB), 2 unchanged, 0 gone" in capsys.readouterr().out

    (tmp_path / "Zeta - Credit II" / "Teaser.pdf").unlink()
    run(tmp_path, "--yes", "--db-only", "--skip-catalogs", monkeypatch=monkeypatch)
    with db.tx() as c:
        assert [r["path"] for r in c.execute("select path from data_files")] == ["Acme - Fund I/PPM.pdf"]
