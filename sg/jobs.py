"""Screen jobs and the console's event log, kept in the database.

Deployed on Vercel, each request may run in a different function instance, so a screen cannot live in one
request's memory while another polls it. A screen is asked for (a queued job), then run by the request that
claims it, which writes its step timeline here as it goes; the browser polls this table. A job that stops
reporting for longer than any function may run was cut off, and says so when read.
"""

import random
import time
import uuid

from psycopg.types.json import Json

from . import db

STALE_AFTER = 900  # seconds without progress; past Vercel's longest function duration (800s)
KEEP_EVENTS = 5000

_JOB = """
    select id, fund_id, fund_name, extractor, judge, status, gates, steps, run_stamp, error,
           extract(epoch from created_at)::float8 as started, extract(epoch from updated_at)::float8 as touched
    from screen_jobs"""


def create(fund_id, fund_name, extractor, judge, gates):
    jid = uuid.uuid4().hex[:10]
    with db.tx() as c:
        c.execute(
            """insert into screen_jobs (id, fund_id, fund_name, extractor, judge, status, gates)
               values (%s, %s, %s, %s, %s, 'queued', %s)""",
            (jid, fund_id, fund_name, extractor, judge, Json(gates)),
        )
    return jid


def claim(jid):
    """Move a queued job to running and return it, or None if it is unknown or already claimed."""
    with db.tx() as c:
        row = c.execute(
            "update screen_jobs set status = 'running', updated_at = now() where id = %s and status = 'queued' "
            "returning id, fund_id, extractor, judge",
            (jid,),
        ).fetchone()
    return row


def progress(jid, steps):
    with db.tx() as c:
        c.execute("update screen_jobs set steps = %s, updated_at = now() where id = %s", (Json(steps), jid))


def finish(jid, steps, run_stamp=None, error=None):
    with db.tx() as c:
        c.execute(
            """update screen_jobs set status = %s, steps = %s, run_stamp = %s, error = %s, updated_at = now()
               where id = %s""",
            ("error" if error else "done", Json(steps), run_stamp, error, jid),
        )


def _shape(r, now):
    """The job as the console reads it. A running job silent past STALE_AFTER was cut off."""
    status, error = r["status"], r["error"]
    if status in ("queued", "running") and now - r["touched"] > STALE_AFTER:
        status, error = "error", "the screen stopped without finishing (cut off or interrupted)"
    open_ = status in ("queued", "running")
    elapsed = round((now if open_ else r["touched"]) - r["started"], 1)
    return {
        "id": r["id"],
        "fund": r["fund_name"],
        "fund_id": r["fund_id"],
        "extractor": r["extractor"],
        "judge": r["judge"],
        "status": "running" if status == "queued" else status,  # the console shows a queued job as starting
        "started": r["started"],
        "elapsed": elapsed,
        "seconds": None if open_ else elapsed,
        "run": r["run_stamp"],
        "error": error,
        "gates": r["gates"],
        "steps": r["steps"],
    }


def get(jid):
    with db.tx() as c:
        r = c.execute(f"{_JOB} where id = %s", (jid,)).fetchone()  # noqa: S608  constant
    return _shape(r, time.time()) if r else None


def recent(limit=50):
    """The newest jobs, newest first."""
    with db.tx() as c:
        rows = c.execute(f"{_JOB} order by created_at desc limit %s", (limit,)).fetchall()  # noqa: S608  constant
    now = time.time()
    return [_shape(r, now) for r in rows]


def log(kind, msg, level="info", **extra):
    with db.tx() as c:
        c.execute(
            "insert into console_events (kind, level, msg, extra) values (%s, %s, %s, %s)",
            (kind, level, msg, Json(extra)),
        )
        if random.random() < 0.01:  # noqa: S311  not security; trims the log now and then
            c.execute("delete from console_events where id < (select max(id) from console_events) - %s", (KEEP_EVENTS,))


def events(limit=1000):
    """The newest events, oldest first: [{t, kind, level, msg, ...extra}]."""
    with db.tx() as c:
        rows = c.execute(
            """select extract(epoch from ts)::float8 as t, kind, level, msg, extra
               from console_events order by id desc limit %s""",
            (limit,),
        ).fetchall()
    return [{"t": r["t"], "kind": r["kind"], "level": r["level"], "msg": r["msg"], **r["extra"]} for r in rows[::-1]]
