#!/usr/bin/env python3
"""The analyst console.

    [PORT=8765] python3 server.py [data-root]     # local, at http://127.0.0.1:8765

Deployed, Vercel imports `app` (WSGI) from this module and the data root comes from RWP_DATA_ROOT. Both paths
run the same handler. With SITE_PASSWORD set, every page and API call needs a session from /login.
"""

import hashlib
import hmac
import json
import mimetypes
import os
import re
import sys
import time
from datetime import date
from email.message import Message
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sg import (  # noqa: E402
    clock,
    datasource,
    disposition,
    fund_status,
    gate_store,
    jobs,
    monitor,
    note,
    policy_store,
    review,
    store,
)
from sg.catalog import build as build_catalog  # noqa: E402
from sg.pipeline import ROOT, Tracker, load_gates, run  # noqa: E402

WEB = ROOT / "web"

# The command line sets it locally (see __main__); an importer such as Vercel's runtime has other arguments.
DATA_ROOT = Path(os.environ.get("RWP_DATA_ROOT", str(Path.home() / "Desktop/RWP-funds"))).resolve()
slug = lambda n: re.sub(r"[^\w.-]+", "_", n)
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
TEXT_EXT = (".md", ".csv", ".json", ".yaml", ".yml", ".txt", ".jsonl")


def log(kind, msg, level="info", **extra):
    """An event for the agent monitor. Logging never breaks a request: if the database is unreachable,
    the event goes to stderr instead."""
    try:
        jobs.log(kind, msg, level, **extra)
    except Exception as e:
        print(f"[{level}] {kind}: {msg} (not logged: {type(e).__name__})", file=sys.stderr)


# ---------- the shared password ----------
# A session cookie is an expiry signed with a key derived from SITE_PASSWORD, so changing the password signs
# everyone out. Unset, the console is open: local use and the test suites.

SESSION_COOKIE, SESSION_DAYS = "rwp_session", 30


def session_key():
    pw = os.environ.get("SITE_PASSWORD", "")
    return hmac.new(pw.encode(), b"rwp-console session", hashlib.sha256).digest() if pw else None


def session_value(now=None):
    exp = str(int((now or time.time()) + SESSION_DAYS * 86400))
    return f"{exp}.{hmac.new(session_key() or b'', exp.encode(), hashlib.sha256).hexdigest()}"


