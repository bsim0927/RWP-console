"""Persistent state in Postgres: screening runs, model calls, document catalogs and the policy.

Functions take and return the same dicts the pipeline and the console have always used (summary.json,
gate records, catalog documents), so callers do not change shape. Gates live in sg/gate_store.py.
"""

import time
from datetime import UTC, datetime

from psycopg import sql
from psycopg.types.json import Json

from . import db


def stamp_time(stamp):
    """Run stamps are local wall-clock time, YYYYMMDDTHHMMSS."""
    return datetime.fromtimestamp(time.mktime(time.strptime(stamp, "%Y%m%dT%H%M%S")), UTC)


# ---------- runs ----------


_INSERT_RUN = """
    insert into runs (fund_id, stamp, fund_name, extractor, judge, disposition, policy_id, summary, report_md,
                      created_at)
    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    returning id"""
_UPSERT_RUN = """
    insert into runs (fund_id, stamp, fund_name, extractor, judge, disposition, policy_id, summary, report_md,
                      created_at)
    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    on conflict (fund_id, stamp) do update set
      fund_name = excluded.fund_name, extractor = excluded.extractor, judge = excluded.judge,
      disposition = excluded.disposition, policy_id = excluded.policy_id,
      summary = excluded.summary, report_md = excluded.report_md
    returning id"""


def save_run(fund_id, summary, results, report_md, gate_yaml=None, policy_id=None, replace=False):
    """One run and its gate records, atomically. gate_yaml maps gate id -> the definition it ran with.
    A second run with the same fund and stamp is an error, unless replace (re-imports) says otherwise."""
    gate_yaml = gate_yaml or {}
    with db.tx() as c:
        params = (
            fund_id,
            summary["run"],
            summary["fund"],
            summary.get("extractor"),
            summary.get("judge"),
            summary["disposition"],
            policy_id,
            Json(summary),
            report_md or "",
            stamp_time(summary["run"]),
        )
        cur = c.execute(_UPSERT_RUN if replace else _INSERT_RUN, params)
        run_id = cur.fetchone()["id"]  # type: ignore[index]
        c.execute("delete from run_gates where run_id = %s", (run_id,))
        for pos, r in enumerate(results, 1):
            c.execute(
                """insert into run_gates (run_id, gate_id, position, gate_version, gate_yaml, result, review,
                                          min_confidence, record)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    run_id,
                    r["gate"],
                    pos,
                    r.get("gate_version"),
                    gate_yaml.get(r["gate"]),
                    r["result"],
                    bool(r.get("review")),
                    r.get("min_confidence"),
                    Json(r),
                ),
            )
    return run_id


def run_stamps(fund_id):
    """A fund's run stamps, newest first."""
    with db.tx() as c:
        rows = c.execute("select stamp from runs where fund_id = %s order by stamp desc", (fund_id,)).fetchall()
    return [r["stamp"] for r in rows]


def stamps_by_fund():
    """{fund_id: [run stamps, newest first]} for every fund with a run, in one query."""
    with db.tx() as c:
        rows = c.execute("select fund_id, stamp from runs order by fund_id, stamp desc").fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["fund_id"], []).append(r["stamp"])
    return out


def latest_summaries():
    """{fund_id: summary of its newest run}."""
    with db.tx() as c:
        rows = c.execute(
            "select distinct on (fund_id) fund_id, summary from runs order by fund_id, stamp desc"
        ).fetchall()
    return {r["fund_id"]: r["summary"] for r in rows}


def summaries(fund_id=None, newest_first=True):
    """Run summaries, each with fund_id added."""
    with db.tx() as c:
        rows = c.execute(
            "select fund_id, stamp, summary from runs where %(f)s::text is null or fund_id = %(f)s",
            {"f": fund_id},
        ).fetchall()
    rows.sort(key=lambda r: r["stamp"], reverse=newest_first)
    return [dict(r["summary"], fund_id=r["fund_id"]) for r in rows]


def run(fund_id, stamp):
    """{summary, gates, markdown} for one run, or None."""
    with db.tx() as c:
        head = c.execute(
            "select id, summary, report_md from runs where fund_id = %s and stamp = %s", (fund_id, stamp)
        ).fetchone()
        if head is None:
            return None
        gates = c.execute("select record from run_gates where run_id = %s order by position", (head["id"],)).fetchall()
    return {"summary": head["summary"], "gates": [g["record"] for g in gates], "markdown": head["report_md"]}


def run_gate_yaml(fund_id, stamp):
    """{gate_id: the gate definition the run used}."""
    with db.tx() as c:
        rows = c.execute(
            """select g.gate_id, g.gate_yaml from run_gates g join runs r on r.id = g.run_id
               where r.fund_id = %s and r.stamp = %s order by g.position""",
            (fund_id, stamp),
        ).fetchall()
    return {r["gate_id"]: r["gate_yaml"] for r in rows}


def runs_with_gates():
    """Every run, oldest first, as {fund_id, summary, gates: [records]}, for analytics and monitoring."""
    with db.tx() as c:
        heads = c.execute("select id, fund_id, summary from runs order by fund_id, stamp").fetchall()
        gates = c.execute("select run_id, record from run_gates order by run_id, position").fetchall()
    by_run: dict = {}
    for g in gates:
        by_run.setdefault(g["run_id"], []).append(g["record"])
    return [{"fund_id": h["fund_id"], "summary": h["summary"], "gates": by_run.get(h["id"], [])} for h in heads]


# ---------- model calls ----------

