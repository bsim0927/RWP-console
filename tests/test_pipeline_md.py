"""PIPELINE.md: reading the table and writing a fund's results into its row (decision G3)."""

import pytest

from sg import pipeline_md

TABLE = """# RWP Alternatives Pipeline

Last updated: 2026-10-01

## Active

| Manager | Strategy | Status | Owner | Last action | Next action |
|---|---|---|---|---|---|
| Northwind Capital | Private Credit Fund I | **Under review** | Analyst A | Screened 2026-09-30 | Confirm hurdle |
| Acme Partners | Real Estate Opportunity Fund II | **Triaged** | Analyst B | Extraction complete | Screen |

Notes the CIO keeps by hand.
"""
ACME = "Acme Partners - Real Estate Opportunity Fund II"


def test_only_the_funds_row_and_the_date_change():
    new, written = pipeline_md.update(
        TABLE, ACME, {"Last action": "Screened 2026-10-11: Under review (draft)", "Owner": "Analyst B"}, "2026-10-11"
    )
    assert written == ["Last action"]  # Owner already matched
    assert new == TABLE.replace(
        "| Acme Partners | Real Estate Opportunity Fund II | **Triaged** | Analyst B | Extraction complete | Screen |",
        "| Acme Partners | Real Estate Opportunity Fund II | **Triaged** | Analyst B | Screened 2026-10-11: Under review (draft) | Screen |",
    ).replace("Last updated: 2026-10-01", "Last updated: 2026-10-11")


def test_status_is_never_written():
    with pytest.raises(ValueError, match="never writes Status"):
        pipeline_md.update(TABLE, ACME, {"Status": "Covered"}, "2026-10-11")


def test_columns_the_table_lacks_are_skipped_and_pipes_escaped():
    new, written = pipeline_md.update(
        TABLE, ACME, {"Referred by": "Adviser", "Next action": "Ask for a | b"}, "2026-10-11"
    )
    assert written == ["Next action"] and "| Ask for a / b |" in new


def test_no_matching_row_or_nothing_new_leaves_the_file_alone():
    assert pipeline_md.update(TABLE, "Zeta Fund - Credit", {"Owner": "X"}, "2026-10-11") == (TABLE, [])
    assert pipeline_md.update(TABLE, ACME, {"Owner": "Analyst B", "Next action": None}, "2026-10-11") == (TABLE, [])


def test_write_keeps_windows_line_endings(tmp_path):
    path = tmp_path / "PIPELINE.md"
    path.write_bytes(TABLE.replace("\n", "\r\n").encode())
    assert pipeline_md.write(path, ACME, {"Next action": "CIO sign-off"}, "2026-10-11") == ["Next action"]
    raw = path.read_bytes().decode()
    assert "\n" not in raw.replace("\r\n", "") and "| CIO sign-off |\r\n" in raw
    assert list(tmp_path.iterdir()) == [path]  # the temporary file was moved into place


def test_parse_and_match_read_the_table_as_before():
    parsed = pipeline_md.parse(TABLE)
    assert parsed["updated"] == "2026-10-01"
    rows = parsed["sections"][0]["rows"]
    assert rows[0]["Status"] == "Under review"  # bold stripped
    assert pipeline_md.match("Northwind Capital - Private Credit Fund I", rows) is rows[0]
