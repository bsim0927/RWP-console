"""Analyst review of a screen run (decisions G1, G2, C3, C4).

A reviewer agrees with a gate or overrides its result, always with a one-line reason; an override also names
the document and page it relies on. A gate may carry manual checks (custody, pricing) that only the analyst
answers, and a "no" fails the gate. Nothing is overwritten: the newest review or answer is in force and the
older ones are its history. The pipeline's own result stays in the run record, untouched.
"""

import re

from . import db
from .gate_store import RESULTS

ROLES = ("analyst", "cio")


class ReviewError(ValueError):
    pass


# ---------- reviewers ----------


def reviewers():
    with db.tx() as c:
        return c.execute("select id, name, role, active from reviewers order by role = 'cio' desc, name").fetchall()


def save_reviewer(body):
    """Add a reviewer, or rename, re-role or (de)activate one. A new reviewer's id comes from the name."""
    name = str(body.get("name") or "").strip()
    rid = body.get("id") or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not name or not re.match(r"^[a-z][a-z0-9_]{1,30}$", rid or ""):
        raise ReviewError("a reviewer needs a name that starts with a letter")
    role = body.get("role", "analyst")
    if role not in ROLES:
        raise ReviewError(f"role must be one of {', '.join(ROLES)}")
    with db.tx() as c:
        c.execute(
            """insert into reviewers (id, name, role, active) values (%s, %s, %s, %s)
               on conflict (id) do update set name = excluded.name, role = excluded.role, active = excluded.active""",
            (rid, name, role, bool(body.get("active", True))),
        )
    return next(r for r in reviewers() if r["id"] == rid)


def _reviewer(c, rid):
    row = c.execute("select id, active from reviewers where id = %s", (rid,)).fetchone()
    if not row or not row["active"]:
        raise ReviewError("choose an active reviewer")


# ---------- reviews and checks ----------


def _gate(c, fund_id, stamp, gate_id):
    """(run id, the gate's run record) or a ReviewError."""
    row = c.execute(
        """select r.id, g.record from runs r join run_gates g on g.run_id = r.id
           where r.fund_id = %s and r.stamp = %s and g.gate_id = %s""",
        (fund_id, stamp, gate_id),
    ).fetchone()
    if not row:
        raise ReviewError(f"no gate {gate_id} in run {fund_id}/{stamp}")
    return row["id"], row["record"]


