"""The one-page screen note and the "what the manager must provide" list (decisions F1, F4).

The tool drafts the note from what the console already holds: intake, the gates after analyst review, flags,
contradictions, and the disposition with its confirmation state. The analyst edits it. Every draft and edit is
a new version; the newest is the note.

The request list covers only what would close a gate: for each Incomplete gate, its contradictions to
reconcile and the missing fields whose definition says what to `ask` for. At most eight items (the template's
limit); a gate with nothing specific to ask still gets one line naming it.

A summary paragraph comes from the run's model when it has one (through llm.record), else from the results.
"""

import json
from datetime import date

import yaml

from . import clock, db, disposition, review, store
from .llm import CTX, call_claude_tool

MAX_ITEMS = 8


def gate_name(g):
    return g.replace("_", " ").capitalize()


def _cite(x):
    return f"{x['file'].split('/')[-1]} p.{x['page']}"


def asks_from(gate_yaml):
    """{gate_id: {field: ask}} from the gate definitions a run used."""
    out = {}
    for gid, text in gate_yaml.items():
        g = yaml.safe_load(text or "") or {}
        out[gid] = {f["name"]: f["ask"] for f in (g.get("extractor") or {}).get("fields", []) if f.get("ask")}
    return out


def provide_list(records, effective, asks):
    """What the manager must provide to close the open gates, in gate order."""
    items: list[str] = []
    for rec in records:
        if effective[rec["gate"]]["result"] != "Incomplete":
            continue
        mine = [
            f"Reconcile the {c['field'].replace('_', ' ')}: {c['summary']}" for c in rec.get("contradictions") or []
        ]
        missing = (rec.get("brief") or {}).get("not_found") or []
        mine += [asks[rec["gate"]][f] for f in missing if f in asks.get(rec["gate"], {})]
        items += mine or [f"Documents that close the {gate_name(rec['gate']).lower()} gate"]
    return list(dict.fromkeys(items))[:MAX_ITEMS]


def outline(fund_id, stamp):
    """Everything the note says, as data."""
    run = store.run(fund_id, stamp)
    if run is None:
        raise review.ReviewError(f"no run {fund_id}/{stamp}")
    eff = review.for_run(fund_id, stamp)
    decision = disposition.for_run(fund_id, stamp)
    intake = store.intake(fund_id)
    done = next((d for d in disposition.decided_on_by_fund().get(fund_id, []) if d >= (intake["filed_on"] or "")), None)
    records = run["gates"]
    return {
        "fund": run["summary"]["fund"],
        "run": stamp,
        "share_class": run["summary"].get("share_class"),
        "intake": intake,
        "clock": clock.status(intake["filed_on"], done, date.today()),
        "decision": {k: decision[k] for k in ("disposition", "state", "confirmed", "signed_off", "blockers")},
        "gates": [
            {
                "gate": r["gate"],
                "result": eff[r["gate"]]["result"],
                "pipeline_result": r["result"],
                "review": eff[r["gate"]]["review"],
                "flags": r.get("flags") or [],
                "facts": [
                    {"field": f["field"], "value": f["value"], "file": f["file"], "page": f["page"]}
                    for f in (r.get("brief") or {}).get("facts", [])
                ],
                "contradictions": r.get("contradictions") or [],
                "failed_checks": eff[r["gate"]]["failed_checks"],
            }
            for r in records
        ],
        "marketing": run["summary"].get("marketing_contradictions") or [],
        "provide": provide_list(records, eff, asks_from(store.run_gate_yaml(fund_id, stamp))),
    }


def plain_summary(o):
    passed = sum(g["result"] == "Pass" for g in o["gates"])
    open_ = [gate_name(g["gate"]).lower() for g in o["gates"] if g["result"] in ("Incomplete", "Not yet run")]
    failed = [gate_name(g["gate"]).lower() for g in o["gates"] if g["result"] == "Fail"]
    parts = [f"{passed} of {len(o['gates'])} gates pass."]
    if failed:
        parts.append(f"Not met: {', '.join(failed)}.")
    if open_:
        parts.append(f"Open: {', '.join(open_)}.")
    return " ".join(parts)


def claude_summary(o):
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
    system = (
        "Write two or three plain sentences summarising this fund screen for the investment committee: what the "
        "fund is, where the gates stand and the main findings. Use only the outline. Do not recommend anything "
        "beyond the disposition it states."
    )
    return call_claude_tool(system, json.dumps(o), "write_summary", schema)["summary"]


SUMMARY_WRITERS = {"claude": claude_summary}

