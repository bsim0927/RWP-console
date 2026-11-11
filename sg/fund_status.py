"""Each fund's pipeline status (decision G3), kept in the database rather than PIPELINE.md.

Moving a fund's status is the CIO's alone, so a console change needs a CIO reviewer. Nothing is overwritten:
the newest row is the status and the older rows are its history. Rows imported once from PIPELINE.md carry no
reviewer and say so.
"""

from . import db, review

STATUSES = (
    "Not reviewed",
    "Triaged",
    "Under review",
    "Deep DD",
    "IC ready",
    "Covered",
    "Watch",
    "Reviewed and not covered",
)
DEFAULT = {"status": "Not reviewed", "reviewer": None, "source": None, "note": None, "at": None}

_SELECT = """
    select s.fund_id, s.status, p.name as reviewer, s.source, s.note,
           to_char(s.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as at
    from fund_status s left join reviewers p on p.id = s.reviewer_id"""


def current():
    """{fund_id: {status, reviewer, source, note, at}} for every fund with a status."""
    with db.tx() as c:
        rows = c.execute(f"{_SELECT} order by s.fund_id, s.id desc").fetchall()  # noqa: S608  constant
    out: dict = {}
    for r in rows:
        out.setdefault(r.pop("fund_id"), r)
    return out


def history(fund_id):
    """A fund's statuses, newest first."""
    with db.tx() as c:
        rows = c.execute(f"{_SELECT} where s.fund_id = %s order by s.id desc", (fund_id,)).fetchall()  # noqa: S608  constant
    for r in rows:
        r.pop("fund_id")
    return rows


def set_status(fund_id, status, reviewer_id, note=None):
    """Move a fund's status. Only an active CIO can."""
    if status not in STATUSES:
        raise review.ReviewError(f"status must be one of {', '.join(STATUSES)}")
    me = next((p for p in review.reviewers() if p["id"] == reviewer_id and p["active"]), None)
    if not me or me["role"] != "cio":
        raise review.ReviewError("only the CIO moves a fund's status")
    with db.tx() as c:
        c.execute(
            "insert into fund_status (fund_id, status, reviewer_id, source, note) values (%s, %s, %s, 'console', %s)",
            (fund_id, status, reviewer_id, str(note or "").strip() or None),
        )
    return history(fund_id)


def import_status(fund_id, status, note):
    """One status from the PIPELINE.md import. Skipped when the fund already has one."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    with db.tx() as c:
        if c.execute("select 1 from fund_status where fund_id = %s", (fund_id,)).fetchone():
            return False
        c.execute(
            "insert into fund_status (fund_id, status, source, note) values (%s, %s, 'import', %s)",
            (fund_id, status, note),
        )
    return True
