"""Edit the disposition policy from the console, with validation and a version history.

The `policies` table is append-only: saving adds a row and the newest row is in force, so every earlier
version stays available to view or restore, and each run records the version it was decided under.
"""

import yaml

from . import db
from .gate_store import GateError

# The conditions sg.pipeline.reduce_gates evaluates. tests/test_policy_store.py holds the two in step.
CONDITIONS = ("any_review", "any_incomplete", "any_fail", "otherwise")
# Disposition prefixes the console colour-codes (web/js/lib.js dispTone).
KNOWN_DISPOSITIONS = ("Coverable", "Covered", "Reviewed and not covered", "Under review")
FALLBACK = "Under review"  # what reduce_gates returns when no rule matches


def validate(p):
    """Return (errors, warnings) for a parsed policy."""
    err: list[str] = []
    warn: list[str] = []
    if not isinstance(p, dict):
        return ["the policy must be a YAML mapping with a rules list"], warn
    rules = p.get("rules")
    if not isinstance(rules, list) or not rules:
        return ["add at least one rule"], warn
    seen: set[str] = set()
    for i, r in enumerate(rules, 1):
        if not isinstance(r, dict):
            err.append(f"rule {i} must have a when and a disposition")
            continue
        when, disp = r.get("when"), r.get("disposition")
        if when not in CONDITIONS:
            err.append(f"rule {i}: when must be one of {', '.join(CONDITIONS)}")
        elif when in seen:
            warn.append(f"rule {i}: {when} already appears above, so this rule never matches")
        else:
            seen.add(when)
        if not isinstance(disp, str) or not disp.strip():
            err.append(f"rule {i} needs a disposition")
        elif not disp.startswith(KNOWN_DISPOSITIONS):
            warn.append(f"rule {i}: the console colours dispositions starting with {', '.join(KNOWN_DISPOSITIONS)}")
        if when == "otherwise" and i < len(rules):
            warn.append(f"rule {i} is otherwise, so the rules after it never run")
    if "otherwise" not in seen:
        warn.append(f"no otherwise rule: a run that matches nothing is recorded as {FALLBACK}")
    return err, warn


def _parse(text):
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise GateError([f"YAML does not parse: {e}"]) from None


def save(text):
    """Save a new version if it is valid and differs from the one in force."""
    err, warn = validate(_parse(text))
    if err:
        raise GateError(err)
    with db.tx() as c:
        cur = c.execute("select id, yaml from policies order by id desc limit 1").fetchone()
        if cur and cur["yaml"] == text:
            return {"id": cur["id"], "warnings": warn, "unchanged": True}
        new = c.execute("insert into policies (yaml) values (%s) returning id", (text,)).fetchone()
    return {"id": new["id"], "warnings": warn}  # type: ignore[index]


def history():
    """Every version, newest first; the first one is in force."""
    with db.tx() as c:
        rows = c.execute(
            """select id, yaml,
                      to_char(created_at at time zone current_setting('TimeZone'), 'YYYYMMDD"T"HH24MISS') as stamp
               from policies order by id desc"""
        ).fetchall()
    return [{"id": r["id"], "stamp": r["stamp"], "text": r["yaml"], "current": i == 0} for i, r in enumerate(rows)]


def restore(version_id):
    """Bring back an earlier version as a new one: history only ever moves forward."""
    with db.tx() as c:
        row = c.execute("select yaml from policies where id = %s", (int(version_id),)).fetchone()
    if not row:
        raise GateError([f"unknown policy version {version_id}"])
    return save(row["yaml"])