STATE = {
    "draft": "Draft, not yet confirmed",
    "confirmed": "Confirmed",
    "awaiting_signoff": "Awaiting CIO sign-off",
    "signed_off": "Signed off by the CIO",
}


def render(o, summary):
    it, d = o["intake"], o["decision"]
    by = d["signed_off"] or d["confirmed"]
    head = [
        ("Referred by", it["referred_by"]),
        ("Owner", it["owner"]),
        ("Filed", it["filed_on"]),
        ("Screen due", o["clock"]["due"] if o["clock"] else None),
        ("Sponsor deadline", it["sponsor_deadline"]),
        ("Share class", o["share_class"] or "Cheapest class open to individuals"),
    ]
    L = [
        f"# {o['fund']}: screen note",
        "",
        " | ".join(f"**{k}:** {v or '–'}" for k, v in head),
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Disposition",
        "",
        f"**{d['disposition']}**. {STATE[d['state']]}" + (f" by {by['reviewer']}." if by else "."),
        "",
        "## Gates",
        "",
        "| Gate | Result | Basis |",
        "|---|---|---|",
    ]
    for g in o["gates"]:
        res = g["result"] + (
            f" (analyst; screen said {g['pipeline_result']})" if g["result"] != g["pipeline_result"] else ""
        )
        basis = [f"{f['field'].replace('_', ' ')}: {f['value']} ({_cite(f)})" for f in g["facts"][:2]]
        basis += [f"flag: {x}" for x in g["flags"]]
        if g["review"]:
            basis.append(f"analyst: {g['review']['reason']}")
        L.append(f"| {gate_name(g['gate'])} | {res} | {'; '.join(basis) or '–'} |")
    findings = [
        f"{gate_name(g['gate'])}: the documents disagree on the {c['field'].replace('_', ' ')}. {c['summary']} "
        f"({'; '.join(f'{_cite(v)}: {v["value"]}' for v in c['values'])})"
        for g in o["gates"]
        for c in g["contradictions"]
    ]
    findings += [
        f"Marketing against filed: {c['topic']}. {c['summary']} ({_cite(c['marketing'])} against {_cite(c['filed'])})"
        for c in o["marketing"]
    ]
    findings += [
        f"{gate_name(g['gate'])}: failed the {', '.join(g['failed_checks'])} check"
        for g in o["gates"]
        if g["failed_checks"]
    ]
    L += ["", "## Findings", ""] + ([f"- {x}" for x in findings] or ["- None recorded."])
    L += ["", "## What the manager must provide", ""] + (
        [f"{i}. {x}" for i, x in enumerate(o["provide"], 1)] or ["Nothing: no gate is waiting on the manager."]
    )
    return "\n".join(L) + "\n"


def draft(fund_id, stamp):
    """A new tool draft of the note. The summary comes from the run's model when it has one."""
    o = outline(fund_id, stamp)
    extractor = (store.run(fund_id, stamp) or {"summary": {}})["summary"].get("extractor")
    writer, model = SUMMARY_WRITERS.get(extractor), None
    summary = plain_summary(o)
    if writer:
        CTX.set({"fund": o["fund"], "gate": "note", "step": "summary"})
        try:
            summary, model = writer(o), extractor
        except Exception as err:  # the call is in model_calls; the note falls back to the plain summary
            summary += f" (Model summary unavailable: {type(err).__name__}.)"
    return _save(fund_id, stamp, render(o, summary), "tool", None, model)


def edit(fund_id, stamp, body, reviewer_id):
    if not str(body or "").strip():
        raise review.ReviewError("the note is empty")
    if not any(p["id"] == reviewer_id and p["active"] for p in review.reviewers()):
        raise review.ReviewError("choose an active reviewer")
    return _save(fund_id, stamp, body, "analyst", reviewer_id, None)


def _save(fund_id, stamp, body, author, reviewer_id, model):
    with db.tx() as c:
        c.execute(
            """insert into screen_notes (run_id, body, author, reviewer_id, model)
               select id, %s, %s, %s, %s from runs where fund_id = %s and stamp = %s""",
            (body, author, reviewer_id, model, fund_id, stamp),
        )
    return versions(fund_id, stamp)


def versions(fund_id, stamp):
    """The note's versions, newest first: [{body, author, reviewer, model, at}]."""
    with db.tx() as c:
        return c.execute(
            """select n.body, n.author, p.name as reviewer, n.model,
                      to_char(n.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as at
               from screen_notes n join runs r on r.id = n.run_id left join reviewers p on p.id = n.reviewer_id
               where r.fund_id = %s and r.stamp = %s order by n.id desc""",
            (fund_id, stamp),
        ).fetchall()
