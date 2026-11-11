"""scripts/reorganize_data_root.py: a Drive download becomes one folder per fund, fund documents only."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "reorganize_data_root", Path(__file__).parent.parent / "scripts" / "reorganize_data_root.py"
)
reorg = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(reorg)  # type: ignore[union-attr]


def put(root, rel, text="x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture
def download(tmp_path):
    dl = tmp_path / "RWP"
    one, two = dl / "RWP-20261006T224806Z-1-001" / "RWP", dl / "RWP-20261006T224806Z-1-002" / "RWP"
    put(one, "PIPELINE.md")
    put(one, "1-Intake/Acme - Fund I/01 Inbound/PPM.pdf")
    put(one, "1-Intake/Acme - Fund I/00 Deal Record.md")
    put(one, "1-Intake/Acme - Fund I/_index/pages.jsonl", "")
    put(two, "1-Intake/Acme - Fund I/01 Inbound/Deck.pdf")  # the same fund, split across parts
    put(two, "1-Intake/Zeta - Credit II/Teaser.pdf")  # a fund not yet indexed
    put(one, "1-Intake/_inbox/arrivals.md")
    put(one, "1-Intake/Notes Only - Fund/03 Diligence/Screen.md")
    put(one, "2-Managers/Monroe - ABF/03 Diligence/Model.xlsx")
    put(one, "2-Managers/Monroe - ABF/_index/pages.jsonl", "")
    put(one, "6-Research/Private Credit/Paper.pdf")  # firm research: no indexed room in this stage
    put(one, "3-Process/Hub/README.md")
    return dl


def run(*argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["reorganize", *map(str, argv)])
    reorg.main()


def test_only_fund_documents_are_copied_into_one_folder_per_fund(download, tmp_path, monkeypatch, capsys):
    dest = tmp_path / "funds"
    run(download, dest, monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "funds: 3 with documents (2 with a page index); 1 hold only notes" in out and "dry run" in out
    assert not dest.exists()

    run(download, dest, "--yes", monkeypatch=monkeypatch)
    got = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    assert got == [
        "Acme - Fund I/01 Inbound/Deck.pdf",
        "Acme - Fund I/01 Inbound/PPM.pdf",
        "Acme - Fund I/_index/pages.jsonl",
        "Monroe - ABF/03 Diligence/Model.xlsx",
        "Monroe - ABF/_index/pages.jsonl",
        "Zeta - Credit II/Teaser.pdf",
    ]
    assert list((download).rglob("*.md"))  # the download itself is untouched


def test_a_file_that_differs_between_parts_is_reported_and_the_first_kept(download, tmp_path, monkeypatch, capsys):
    put(download / "RWP-20261006T224806Z-1-002" / "RWP", "1-Intake/Acme - Fund I/01 Inbound/PPM.pdf", "other")
    run(download, tmp_path / "funds", "--yes", monkeypatch=monkeypatch)
    assert "01 Inbound/PPM.pdf: differs between download parts" in capsys.readouterr().out
    assert (tmp_path / "funds" / "Acme - Fund I" / "01 Inbound" / "PPM.pdf").read_text() == "x"


def test_it_refuses_a_destination_that_is_not_empty(download, tmp_path, monkeypatch):
    put(tmp_path, "funds/keep.txt")
    with pytest.raises(SystemExit, match="not empty"):
        run(download, tmp_path / "funds", monkeypatch=monkeypatch)


def test_an_index_that_names_a_file_before_drive_renamed_it_is_repointed(download, tmp_path, monkeypatch, capsys):
    one = download / "RWP-20261006T224806Z-1-001" / "RWP"
    put(one, "1-Intake/Acme - Fund I/01 Inbound/Fall _26 Deck.pdf")
    put(
        one,
        "1-Intake/Acme - Fund I/_index/pages.jsonl",
        '{"file": "01 Inbound/Fall \'26 Deck.pdf", "page": 1}\n{"file": "01 Inbound/PPM.pdf", "page": 1}\n',
    )
    run(download, tmp_path / "funds", "--yes", monkeypatch=monkeypatch)
    assert "1 indexed pages repointed" in capsys.readouterr().out
    idx = (tmp_path / "funds" / "Acme - Fund I" / "_index" / "pages.jsonl").read_text().splitlines()
    assert [json.loads(x)["file"] for x in idx] == ["01 Inbound/Fall _26 Deck.pdf", "01 Inbound/PPM.pdf"]