def add_review(fund_id, stamp, gate_id, reviewer_id, verdict, reason, result=None, document=None, page=None):
    reason = str(reason or "").strip()
    if verdict not in ("agree", "override"):
        raise ReviewError("verdict must be agree or override")
    if not reason:
        raise ReviewError("give a one-line reason")
    if verdict == "override":
        if result not in RESULTS:
            raise ReviewError(f"an override sets the result to {', '.join(RESULTS)}")
        if not str(document or "").strip() or not str(page or "").isdigit() or int(page) < 1:
            raise ReviewError("an override names the document and page it relies on")
    else:
        result = document = page = None
    with db.tx() as c:
        _reviewer(c, reviewer_id)
        run_id, _ = _gate(c, fund_id, stamp, gate_id)
        c.execute(
            """insert into gate_reviews (run_id, gate_id, reviewer_id, verdict, result, reason, document, page)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (run_id, gate_id, reviewer_id, verdict, result, reason, document and document.strip(), page and int(page)),
        )
    return for_run(fund_id, stamp)


def add_check(fund_id, stamp, gate_id, check_id, ok, reviewer_id, note=None):
    if not isinstance(ok, bool):
        raise ReviewError("answer the check yes or no")
    with db.tx() as c:
        _reviewer(c, reviewer_id)
        run_id, record = _gate(c, fund_id, stamp, gate_id)
        if check_id not in {k["id"] for k in record.get("checks") or []}:
            raise ReviewError(f"gate {gate_id} has no manual check {check_id} in this run")
        c.execute(
            """insert into gate_checks (run_id, gate_id, check_id, ok, note, reviewer_id)
               values (%s, %s, %s, %s, %s, %s)""",
            (run_id, gate_id, check_id, ok, str(note or "").strip() or None, reviewer_id),
        )
    return for_run(fund_id, stamp)


_REVIEWS = """
    select v.run_id, v.gate_id, v.reviewer_id, p.name as reviewer, v.verdict, v.result, v.reason, v.document,
           v.page, to_char(v.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as at
    from gate_reviews v join reviewers p on p.id = v.reviewer_id
    where v.run_id = any(%s) order by v.id desc"""
_CHECKS = """
    select k.run_id, k.gate_id, k.check_id, k.ok, k.note, k.reviewer_id, p.name as reviewer,
           to_char(k.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as at
    from gate_checks k join reviewers p on p.id = k.reviewer_id
    where k.run_id = any(%s) order by k.id desc"""


def _by_run(c, run_ids):
    """{run_id: {gate_id: {"reviews": [newest first], "checks": {check_id: [newest first]}}}}"""
    out: dict = {}
    blank = lambda r: out.setdefault(r.pop("run_id"), {}).setdefault(r["gate_id"], {"reviews": [], "checks": {}})
    for r in c.execute(_REVIEWS, (list(run_ids),)).fetchall():
        blank(r)["reviews"].append(r)
    for r in c.execute(_CHECKS, (list(run_ids),)).fetchall():
        blank(r)["checks"].setdefault(r["check_id"], []).append(r)
    return out


def effective(record, review=None):
    """The gate after the analyst. An override sets the result; otherwise a "no" on any manual check fails
    the gate; otherwise the pipeline's result stands. A reviewed gate no longer waits on analyst review."""
    review = review or {}
    latest = (review.get("reviews") or [None])[0]
    answers = {k: hist[0] for k, hist in (review.get("checks") or {}).items()}
    failed = [k for k, a in answers.items() if not a["ok"]]
    if latest and latest["verdict"] == "override":
        result, source = latest["result"], "override"
    elif failed:
        result, source = "Fail", "check"
    else:
        result, source = record["result"], "pipeline"
    return {
        "result": result,
        "source": source,
        "pipeline_result": record["result"],
        "reviewed": latest is not None,
        "needs_review": bool(record.get("review")) and latest is None,
        "review": latest,
        "history": review.get("reviews") or [],
        "checks": answers,
        "check_history": review.get("checks") or {},
        "pending_checks": [k["id"] for k in record.get("checks") or [] if k["id"] not in answers],
        "failed_checks": failed,
    }


def for_run(fund_id, stamp):
    """{gate_id: effective(...)} for one run, in pipeline order."""
    with db.tx() as c:
        head = c.execute("select id from runs where fund_id = %s and stamp = %s", (fund_id, stamp)).fetchone()
        if not head:
            raise ReviewError(f"no run {fund_id}/{stamp}")
        gates = c.execute(
            "select gate_id, record from run_gates where run_id = %s order by position", (head["id"],)
        ).fetchall()
        rv = _by_run(c, [head["id"]]).get(head["id"], {})
    return {g["gate_id"]: effective(g["record"], rv.get(g["gate_id"])) for g in gates}


def latest_by_fund():
    """{fund_id: {gate_id: effective(...)}} for each fund's newest run, in two queries."""
    with db.tx() as c:
        rows = c.execute(
            """with latest as (select distinct on (fund_id) id, fund_id from runs order by fund_id, stamp desc)
               select l.id, l.fund_id, g.gate_id, g.record
               from latest l join run_gates g on g.run_id = l.id order by l.fund_id, g.position"""
        ).fetchall()
        rv = _by_run(c, {r["id"] for r in rows}) if rows else {}
    out: dict = {}
    for r in rows:
        out.setdefault(r["fund_id"], {})[r["gate_id"]] = effective(r["record"], rv.get(r["id"], {}).get(r["gate_id"]))
    return out
