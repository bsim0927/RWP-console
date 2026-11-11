"""Create, edit, reorder and remove gates from the console, with validation and a version history.

Gates live in the `gates` table; every overwrite or delete first copies the current row to `gate_history`,
so any change can be restored. The console addresses a gate as "<position>_<id>.yaml", the name it had
when gates were files; `position` is the order the pipeline and the UI use.
"""

import ast
import re

import yaml

from . import db

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")
FILE_RE = re.compile(r"^(\d+)_([a-z][a-z0-9_]*)\.yaml$")
QTYPES = ("bool", "choice")
CHECK_NAMES = ("total_pct", "fees_disagree")  # names code_checks() adds to the rule environment
# Every gate answers in the same words; anything a fund needs beyond them (QP-only, an affiliated
# administrator) is a flag, so dispositions, charts and the screen note never learn per-gate results.
RESULTS = ("Pass", "Fail", "Incomplete")


class GateError(ValueError):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def _file(position, gid):
    return f"{position}_{gid}.yaml"


def current():
    """Live gates in pipeline order: [{file, id, position, version, text}]."""
    with db.tx() as c:
        rows = c.execute("select id, position, version, yaml from gates order by position, id").fetchall()
    return [
        {
            "file": _file(r["position"], r["id"]),
            "id": r["id"],
            "position": r["position"],
            "version": r["version"],
            "text": r["yaml"],
        }
        for r in rows
    ]


def _get(c, name):
    m = FILE_RE.match(name or "")
    row = (
        m
        and c.execute(
            "select id, position, version, yaml from gates where id = %s and position = %s", (m[2], int(m[1]))
        ).fetchone()
    )
    if not row:
        raise GateError([f"unknown gate file {name}"])
    return row


def _backup(c, row, reason):
    c.execute(
        "insert into gate_history (gate_id, position, yaml, version, reason) values (%s, %s, %s, %s, %s)",
        (row["id"], row["position"], row["yaml"], row["version"], reason),
    )


def validate(g, own_file=None):
    """Return (errors, warnings) for a parsed gate."""
    err: list[str] = []
    warn: list[str] = []
    if not isinstance(g, dict):
        return ["the gate must be a YAML mapping"], warn
    gid = g.get("id")
    if not isinstance(gid, str) or not ID_RE.match(gid):
        err.append("id must be lowercase letters, digits and underscores, starting with a letter")
    else:
        for cur in current():
            if cur["file"] != own_file and cur["id"] == gid:
                err.append(f"id {gid} is already used by {cur['file']}")
    if not isinstance(g.get("version", 1), int):
        err.append("version must be a whole number")
    if g.get("static_result"):
        return err, warn  # manual gate: no extraction, no judge
    ex = g.get("extractor") or {}
    fields = ex.get("fields") or []
    if not fields:
        err.append("add at least one field to extract")
    names = [f.get("name") for f in fields if isinstance(f, dict)]
    if any(not n or not re.match(r"^[a-z][a-z0-9_]*$", str(n)) for n in names) or len(names) != len(fields):
        err.append("every field needs a name in lowercase_with_underscores")
    if len(set(names)) != len(names):
        err.append("field names must be unique")
    if not ex.get("sources") and not ex.get("keywords"):
        warn.append("no sources or keywords: retrieval will find no pages")
    qs = g.get("questions") or []
    if not qs:
        err.append("add at least one judge question")
    qids = []
    for i, q in enumerate(qs, 1):
        if not isinstance(q, dict) or not q.get("id") or not re.match(r"^[a-z][a-z0-9_]*$", str(q.get("id"))):
            err.append(f"question {i} needs an id in lowercase_with_underscores")
            continue
        qids.append(q["id"])
        if q.get("type") not in QTYPES:
            err.append(f"question {q['id']}: type must be bool or choice")
        if not str(q.get("q", "")).strip():
            err.append(f"question {q['id']}: the question text is empty")
        if q.get("type") == "choice" and len(q.get("options") or []) < 2:
            err.append(f"question {q['id']}: a choice question needs at least two options")
    if len(set(qids)) != len(qids):
        err.append("question ids must be unique")
    allowed = (
        set(qids)
        | {f"{q['id']}_p" for q in qs if isinstance(q, dict) and q.get("type") == "choice" and q.get("id")}
        | set(CHECK_NAMES)
    )
    rules = g.get("derive") or []
    if not rules:
        err.append("add at least one derive rule")
    for i, r in enumerate(rules, 1):
        if not isinstance(r, dict) or not str(r.get("then", "")).strip():
            err.append(f"rule {i} needs a result")
            continue
        if r["then"] not in RESULTS:
            err.append(f"rule {i}: the result must be Pass, Fail or Incomplete; say anything more with a flag")
        if r.get("if") is None:
            if i < len(rules):
                warn.append(f"rule {i} has no condition, so the rules after it never run")
            continue
        err += _condition_errors(f"rule {i}", r["if"], allowed)
    flags = g.get("flags") or []
    if not isinstance(flags, list):
        err.append("flags must be a list")
        flags = []
    for i, f in enumerate(flags, 1):
        if not isinstance(f, dict) or not str(f.get("flag", "")).strip():
            err.append(f"flag {i} needs its text")
        elif f.get("if") is not None:
            err += _condition_errors(f"flag {i}", f["if"], allowed)
    checks = g.get("checks") or []
    ids = [c.get("id") for c in checks if isinstance(c, dict)] if isinstance(checks, list) else []
    if not isinstance(checks, list) or len(ids) != len(checks):
        err.append("checks must be a list of {id, q}")
    elif any(not i or not re.match(r"^[a-z][a-z0-9_]*$", str(i)) for i in ids) or len(set(ids)) != len(ids):
        err.append("every manual check needs a unique id in lowercase_with_underscores")
    elif any(not str(c.get("q", "")).strip() for c in checks):
        err.append("every manual check needs its question")
    if rules and isinstance(rules[-1], dict) and rules[-1].get("if") is not None:
        warn.append("the last rule has a condition; a gate that matches nothing returns Incomplete")
    dec = (g.get("review_if") or {}).get("decisive")
    if dec and set(dec) - set(qids):
        err.append(f"review_if.decisive names unknown questions: {', '.join(sorted(set(dec) - set(qids)))}")
    return err, warn