def valid_session(value, now=None):
    key = session_key()
    exp, _, sig = (value or "").partition(".")
    if not key or not exp.isdigit():
        return False
    good = hmac.new(key, exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and int(exp) > (now or time.time())


# ---------- the fund data ----------
# A data root on disk, or the database and Storage when hosted (sg/datasource.py, chosen by RWP_DATA_SOURCE).
# Folder names inside a fund are kept as they are and mean nothing to the console.

_SOURCES: dict = {}


def data():
    """The data source, one per data root, so a local source keeps its page cache between requests."""
    key = (os.environ.get("RWP_DATA_SOURCE", "local"), DATA_ROOT)
    if key not in _SOURCES:
        _SOURCES[key] = datasource.source(DATA_ROOT)
    return _SOURCES[key]


def discover():
    """{room id: Room} for every indexed data room."""
    return data().rooms()


def inside(base, p):
    try:
        return p.resolve().is_relative_to(base.resolve())
    except OSError:
        return False


# ---------- where each fund stands ----------
# Statuses live in the database and move only by the CIO's hand (sg/fund_status.py). The last and next action
# come from the screen itself, so they are never stale and nobody types them.

STATE_WORDS = {
    "draft": "draft",
    "confirmed": "confirmed",
    "awaiting_signoff": "awaiting CIO sign-off",
    "signed_off": "signed off",
}


def fund_actions(latest):
    """{"last", "next"} for a fund from its newest screen (disposition.latest_by_fund), or Nones."""
    if not latest:
        return {"last": None, "next": "Screen the data room"}
    d, r = latest["decision"], latest["run"]
    last = f"Screened {r[:4]}-{r[4:6]}-{r[6:8]}: {d['disposition'].split(' (')[0]} ({STATE_WORDS[d['state']]})"
    if d["blockers"]:
        nxt = "Analyst to " + "; ".join(d["blockers"])
    elif d["state"] == "awaiting_signoff":
        nxt = "CIO sign-off"
    elif d["state"] == "draft":
        nxt = "Confirm the disposition"
    elif d["disposition"].startswith("Under review"):
        nxt = "Manager to provide the requested documents"
    else:
        nxt = "CIO to update the status"
    return {"last": last, "next": nxt}


def screen_clock(intake, decided_on):
    """The fund against its five-business-day clock. The screen is done once a disposition is confirmed
    (or, for "not covered", signed off) on or after the filing date."""
    filed = intake.get("filed_on")
    if not filed:
        return None
    done = next((d for d in decided_on if d >= filed), None)
    return clock.status(filed, done, date.today())


def with_review(summary, latest):
    """A run summary after analyst review: each gate's reviewed result (the pipeline's stays as pipeline_result),
    and the proposed disposition with its confirmation state."""
    if not summary or not latest or latest["run"] != summary["run"]:
        return summary
    gates = {}
    for g, x in summary["gates"].items():
        e = latest["gates"].get(g)
        gates[g] = (
            x
            if e is None
            else {
                **x,
                "result": e["result"],
                "pipeline_result": e["pipeline_result"],
                "reviewed": e["reviewed"],
                "review": e["needs_review"],
                "pending_checks": e["pending_checks"],
            }
        )
    d = latest["decision"]
    decision = {k: d[k] for k in ("state", "needs_signoff", "confirmed", "signed_off", "blockers")}
    return {**summary, "gates": gates, "flags": d["flags"], "disposition": d["disposition"], "decision": decision}


# ---------- analytics over every logged run ----------


def analytics():
    """One row per gate per run: result, confidence, evidence counts, tokens, step seconds."""
    rows = []
    for r in sorted(store.runs_with_gates(), key=lambda r: r["summary"]["run"], reverse=True):
        s = dict(r["summary"], fund_id=r["fund_id"])
        for g in r["gates"]:
            b = g.get("brief") or {}
            usage = ((g.get("answers") or {}).get("_meta") or {}).get("usage") or {}
            steps = {
                e["step"]: round((e["end"] if e["end"] is not None else e["start"]) - e["start"], 3)
                for e in g.get("timeline") or []
            }
            rows.append(
                {
                    "fund": s["fund"],
                    "fund_id": s["fund_id"],
                    "run": s["run"],
                    "extractor": s.get("extractor"),
                    "judge": s.get("judge"),
                    "gate": g.get("gate"),
                    "result": g.get("result"),
                    "review": bool(g.get("review")),
                    "min_confidence": g.get("min_confidence"),
                    "facts": len(b.get("facts") or []),
                    "rejected": len(g.get("rejected") or []),
                    "not_found": len(b.get("not_found") or []),
                    "pages_offered": len(g.get("pages_offered") or []),
                    "tokens_in": usage.get("input_tokens", 0),
                    "tokens_out": usage.get("output_tokens", 0),
                    "steps": steps,
                }
            )
    return rows


class H(BaseHTTPRequestHandler):
    def send(self, body, ctype="application/json", code=200, extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self._code = code
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def signed_in(self):
        if not session_key():
            return True
        morsel = SimpleCookie(self.headers.get("Cookie") or "").get(SESSION_COOKIE)
        return morsel is not None and valid_session(morsel.value)

    def guard(self):
        """Run the sign-in pages, and turn away anyone without a session. True when the request may go on."""
        path = urlparse(self.path).path
        if path == "/login":
            if self.command == "POST":
                self.sign_in()
            else:
                self.send((WEB / "login.html").read_bytes(), "text/html; charset=utf-8")
            return False
        if path == "/logout":
            self.send(b"", "text/plain", 303, {"Location": "/login", "Set-Cookie": self.cookie("", 0)})
            return False
        if self.signed_in():
            return True
        if path.startswith("/api/"):
            self.send({"error": "sign in first"}, code=401)
        else:
            self.send(b"", "text/plain", 303, {"Location": "/login"})
        return False

    def sign_in(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        given = (parse_qs(raw).get("password") or [""])[0]
        want = os.environ.get("SITE_PASSWORD", "")
        if want and hmac.compare_digest(given.encode(), want.encode()):
            log("auth", "signed in")
            return self.send(
                b"",
                "text/plain",
                303,
                {"Location": "/", "Set-Cookie": self.cookie(session_value(), SESSION_DAYS * 86400)},
            )
        log("auth", "a sign-in failed", "warn")
        time.sleep(1)  # slows guessing
        self.send(b"", "text/plain", 303, {"Location": "/login?error=1"})

    def cookie(self, value, max_age):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return f"{SESSION_COOKIE}={value}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=Lax{secure}"

    def static(self, rel):
        p = WEB / rel
        if not inside(WEB, p) or not p.is_file():
            return self.send({"error": "not found"}, code=404)
        return self.send(p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_GET(self):
        if not self.guard():
            return
        t0, self._code = time.time(), 200
        try:
            self.route_get()
        except Exception as e:  # keep the server up and put the error in the log
            log("error", f"GET {self.path}: {type(e).__name__}: {e}", "error")
            self.send({"error": f"{type(e).__name__}: {e}"}, code=500)
        path = urlparse(self.path).path
        if path.startswith("/api/") and not path.startswith(("/api/job/", "/api/logs")):
            log(
                "http",
                f"GET {unquote(self.path)}",
                "warn" if self._code >= 400 else "info",
                status=self._code,
                ms=round(1000 * (time.time() - t0)),
            )

    def route_get(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        parts = [unquote(p) for p in u.path.split("/") if p]
        if not parts:
            return self.static("index.html")
        if parts == ["legacy"]:
            return self.static("legacy.html")
        if parts[0] != "api":
            return self.static("/".join(parts))
        rooms = discover()
        if parts == ["api", "funds"]:
            out = []
            stamps, latest, catalogs = store.stamps_by_fund(), store.latest_summaries(), store.catalog_summaries()
            intakes, reviewed, decided = store.intakes(), disposition.latest_by_fund(), disposition.decided_on_by_fund()
            statuses, material = fund_status.current(), store.latest_material()
            for fid, room in sorted(rooms.items()):
                rs = stamps.get(fid, [])
                intake = intakes.get(fid) or dict.fromkeys(store.INTAKE_FIELDS)
                out.append(
                    {
                        "id": fid,
                        "name": room.name,
                        "path": room.path,
                        "runs": rs,
                        "latest": with_review(latest.get(fid), reviewed.get(fid)),
                        "catalog": catalogs.get(fid),
                        "status": statuses.get(fid) or fund_status.DEFAULT,
                        "actions": fund_actions(reviewed.get(fid)),
                        "material_on": material.get(fid),
                        "intake": intake,
                        "clock": screen_clock(intake, decided.get(fid, [])),
                    }
                )
            return self.send(out)
        if parts == ["api", "runs"]:
            return self.send(store.summaries())
        if parts == ["api", "analytics"]:
            return self.send(analytics())
        if parts[:2] == ["api", "status"] and len(parts) == 3:
            return self.send(fund_status.history(parts[2]))
        if parts == ["api", "agent"]:
            out = monitor.report()
            out["jobs"] = jobs.recent()
            return self.send(out)
        if parts == ["api", "reviewers"]:
            return self.send(review.reviewers())
        if parts == ["api", "policy", "history"]:
            return self.send(policy_store.history())
        if parts == ["api", "gates", "history"]:
            return self.send(gate_store.history(qs.get("file", [None])[0]))
        if parts == ["api", "config"]:
            gates = [
                {"file": g["file"], "text": g["text"], "parsed": yaml.safe_load(g["text"])}
                for g in gate_store.current()
            ]
            pol = store.policy()
            return self.send(
                {
                    "gates": gates,
                    "policy": {"id": pol["id"], "text": pol["yaml"], "parsed": yaml.safe_load(pol["yaml"])},
                }
            )
        if parts == ["api", "logs"]:
            recent = [{k: v for k, v in j.items() if k not in ("steps", "gates")} for j in jobs.recent()]
            return self.send({"events": jobs.events(), "jobs": recent})
        if parts == ["api", "meta"]:
            return self.send(
                {
                    "password": bool(session_key()),
                    "data_root": data().label,
                    "rooms": len(rooms),
                    "running": sum(j["status"] == "running" for j in jobs.recent(20)),
                }
            )
        if parts == ["api", "search"]:
            fund = qs.get("fund", [None])[0]
            return self.send(data().search(qs.get("q", [""])[0], only=fund if fund in rooms else None))
        if parts == ["api", "fs"]:
            v = qs.get("path", [""])[0].strip("/")
            entries = data().listing(v)
            if entries is None:
                return self.send({"error": "not a folder"}, code=404)
            return self.send({"path": v, "root": DATA_ROOT.name, "entries": entries})
        if parts == ["api", "raw"]:
            path = qs.get("path", [""])[0]
            found = data().file(path)
            if found is None:
                return self.send({"error": "not found"}, code=404)
            kind, where = found
            if kind == "url":  # hosted: the browser fetches the file from Storage with a short-lived link
                return self.send(b"", "text/plain", 302, {"Location": where})
            ctype = mimetypes.guess_type(where.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or where.suffix.lower() in TEXT_EXT:
                ctype = "text/plain; charset=utf-8"
            return self.send(
                where.read_bytes(), ctype, extra={"Content-Disposition": f'inline; filename="{slug(where.name)}"'}
            )
        if parts == ["api", "filepages"]:
            path = qs.get("path", [""])[0].lstrip("/")
            room = next((r for r in rooms.values() if path.startswith(r.path + "/")), None)
            if room is None:
                return self.send({"room": None, "pages": []})
            rel = path[len(room.path) + 1 :]
            pages = [{"page": x["page"], "text": x["text"]} for x in data().pages(room) if x["file"] == rel]
            return self.send({"room": room.name, "pages": pages})
        if parts[:2] == ["api", "run"] and len(parts) == 4:
            fid, stamp = parts[2], parts[3]
            found = store.run(fid, stamp)
            if found is None:
                return self.send({"error": "not found"}, code=404)
            room = rooms.get(fid)
            return self.send(
                {
                    **found,
                    "review": review.for_run(fid, stamp),
                    "decision": disposition.for_run(fid, stamp),
                    "room_path": room.path if room else None,
                }
            )
        if parts[:2] == ["api", "note"] and len(parts) == 4:
            return self.send(note.versions(parts[2], parts[3]))
        if parts[:2] == ["api", "job"] and len(parts) == 3:
            j = jobs.get(parts[2])
            return self.send(j) if j else self.send({"error": "unknown job"}, code=404)
        if parts[:2] == ["api", "catalog"] and len(parts) == 3:
            room = rooms.get(parts[2])
            if not room:
                return self.send({"error": "unknown fund"}, code=404)
            hit = store.catalog(parts[2])
            if hit is None:
                folder = data().folder(room)
                if folder is None:
                    return self.send({"error": "no catalog yet; scripts/upload_data_root.py builds it"}, code=404)
                log("catalog", f"building catalog for {room.name}")
                build_catalog(folder)
                hit = store.catalog(parts[2])
            summary, docs = hit
            return self.send({"summary": summary, "docs": docs, "room_path": room.path})
        if parts[:2] == ["api", "history"] and len(parts) == 3:
            return self.send(store.summaries(parts[2], newest_first=False))
        self.send({"error": "not found"}, code=404)

    def policy_write(self, method):
        parts = [unquote(p) for p in urlparse(self.path).path.split("/") if p]
        if parts[:2] != ["api", "policy"]:
            return False
        try:
            if method == "PUT" and parts == ["api", "policy"]:
                out = policy_store.save(self.body()["text"])
            elif method == "POST" and parts == ["api", "policy", "restore"]:
                out = policy_store.restore(self.body()["id"])
            elif method == "POST" and parts == ["api", "policy", "validate"]:
                try:
                    parsed = yaml.safe_load(self.body()["text"])
                except yaml.YAMLError as e:
                    return self.send({"errors": [f"YAML does not parse: {e}"], "warnings": []}) or True
                err, warn = policy_store.validate(parsed)
                out = {"errors": err, "warnings": warn, "policy": parsed}
            else:
                return self.send({"error": "not found"}, code=404) or True
        except (gate_store.GateError, KeyError, ValueError) as e:
            errors = e.errors if isinstance(e, gate_store.GateError) else [f"bad request: {e}"]
            return self.send({"error": "; ".join(errors), "errors": errors}, code=400) or True
        if parts[-1] != "validate":
            log("policy", f"{method} {'/'.join(parts[1:])}: {json.dumps(out)[:200]}")
        self.send(out)
        return True

    def gate_write(self, method):
        parts = [unquote(p) for p in urlparse(self.path).path.split("/") if p]
        if parts[:2] != ["api", "gates"]:
            return False
        try:
            if method == "POST" and parts == ["api", "gates"]:
                out = gate_store.create(self.body())
            elif method == "POST" and parts == ["api", "gates", "reorder"]:
                out = gate_store.reorder(self.body()["order"])
            elif method == "POST" and parts == ["api", "gates", "restore"]:
                out = gate_store.restore(self.body()["file"])
            elif method == "POST" and parts == ["api", "gates", "validate"]:
                b = self.body()
                try:
                    g = yaml.safe_load(b["text"]) if "text" in b else b["gate"]
                except yaml.YAMLError as e:
                    return self.send({"errors": [f"YAML does not parse: {e}"], "warnings": []}) or True
                err, warn = gate_store.validate(g, own_file=b.get("file"))
                out = {"errors": err, "warnings": warn, "gate": g}
            elif method == "PUT" and len(parts) == 3:
                out = gate_store.update(parts[2], self.body())
            elif method == "DELETE" and len(parts) == 3:
                out = gate_store.remove(parts[2])
            else:
                return self.send({"error": "not found"}, code=404) or True
        except gate_store.GateError as e:
            return self.send({"error": str(e), "errors": e.errors}, code=400) or True
        if parts[-1] != "validate":
            log("gates", f"{method} {'/'.join(parts[2:]) or 'new gate'}: {json.dumps(out)[:200]}")
        self.send(out)
        return True

    def intake_write(self):
        parts = [unquote(p) for p in urlparse(self.path).path.split("/") if p]
        if parts[:2] != ["api", "intake"] or len(parts) != 3:
            return False
        if parts[2] not in discover():
            return self.send({"error": "unknown fund"}, code=404) or True
        try:
            out = store.save_intake(parts[2], self.body())
        except ValueError as e:
            return self.send({"error": str(e)}, code=400) or True
        log("intake", f"saved intake for {parts[2]}: {json.dumps(out)[:200]}")
        self.send(out)
        return True

    def review_write(self):
        """Reviewers, gate reviews and manual-check answers. Each answer is a new row, never an edit."""
        path = urlparse(self.path).path
        parts = [unquote(p) for p in path.split("/") if p]
        is_note = parts[:2] == ["api", "note"] and len(parts) == 4
        if (
            path not in ("/api/reviewers", "/api/review", "/api/check", "/api/disposition", "/api/status")
            and not is_note
        ):
            return False
        b = self.body()
        try:
            if is_note:
                fid, stamp = parts[2], parts[3]
                out = (
                    note.draft(fid, stamp)
                    if b.get("draft")
                    else note.edit(fid, stamp, b.get("body"), b.get("reviewer"))
                )
            elif path == "/api/reviewers":
                out = review.save_reviewer(b)
            elif path == "/api/status":
                if b.get("fund") not in discover():
                    raise review.ReviewError("unknown fund")
                out = fund_status.set_status(b.get("fund"), b.get("status"), b.get("reviewer"), b.get("note"))
            elif path == "/api/disposition":
                out = disposition.confirm(b.get("fund"), b.get("run"), b.get("reviewer"), b.get("reason"))
            elif path == "/api/review":
                out = review.add_review(
                    b.get("fund"), b.get("run"), b.get("gate"), b.get("reviewer"), b.get("verdict"),
                    b.get("reason"), b.get("result"), b.get("document"), b.get("page"),
                )  # fmt: skip
            else:
                out = review.add_check(
                    b.get("fund"), b.get("run"), b.get("gate"), b.get("check"), b.get("ok"), b.get("reviewer"),
                    b.get("note"),
                )  # fmt: skip
        except review.ReviewError as e:
            return self.send({"error": str(e)}, code=400) or True
        log("review", f"POST {path[5:]}: {json.dumps(b)[:200]}")
        self.send(out)
        return True

    def do_PUT(self):
        if not self.guard():
            return
        if not (self.policy_write("PUT") or self.gate_write("PUT") or self.intake_write()):
            self.send({"error": "not found"}, code=404)

    def do_DELETE(self):
        if not self.guard():
            return
        if not self.gate_write("DELETE"):
            self.send({"error": "not found"}, code=404)

    def do_POST(self):
        if not self.guard():
            return
        if self.policy_write("POST") or self.gate_write("POST") or self.review_write():
            return
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if parts[:2] == ["api", "catalog"] and len(parts) == 4 and parts[3] == "rebuild":
            room = discover().get(parts[2])
            if not room:
                return self.send({"error": "unknown fund"}, code=404)
            folder = data().folder(room)
            if folder is None:
                return self.send({"error": "catalogs are rebuilt by scripts/upload_data_root.py here"}, code=409)
            try:
                build_catalog(folder)
            except Exception as e:
                log("catalog", f"rebuild failed for {room.name}: {e}", "error")
                return self.send({"error": f"{type(e).__name__}: {e}"}, code=500)
            log("catalog", f"rebuilt catalog for {room.name}")
            return self.send({"ok": True})
        if parts == ["api", "screen"]:
            return self.queue_screen()
        if parts[:2] == ["api", "screen"] and len(parts) == 4 and parts[3] == "run":
            return self.run_screen(parts[2])
        return self.send({"error": "not found"}, code=404)

    def queue_screen(self):
        """Ask for a screen: a queued job the browser then runs with POST /api/screen/<job>/run."""
        body = self.body()
        room = discover().get(body.get("fund"))
        if not room:
            return self.send({"error": "unknown fund"}, code=404)
        ex, jd = body.get("extractor", "claude"), body.get("judge", "jev")
        jid = jobs.create(body["fund"], room.name, ex, jd, [g["id"] for g in load_gates()])
        log("job", f"screen queued: {room.name} (extractor {ex}, judge {jd})", job=jid)
        self.send({"job": jid})

    def run_screen(self, jid):
        """Run a queued screen inside this request (no background thread: a serverless function stops when
        its response is sent), writing each step to the job as it goes. The browser polls the job."""
        job = jobs.claim(jid)
        if not job:
            return self.send({"error": "unknown job, or already started"}, code=409)
        room = discover().get(job["fund_id"])
        tr = Tracker(on_change=lambda steps: jobs.progress(jid, steps))
        try:
            if not room:
                raise LookupError(f"no data room {job['fund_id']}")
            _, summary, _ = run(data().data_room(room), job["extractor"], job["judge"], tracker=tr)
        except (SystemExit, Exception) as e:  # missing key, API errors
            error = str(e) or type(e).__name__
            jobs.finish(jid, tr.steps, error=error)
            log("job", f"screen failed: {job['fund_id']}: {error}", "error", job=jid)
            return self.send({"status": "error", "error": error})
        jobs.finish(jid, tr.steps, run_stamp=summary["run"])
        log("job", f"screen finished: {summary['fund']}: {summary['disposition']}", job=jid, run=summary["run"])
        self.send({"status": "done", "run": summary["run"]})

    def log_message(self, *a):
        pass


class WsgiRequest(H):
    """One WSGI request through the same handler, with no socket: how Vercel runs the console. Everything
    the handler answers goes through send(), which this captures instead of writing to a connection."""

    def __init__(self, environ):  # deliberately not BaseHTTPRequestHandler's, which serves a socket
        self.command = environ["REQUEST_METHOD"]
        path = (environ.get("PATH_INFO") or "/").encode("latin-1").decode("utf-8", "replace")  # PEP 3333
        qs = environ.get("QUERY_STRING")
        self.path = quote(path) + (f"?{qs}" if qs else "")
        self.headers = Message()
        for k, v in environ.items():
            if k.startswith("HTTP_"):
                self.headers[k[5:].replace("_", "-").title()] = v
        for k in ("CONTENT_LENGTH", "CONTENT_TYPE"):
            if environ.get(k):
                self.headers[k.replace("_", "-").title()] = environ[k]
        self.rfile = environ["wsgi.input"]
        self.reply: tuple[int, str, bytes, dict] = (500, "application/json", b'{"error": "no response"}', {})

    def send(self, body, ctype="application/json", code=200, extra=None):
        self._code = code
        self.reply = (code, ctype, body if isinstance(body, bytes) else json.dumps(body).encode(), extra or {})


def app(environ, start_response):
    req = WsgiRequest(environ)
    handler = getattr(req, f"do_{req.command}", None)
    if handler is None:
        req.send({"error": "method not allowed"}, code=405)
    else:
        handler()
    code, ctype, data, extra = req.reply
    headers = [("Content-Type", ctype), ("Content-Length", str(len(data))), ("Cache-Control", "no-store")]
    start_response(f"{code} {HTTPStatus(code).phrase}", headers + list(extra.items()))
    return [data]


if __name__ == "__main__":
    if len(sys.argv) > 1:
        DATA_ROOT = Path(sys.argv[1]).resolve()
    log("server", f"started, data root {DATA_ROOT}")
    port = int(os.environ.get("PORT", 8765))
    print(f"http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
