"""Create, edit, reorder and remove gate files from the console, with validation and a version history.

Every overwrite or delete first copies the current file to gates/.history/, so any change can be restored.
Files are named <position>_<id>.yaml; the position prefix is the order the pipeline and the UI use.
"""

import ast
import os
import re
import time
from pathlib import Path

import yaml

GATES = Path(__file__).resolve().parent.parent / "gates"
HISTORY = GATES / ".history"
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")
QTYPES = ("bool", "choice")
CHECK_NAMES = {"total_pct"}  # names code_checks() adds to the rule environment


class GateError(ValueError):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def files():
    return sorted(GATES.glob("*.yaml"), key=lambda p: (_pos(p), p.name))


def _pos(p):
    m = re.match(r"(\d+)_", p.name)
    return int(m.group(1)) if m else 999


def _path(name):
    p = GATES / name
    if p.parent != GATES or p.suffix != ".yaml" or not p.exists():
        raise GateError([f"unknown gate file {name}"])
    return p


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
        for p in files():
            if p.name != own_file and (yaml.safe_load(p.read_text()) or {}).get("id") == gid:
                err.append(f"id {gid} is already used by {p.name}")
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
        | CHECK_NAMES
    )
    rules = g.get("derive") or []
    if not rules:
        err.append("add at least one derive rule")
    for i, r in enumerate(rules, 1):
        if not isinstance(r, dict) or not str(r.get("then", "")).strip():
            err.append(f"rule {i} needs a result")
            continue
        cond = r.get("if")
        if cond is None:
            if i < len(rules):
                warn.append(f"rule {i} has no condition, so the rules after it never run")
            continue
        try:
            tree = ast.parse(str(cond), mode="eval")
        except SyntaxError as e:
            err.append(f"rule {i}: condition is not valid ({e.msg})")
            continue
        bad = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - allowed - {"True", "False", "None"})
        if bad:
            err.append(
                f"rule {i}: unknown name {', '.join(bad)}; use question ids{', total_pct' if CHECK_NAMES else ''}"
            )
        if any(isinstance(n, (ast.Call, ast.Attribute, ast.Lambda, ast.Subscript)) for n in ast.walk(tree)):
            err.append(f"rule {i}: only comparisons, and/or/not and literals are allowed")
    if rules and isinstance(rules[-1], dict) and rules[-1].get("if") is not None:
        warn.append("the last rule has a condition; a gate that matches nothing returns Incomplete")
    dec = (g.get("review_if") or {}).get("decisive")
    if dec and set(dec) - set(qids):
        err.append(f"review_if.decisive names unknown questions: {', '.join(sorted(set(dec) - set(qids)))}")
    return err, warn


def _parse(text):
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise GateError([f"YAML does not parse: {e}"]) from None


def _dump(g):
    return yaml.safe_dump(g, sort_keys=False, allow_unicode=True, width=110, default_flow_style=None)


def _backup(p, reason):
    HISTORY.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    (HISTORY / f"{p.stem}.{stamp}.{reason}.yaml").write_text(p.read_text())


def _write(p, text):
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(text)
    os.replace(tmp, p)  # the pipeline never sees a half-written gate


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
    pos = max([_pos(p) for p in files() if _pos(p) < 999] or [0]) + 1
    p = GATES / f"{pos}_{g['id']}.yaml"
    _write(p, text)
    return {"file": p.name, "warnings": warn}


def update(name, body):
    p = _path(name)
    old = yaml.safe_load(p.read_text())
    text, g = _text_for(body)
    err, warn = validate(g, own_file=name)
    if err:
        raise GateError(err)
    text, g = _bump(text, g, old)
    if text == p.read_text():
        return {"file": name, "warnings": warn, "unchanged": True}
    _backup(p, "edit")
    target = p
    if g["id"] != old.get("id"):  # keep the file name in step with the id
        target = GATES / f"{_pos(p)}_{g['id']}.yaml"
        p.unlink()
    _write(target, text)
    return {"file": target.name, "warnings": warn, "version": g.get("version")}


def remove(name):
    p = _path(name)
    _backup(p, "deleted")
    p.unlink()
    return {"removed": name}


def reorder(order):
    current = {p.name: p for p in files()}
    if sorted(order) != sorted(current):
        raise GateError(["the new order must list every gate file exactly once"])
    staged = []
    for i, name in enumerate(order, 1):
        tmp = GATES / f".reorder.{name}"
        os.replace(current[name], tmp)
        staged.append((tmp, GATES / re.sub(r"^\d+_", f"{i}_", name if re.match(r"\d+_", name) else f"{i}_{name}")))
    for tmp, final in staged:
        os.replace(tmp, final)
    return {"order": [f.name for _, f in staged]}


def history(name=None):
    if not HISTORY.exists():
        return []
    out = []
    for p in sorted(HISTORY.glob("*.yaml"), reverse=True):
        stem, stamp, reason = (p.name[:-5].rsplit(".", 2) + ["", ""])[:3]
        if name and stem != Path(name).stem and stem.split("_", 1)[-1] != Path(name).stem.split("_", 1)[-1]:
            continue
        g = yaml.safe_load(p.read_text()) or {}
        out.append(
            {
                "file": p.name,
                "gate_file": stem + ".yaml",
                "id": g.get("id"),
                "version": g.get("version"),
                "stamp": stamp,
                "reason": reason,
                "text": p.read_text(),
            }
        )
    return out


def restore(hist_file):
    src = HISTORY / hist_file
    if src.parent != HISTORY or not src.exists():
        raise GateError([f"unknown history entry {hist_file}"])
    text = src.read_text()
    g = _parse(text)
    live = next((p for p in files() if (yaml.safe_load(p.read_text()) or {}).get("id") == g.get("id")), None)
    if live:
        # A restore is a new version, never a step back, so run records stay unambiguous.
        nxt = int((yaml.safe_load(live.read_text()) or {}).get("version") or 0) + 1
        text = (
            re.sub(r"(?m)^version:\s*\d+", f"version: {nxt}", text, count=1)
            if re.search(r"(?m)^version:", text)
            else _dump({**g, "version": nxt})
        )
        return update(live.name, {"text": text})
    return create({"text": text})
