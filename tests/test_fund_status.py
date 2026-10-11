"""Pipeline status in the database (decision G3), and the one-time PIPELINE.md import."""

import importlib.util
import sys
from pathlib import Path

import psycopg
import pytest

from sg import fund_status, review, store
from sg.review import ReviewError

pytestmark = pytest.mark.usefixtures("db")

spec = importlib.util.spec_from_file_location(
    "import_pipeline_md", Path(__file__).parent.parent / "scripts" / "import_pipeline_md.py"
)
importer = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(importer)  # type: ignore[union-attr]

PIPELINE = """# Pipeline

Last updated: 2026-09-27

## Active

| Manager | Strategy | Status | Owner | Last action | Next action |
|---|---|---|---|---|---|
| Monroe Capital | ABF | **Deep DD** | Analyst A | Screened 2026-09-22 | Valuation policy |

## Intake, unscreened

| Manager | Strategy | Status | Owner | Material on file | Next action |
|---|---|---|---|---|---|
| Apollo | Fund XI | Not reviewed | unassigned | 2026-09-19 | Screen |
| Zeta Partners | Credit II | Not reviewed | Analyst B | – | Screen |
"""


def test_only_the_cio_moves_a_status_and_every_move_is_kept():
    assert fund_status.current() == {}
    review.save_reviewer({"id": "analyst_a", "name": "Analyst A", "role": "analyst"})
    with pytest.raises(ReviewError, match="only the CIO"):
        fund_status.set_status("f", "Deep DD", "analyst_a")
    with pytest.raises(ReviewError, match="status must be one of"):
        fund_status.set_status("f", "Promoted", "cio")
    fund_status.set_status("f", "Under review", "cio")
    hist = fund_status.set_status("f", "Deep DD", "cio", "Strong first screen")
    assert [(h["status"], h["reviewer"], h["source"], h["note"]) for h in hist] == [
        ("Deep DD", "CIO", "console", "Strong first screen"),
        ("Under review", "CIO", "console", None),
    ]
    assert fund_status.current()["f"]["status"] == "Deep DD"


def test_an_import_never_overwrites_a_status():
    assert fund_status.import_status("f", "Triaged", "from the file") is True
    assert fund_status.import_status("f", "Covered", "again") is False
    assert fund_status.current()["f"] == {
        "status": "Triaged",
        "reviewer": None,
        "source": "import",
        "note": "from the file",
        "at": fund_status.current()["f"]["at"],
    }


def test_a_console_status_must_name_its_reviewer_in_the_database_too(db):
    with psycopg.connect(db) as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute("insert into fund_status (fund_id, status, source) values ('f', 'Triaged', 'console')")


def test_the_import_matches_rows_to_rooms_and_keeps_rows_without_one(tmp_path, monkeypatch, capsys):
    root = tmp_path / "data"
    for name in ("Monroe Capital - ABF", "Apollo - Fund XI"):
        (root / name / "_index").mkdir(parents=True)
        (root / name / "_index" / "pages.jsonl").write_text("")
    src = tmp_path / "PIPELINE.md"
    src.write_text(PIPELINE)
    store.save_intake("Apollo_-_Fund_XI", {"owner": "Analyst C"})  # an owner already set is kept

    monkeypatch.setattr(sys, "argv", ["import", str(src), str(root)])
    importer.main()
    assert "dry run" in capsys.readouterr().out and fund_status.current() == {}

    monkeypatch.setattr(sys, "argv", ["import", str(src), str(root), "--yes"])
    importer.main()
    now = fund_status.current()
    assert {k: v["status"] for k, v in now.items()} == {
        "Monroe_Capital_-_ABF": "Deep DD",
        "Apollo_-_Fund_XI": "Not reviewed",
        "Zeta_Partners_-_Credit_II": "Not reviewed",  # no data room yet, kept under its own name
    }
    assert now["Monroe_Capital_-_ABF"]["note"] == (
        "Imported from PIPELINE.md (2026-09-27). Last action: Screened 2026-09-22; Next action: Valuation policy"
    )
    assert store.intake("Monroe_Capital_-_ABF")["owner"] == "Analyst A"
    assert store.intake("Apollo_-_Fund_XI")["owner"] == "Analyst C"
    assert store.intake("Zeta_Partners_-_Credit_II")["owner"] == "Analyst B"
    importer.main()  # re-running adds nothing
    assert len(fund_status.history("Monroe_Capital_-_ABF")) == 1