def _condition_errors(label, cond, allowed):
    try:
        tree = ast.parse(str(cond), mode="eval")
    except SyntaxError as e:
        return [f"{label}: condition is not valid ({e.msg})"]
    err = []
    bad = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - allowed - {"True", "False", "None"})
    if bad:
        err.append(f"{label}: unknown name {', '.join(bad)}; use question ids, {', '.join(CHECK_NAMES)}")
    if any(isinstance(n, (ast.Call, ast.Attribute, ast.Lambda, ast.Subscript)) for n in ast.walk(tree)):
        err.append(f"{label}: only comparisons, and/or/not and literals are allowed")
    return err


def _parse(text):
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise GateError([f"YAML does not parse: {e}"]) from None


def _dump(g):
    return yaml.safe_dump(g, sort_keys=False, allow_unicode=True, width=110, default_flow_style=None)


def _text_for(body):
    """Body carries either raw YAML text (comments kept) or a structured gate (form editor)."""
    if "text" in body:
        return body["text"], _parse(body["text"])
    return _dump(body["gate"]), body["gate"]


def _bump(text, g, old):
    """Raise the version when the content changes and the analyst did not change it themselves."""
    if old is None:
        return text, g
    strip = lambda d: {k: v for k, v in (d or {}).items() if k != "version"}
    if strip(g) != strip(old) and g.get("version") == old.get("version"):
        g = {**g, "version": int(old.get("version") or 0) + 1}
        if re.search(r"(?m)^version:\s*\d+", text):
            text = re.sub(r"(?m)^version:\s*\d+", f"version: {g['version']}", text, count=1)
        else:
            text = _dump(g)
    return text, g


def create(body):
    text, g = _text_for(body)
    err, warn = validate(g)
    if err:
        raise GateError(err)
    g.setdefault("version", 1)
    if "version:" not in text:
        text = _dump(g)
    with db.tx() as c:
        pos = c.execute("select coalesce(max(position), 0) + 1 as p from gates").fetchone()["p"]  # type: ignore[index]
        c.execute(
            "insert into gates (id, position, yaml, version) values (%s, %s, %s, %s)",
            (g["id"], pos, text, g["version"]),
        )
    return {"file": _file(pos, g["id"]), "warnings": warn}


def update(name, body):
    with db.tx() as c:
        row = _get(c, name)
        old = yaml.safe_load(row["yaml"])
        text, g = _text_for(body)
        err, warn = validate(g, own_file=name)
        if err:
            raise GateError(err)
        text, g = _bump(text, g, old)
        if text == row["yaml"]:
            return {"file": name, "warnings": warn, "unchanged": True}
        _backup(c, row, "edit")
        c.execute(
            "update gates set id = %s, yaml = %s, version = %s, updated_at = now() where id = %s",
            (g["id"], text, int(g.get("version") or 1), row["id"]),
        )
    return {"file": _file(row["position"], g["id"]), "warnings": warn, "version": g.get("version")}


def remove(name):
    with db.tx() as c:
        row = _get(c, name)
        _backup(c, row, "deleted")
        c.execute("delete from gates where id = %s", (row["id"],))
    return {"removed": name}


def reorder(order):
    with db.tx() as c:
        live = {_file(r["position"], r["id"]): r["id"] for r in c.execute("select id, position from gates").fetchall()}
        if sorted(order) != sorted(live):
            raise GateError(["the new order must list every gate file exactly once"])
        for i, name in enumerate(order, 1):
            c.execute("update gates set position = %s where id = %s", (i, live[name]))
    return {"order": [_file(i, live[n]) for i, n in enumerate(order, 1)]}


def history(name=None):
    """Saved prior states, newest first. A history entry's handle ("file") is its row id."""
    m = FILE_RE.match(name or "")
    with db.tx() as c:
        rows = c.execute(
            """select id, gate_id, position, yaml, version, reason,
                      to_char(created_at at time zone current_setting('TimeZone'), 'YYYYMMDD"T"HH24MISS') as stamp
               from gate_history where %(g)s::text is null or gate_id = %(g)s order by id desc""",
            {"g": m[2] if m else None},
        ).fetchall()
    return [
        {
            "file": str(r["id"]),
            "gate_file": _file(r["position"], r["gate_id"]),
            "id": r["gate_id"],
            "version": r["version"],
            "stamp": r["stamp"],
            "reason": r["reason"],
            "text": r["yaml"],
        }
        for r in rows
    ]


def restore(hist_file):
    with db.tx() as c:
        src = c.execute(
            "select yaml from gate_history where id = %s", (int(hist_file) if str(hist_file).isdigit() else -1,)
        ).fetchone()
    if not src:
        raise GateError([f"unknown history entry {hist_file}"])
    text = src["yaml"]
    g = _parse(text)
    live = next((x for x in current() if x["id"] == g.get("id")), None)
    if live:
        # A restore is a new version, never a step back, so run records stay unambiguous.
        nxt = int(live["version"] or 0) + 1
        text = (
            re.sub(r"(?m)^version:\s*\d+", f"version: {nxt}", text, count=1)
            if re.search(r"(?m)^version:", text)
            else _dump({**g, "version": nxt})
        )
        return update(live["file"], {"text": text})
    return create({"text": text})
