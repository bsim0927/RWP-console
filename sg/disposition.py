"""The disposition after analyst review, and its confirmation (decision F5).

The proposed disposition is the run's own policy applied to the gate results after review. It is a draft until
an analyst confirms it, which needs every low-confidence gate reviewed and every analyst check answered.
"Reviewed and not covered" also needs the CIO's sign-off (Charter, Section IV: the CIO declines at the screen).
Confirmations are append-only; only an unbroken run of the newest ones naming the current disposition counts,
so a later review that changes the disposition reopens the draft.
"""

import yaml

from . import db, review, store
from .pipeline import reduce_gates

NOT_COVERED = "Reviewed and not covered"
FINAL = ("confirmed", "signed_off")

_CONFIRMATIONS = """
    select d.run_id, d.disposition, d.reviewer_id, p.name as reviewer, p.role, d.sign_off, d.reason,
           to_char(d.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as at
    from disposition_confirmations d join reviewers p on p.id = d.reviewer_id
    where d.run_id = any(%s) order by d.id desc"""


def decide(gates, policy, confirmations=()):
    """gates: {gate_id: review.effective(...)}; confirmations newest first."""
    results = [{"result": e["result"], "review": e["needs_review"]} for e in gates.values()]
    disposition, flags = reduce_gates(policy, results)
    blockers = []
    waiting = [g for g, e in gates.items() if e["needs_review"]]
    if waiting:
        blockers.append(f"review {', '.join(g.replace('_', ' ') for g in waiting)}")
    pending = [f"{k} ({g.replace('_', ' ')})" for g, e in gates.items() for k in e["pending_checks"]]
    if pending:
        blockers.append(f"answer the {', '.join(pending)} check{'s' if len(pending) > 1 else ''}")
    streak = []
    for c in confirmations:
        if c["disposition"] != disposition:
            break
        streak.append(c)
    needs_signoff = disposition.startswith(NOT_COVERED)
    signed = next((c for c in streak if c["sign_off"]), None)
    if not streak:
        state = "draft"
    elif needs_signoff:
        state = "signed_off" if signed else "awaiting_signoff"
    else:
        state = "confirmed"
    return {
        "disposition": disposition,
        "flags": flags,
        "state": state,
        "needs_signoff": needs_signoff,
        "confirmed": streak[-1] if streak else None,
        "signed_off": signed,
        "blockers": blockers,
        "history": list(confirmations),
    }


def _policies(c, run_ids):
    """{run_id: the policy the run was screened under}; the policy in force for runs that predate the link."""
    rows = c.execute(
        "select r.id, p.yaml from runs r left join policies p on p.id = r.policy_id where r.id = any(%s)",
        (list(run_ids),),
    ).fetchall()
    now = store.policy()["yaml"] if any(r["yaml"] is None for r in rows) else ""
    return {r["id"]: yaml.safe_load(r["yaml"] or now) for r in rows}


def _confirmations(c, run_ids):
    out: dict = {}
    for r in c.execute(_CONFIRMATIONS, (list(run_ids),)).fetchall():
        out.setdefault(r.pop("run_id"), []).append(r)
    return out


def for_run(fund_id, stamp):
    gates = review.for_run(fund_id, stamp)
    with db.tx() as c:
        run_id = c.execute("select id from runs where fund_id = %s and stamp = %s", (fund_id, stamp)).fetchone()["id"]  # type: ignore[index]
        policy = _policies(c, [run_id])[run_id]
        conf = _confirmations(c, [run_id]).get(run_id, [])
    return decide(gates, policy, conf)


def latest_by_fund():
    """{fund_id: {"run": stamp, "gates": {gate_id: effective}, "decision": decide(...)}} for each newest run."""
    gates = review.latest_by_fund()
    with db.tx() as c:
        heads = c.execute(
            "select distinct on (fund_id) id, fund_id, stamp from runs order by fund_id, stamp desc"
        ).fetchall()
        ids = [h["id"] for h in heads]
        policies, conf = (_policies(c, ids), _confirmations(c, ids)) if ids else ({}, {})
    return {
        h["fund_id"]: {
            "run": h["stamp"],
            "gates": gates.get(h["fund_id"], {}),
            "decision": decide(gates.get(h["fund_id"], {}), policies[h["id"]], conf.get(h["id"], [])),
        }
        for h in heads
    }


def confirm(fund_id, stamp, reviewer_id, reason=None):
    """Confirm the current disposition; from the CIO this is also the sign-off a "not covered" needs."""
    now = for_run(fund_id, stamp)
    if now["blockers"]:
        raise review.ReviewError("before confirming, " + "; ".join(now["blockers"]))
    people = {p["id"]: p for p in review.reviewers()}
    me = people.get(reviewer_id)
    if not me or not me["active"]:
        raise review.ReviewError("choose an active reviewer")
    if now["state"] in FINAL:
        raise review.ReviewError("this disposition is already confirmed")
    if now["state"] == "awaiting_signoff" and me["role"] != "cio":
        raise review.ReviewError("a not-covered disposition is signed off by the CIO")
    with db.tx() as c:
        c.execute(
            """insert into disposition_confirmations (run_id, disposition, reviewer_id, sign_off, reason)
               select id, %s, %s, %s, %s from runs where fund_id = %s and stamp = %s""",
            (
                now["disposition"],
                reviewer_id,
                me["role"] == "cio" and now["needs_signoff"],
                str(reason or "").strip() or None,
                fund_id,
                stamp,
            ),
        )
    return for_run(fund_id, stamp)


def decided_on_by_fund():
    """{fund_id: [dates, oldest first]} on which a screen of the fund reached a final, confirmed disposition."""
    with db.tx() as c:
        rows = c.execute(
            """select r.fund_id, to_char(d.created_at, 'YYYY-MM-DD') as day
               from disposition_confirmations d join runs r on r.id = d.run_id
               where d.sign_off or d.disposition not like %s order by d.created_at""",
            (NOT_COVERED + "%",),
        ).fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(r["fund_id"], []).append(r["day"])
    return out