CALL_FIELDS = [
    "fund",
    "gate",
    "step",
    "model",
    "seconds",
    "error",
    "attempts",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "input_chars",
    "output",
]


def record_call(rec):
    """One model call, as llm.record() builds it. Re-recording the same id is a no-op."""
    with db.tx() as c:
        c.execute(
            """insert into model_calls (id, ts, fund, gate, step, provider, model, seconds, ok, error, attempts,
                                        input_tokens, output_tokens, cache_read_tokens, input_chars, output)
               values (%(id)s, to_timestamp(%(ts)s), %(fund)s, %(gate)s, %(step)s, %(provider)s, %(model)s,
                       %(seconds)s, %(ok)s, %(error)s, %(attempts)s, %(input_tokens)s, %(output_tokens)s,
                       %(cache_read_tokens)s, %(input_chars)s, %(output)s)
               on conflict (id) do nothing""",
            {**dict.fromkeys(CALL_FIELDS), **rec, "ts": rec.get("ts") or time.time()},
        )


def calls():
    """Every recorded model call, oldest first, with ts as epoch seconds like the records themselves."""
    with db.tx() as c:
        return c.execute(
            """select id, extract(epoch from ts)::float8 as ts, fund, gate, step, provider, model,
                      seconds::float8 as seconds, ok, error, attempts, input_tokens, output_tokens,
                      cache_read_tokens, input_chars, output
               from model_calls order by ts"""
        ).fetchall()


# ---------- catalogs ----------


def save_catalog(room_id, room_name, docs, summary):
    """Replace a room's catalog."""
    with db.tx() as c:
        c.execute(
            """insert into catalogs (room_id, room_name, summary, built_at) values (%s, %s, %s, now())
               on conflict (room_id) do update set room_name = excluded.room_name, summary = excluded.summary,
                 built_at = excluded.built_at""",
            (room_id, room_name, Json(summary)),
        )
        c.execute("delete from catalog_documents where room_id = %s", (room_id,))
        with c.cursor() as cur:
            cur.executemany(
                "insert into catalog_documents (room_id, doc_id, ordinal, doc) values (%s, %s, %s, %s)",
                [(room_id, d["doc_id"], i, Json(d)) for i, d in enumerate(docs)],
            )


def catalog(room_id):
    """(summary, docs) for a room, or None if it has never been built."""
    with db.tx() as c:
        head = c.execute("select summary from catalogs where room_id = %s", (room_id,)).fetchone()
        if head is None:
            return None
        docs = c.execute("select doc from catalog_documents where room_id = %s order by ordinal", (room_id,)).fetchall()
    return head["summary"], [d["doc"] for d in docs]


def catalog_summaries():
    """{room_id: catalog summary}."""
    with db.tx() as c:
        rows = c.execute("select room_id, summary from catalogs").fetchall()
    return {r["room_id"]: r["summary"] for r in rows}


# ---------- intake ----------

INTAKE_FIELDS = ("referred_by", "owner", "sponsor_deadline", "filed_on", "share_class")
INTAKE_DATES = ("sponsor_deadline", "filed_on")
_INTAKE_SELECT = """select fund_id, referred_by, owner, to_char(sponsor_deadline, 'YYYY-MM-DD') as sponsor_deadline,
                           to_char(filed_on, 'YYYY-MM-DD') as filed_on, share_class from intake"""


def intakes():
    """{fund_id: {referred_by, owner, sponsor_deadline, filed_on, share_class}}, dates as YYYY-MM-DD."""
    with db.tx() as c:
        rows = c.execute(_INTAKE_SELECT).fetchall()
    return {r["fund_id"]: {k: r[k] for k in INTAKE_FIELDS} for r in rows}


def intake(fund_id):
    return intakes().get(fund_id) or dict.fromkeys(INTAKE_FIELDS)


def save_intake(fund_id, fields):
    """Set the given intake fields; blank clears one. Unknown fields and malformed dates are refused."""
    bad = sorted(set(fields) - set(INTAKE_FIELDS))
    if bad:
        raise ValueError(f"unknown intake field {', '.join(bad)}")
    vals = {k: (str(v).strip() or None) if v is not None else None for k, v in fields.items()}
    for k in INTAKE_DATES:
        if vals.get(k):
            try:
                datetime.strptime(vals[k], "%Y-%m-%d")  # type: ignore[arg-type]
            except ValueError:
                raise ValueError(f"{k} must be a date, YYYY-MM-DD") from None
    if not vals:
        return intake(fund_id)
    cols = [sql.Identifier(k) for k in vals]
    query = sql.SQL(
        "insert into intake (fund_id, {cols}) values (%s, {vals}) "
        "on conflict (fund_id) do update set {sets}, updated_at = now()"
    ).format(
        cols=sql.SQL(", ").join(cols),
        vals=sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        sets=sql.SQL(", ").join(sql.SQL("{0} = excluded.{0}").format(k) for k in cols),
    )
    with db.tx() as c:
        c.execute(query, (fund_id, *vals.values()))
    return intake(fund_id)


# ---------- policy ----------


def policy():
    """The policy in force: {id, yaml}. The newest row wins; older rows are its history."""
    with db.tx() as c:
        row = c.execute("select id, yaml from policies order by id desc limit 1").fetchone()
    if row is None:
        raise SystemExit("no policy in the database; the seed migration should have added one")
    return row


def save_policy(yaml_text):
    with db.tx() as c:
        return c.execute("insert into policies (yaml) values (%s) returning id", (yaml_text,)).fetchone()["id"]  # type: ignore[index]
