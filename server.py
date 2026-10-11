#!/usr/bin/env python3
"""Local analyst console. [PORT=8765] python3 server.py [data-root] -> http://127.0.0.1:8765"""

import collections
import json
import mimetypes
import os
import re
import sys
import threading
import time
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sg import clock, disposition, fund_status, gate_store, monitor, note, policy_store, review, store  # noqa: E402
from sg.catalog import build as build_catalog  # noqa: E402
from sg.pipeline import ROOT, Tracker, load_gates, run  # noqa: E402

JOBS: dict[str, dict] = {}
LOG: collections.deque[dict] = collections.deque(maxlen=1000)  # in-memory event log, newest last
WEB = ROOT / "web"

DATA_ROOT = Path(
    sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RWP_DATA_ROOT", str(Path.home() / "Desktop/RWP-funds"))
).resolve()
slug = lambda n: re.sub(r"[^\w.-]+", "_", n)
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
TEXT_EXT = (".md", ".csv", ".json", ".yaml", ".yml", ".txt", ".jsonl")


def log(kind, msg, level="info", **extra):
    LOG.append({"t": time.time(), "kind": kind, "level": level, "msg": msg, **extra})


def discover():
    rooms = {}
    for idx in DATA_ROOT.rglob("_index/pages.jsonl"):
        folder = idx.parent.parent
        rooms[slug(folder.name)] = folder
    return rooms


def inside(base, p):
    try:
        return p.resolve().is_relative_to(base.resolve())
    except OSError:
        return False


# ---------- the file tree ----------
# The data root is one folder per fund, holding only what the fund sent (scripts/reorganize_data_root.py builds
# it from a Drive download). Folder names inside a fund are kept as they are and mean nothing to the console.


def listing(v):
    """The entries of folder v (relative to the data root), folders first, or None if it is not one."""
    d = DATA_ROOT / v
    if not inside(DATA_ROOT, d) or not d.is_dir():
        return None
    out = []
    for c in d.iterdir():
        if c.name.startswith(".") or c.name == "_index":
            continue
        st = c.stat()
        path = f"{v}/{c.name}" if v else c.name
        out.append(
            {
                "name": c.name,
                "dir": c.is_dir(),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "path": path,
                "real": path,
                "room": c.is_dir() and (c / "_index" / "pages.jsonl").exists(),
            }
        )
    return sorted(out, key=lambda e: (not e["dir"], e["name"].lower()))


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


# ---------- full-text search over indexed pages (lazy, mtime-cached) ----------

_PAGES: dict[Path, tuple[float, list[dict]]] = {}


def room_pages(folder):
    idx = folder / "_index" / "pages.jsonl"
    m = idx.stat().st_mtime
    hit = _PAGES.get(idx)
    if not hit or hit[0] != m:
        hit = (m, [json.loads(line) for line in idx.open()])
        _PAGES[idx] = hit
    return hit[1]


def search(q, rooms, limit=80):
    terms = [t for t in re.findall(r"\w+", q.lower()) if len(t) > 1]
    if not terms:
        return []
    named, out = [], []
    for fid, folder in rooms.items():
        pages = room_pages(folder)
        # Evidence cites a file by name or path, words that rarely appear on its pages, so match those too.
        firsts: dict[str, dict] = {}
        for p in pages:
            firsts.setdefault(p["file"], p)
        for rel, p in firsts.items():
            if all(term in rel.lower() for term in terms):
                named.append(
                    {
                        "fund": fid,
                        "room": folder.name,
                        "file": rel,
                        "page": p["page"],
                        "path": str((folder / rel).relative_to(DATA_ROOT)),
                        "snippet": re.sub(r"\s+", " ", p["text"][:320]).strip(),
                        "score": 0,
                        "by_name": True,
                    }
                )
        for p in pages:
            t = p["text"].lower()
            if all(term in t for term in terms):
                i = t.find(terms[0])
                snip = re.sub(r"\s+", " ", p["text"][max(0, i - 120) : i + 200]).strip()
                out.append(
                    {
                        "fund": fid,
                        "room": folder.name,
                        "file": p["file"],
                        "page": p["page"],
                        "path": str((folder / p["file"]).relative_to(DATA_ROOT)),
                        "snippet": snip,
                        "score": sum(t.count(term) for term in terms),
                    }
                )
    out.sort(key=lambda r: -r["score"])
    return (named + out)[:limit]


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

    def static(self, rel):
        p = WEB / rel
        if not inside(WEB, p) or not p.is_file():
            return self.send({"error": "not found"}, code=404)
        return self.send(p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")

    def data_path(self, qs):
        p = DATA_ROOT / qs.get("path", [""])[0].lstrip("/")
        return p if inside(DATA_ROOT, p) and p.exists() else None

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_GET(self):
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
            for fid, folder in sorted(rooms.items()):
                rs = stamps.get(fid, [])
                rel = folder.relative_to(DATA_ROOT)
                intake = intakes.get(fid) or dict.fromkeys(store.INTAKE_FIELDS)
                out.append(
                    {
                        "id": fid,
                        "name": folder.name,
                        "path": str(rel),
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
            out["jobs"] = [
                {
                    "id": k,
                    "fund": j["fund"],
                    "fund_id": j["fund_id"],
                    "status": j["status"],
                    "started": j["started"],
                    "extractor": j["extractor"],
                    "judge": j["judge"],
                    "elapsed": round(time.time() - j["tr"].t0, 1) if j["status"] == "running" else j.get("seconds"),
                    "run": j.get("run"),
                    "error": j.get("error"),
                    "steps": list(j["tr"].steps),
                }
                for k, j in JOBS.items()
            ][::-1]
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
            jobs = [
                {
                    "id": k,
                    "fund": j["fund"],
                    "fund_id": j["fund_id"],
                    "status": j["status"],
                    "started": j["started"],
                    "extractor": j["extractor"],
                    "judge": j["judge"],
                    "elapsed": round(time.time() - j["tr"].t0, 1) if j["status"] == "running" else j.get("seconds"),
                    "run": j.get("run"),
                    "error": j.get("error"),
                }
                for k, j in JOBS.items()
            ]
            return self.send({"events": list(LOG), "jobs": jobs[::-1]})
        if parts == ["api", "meta"]:
            return self.send(
                {
                    "data_root": str(DATA_ROOT),
                    "rooms": len(rooms),
                    "running": sum(j["status"] == "running" for j in JOBS.values()),
                }
            )
        if parts == ["api", "search"]:
            fund = qs.get("fund", [None])[0]
            return self.send(search(qs.get("q", [""])[0], {fund: rooms[fund]} if fund in rooms else rooms))
        if parts == ["api", "fs"]:
            v = qs.get("path", [""])[0].strip("/")
            entries = listing(v)
            if entries is None:
                return self.send({"error": "not a folder"}, code=404)
            return self.send({"path": v, "root": DATA_ROOT.name, "entries": entries})
        if parts == ["api", "raw"]:
            p = self.data_path(qs)
            if p is None or not p.is_file():
                return self.send({"error": "not found"}, code=404)
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or p.suffix.lower() in TEXT_EXT:
                ctype = "text/plain; charset=utf-8"
            return self.send(p.read_bytes(), ctype, extra={"Content-Disposition": f'inline; filename="{slug(p.name)}"'})
        if parts == ["api", "filepages"]:
            p = self.data_path(qs)
            if p is None:
                return self.send({"error": "not found"}, code=404)
            for folder in rooms.values():
                if inside(folder, p):
                    rel = str(p.relative_to(folder))
                    pages = [{"page": x["page"], "text": x["text"]} for x in room_pages(folder) if x["file"] == rel]
                    return self.send({"room": folder.name, "pages": pages})
            return self.send({"room": None, "pages": []})
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
                    "room_path": str(room.relative_to(DATA_ROOT)) if room else None,
                }
            )
        if parts[:2] == ["api", "note"] and len(parts) == 4:
            return self.send(note.versions(parts[2], parts[3]))
        if parts[:2] == ["api", "job"] and len(parts) == 3:
            j = JOBS.get(parts[2])
            if not j:
                return self.send({"error": "unknown job"}, code=404)
            return self.send(
                {
                    "status": j["status"],
                    "run": j.get("run"),
                    "error": j.get("error"),
                    "elapsed": round(time.time() - j["tr"].t0, 2),
                    "gates": j["gates"],
                    "steps": list(j["tr"].steps),
                }
            )
        if parts[:2] == ["api", "catalog"] and len(parts) == 3:
            folder = rooms.get(parts[2])
            if not folder:
                return self.send({"error": "unknown fund"}, code=404)
            hit = store.catalog(parts[2])
            if hit is None:
                log("catalog", f"building catalog for {folder.name}")
                build_catalog(folder)
                hit = store.catalog(parts[2])
            summary, docs = hit
            return self.send({"summary": summary, "docs": docs, "room_path": str(folder.relative_to(DATA_ROOT))})
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
        if not (self.policy_write("PUT") or self.gate_write("PUT") or self.intake_write()):
            self.send({"error": "not found"}, code=404)

    def do_DELETE(self):
        if not self.gate_write("DELETE"):
            self.send({"error": "not found"}, code=404)

    def do_POST(self):
        if self.policy_write("POST") or self.gate_write("POST") or self.review_write():
            return
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if parts[:2] == ["api", "catalog"] and len(parts) == 4 and parts[3] == "rebuild":
            folder = discover().get(parts[2])
            if not folder:
                return self.send({"error": "unknown fund"}, code=404)
            try:
                build_catalog(folder)
            except Exception as e:
                log("catalog", f"rebuild failed for {folder.name}: {e}", "error")
                return self.send({"error": f"{type(e).__name__}: {e}"}, code=500)
            log("catalog", f"rebuilt catalog for {folder.name}")
            return self.send({"ok": True})
        if urlparse(self.path).path != "/api/screen":
            return self.send({"error": "not found"}, code=404)
        body = self.body()
        folder = discover().get(body.get("fund"))
        if not folder:
            return self.send({"error": "unknown fund"}, code=404)
        tr = Tracker()
        ex, jd = body.get("extractor", "claude"), body.get("judge", "jev")
        job = {
            "status": "running",
            "tr": tr,
            "gates": [g["id"] for g in load_gates()],
            "fund": folder.name,
            "fund_id": body["fund"],
            "extractor": ex,
            "judge": jd,
            "started": time.time(),
        }
        jid = uuid.uuid4().hex[:10]
        JOBS[jid] = job
        log("job", f"screen started: {folder.name} (extractor {ex}, judge {jd})", job=jid)

        def work():
            try:
                _, summary, _ = run(folder, ex, jd, tracker=tr)
                job.update(status="done", run=summary["run"], seconds=summary.get("seconds"))
                log("job", f"screen finished: {folder.name}: {summary['disposition']}", job=jid, run=summary["run"])
            except (SystemExit, Exception) as e:  # missing key, API errors
                job.update(status="error", error=str(e) or type(e).__name__, seconds=round(time.time() - tr.t0, 1))
                log("job", f"screen failed: {folder.name}: {job['error']}", "error", job=jid)

        threading.Thread(target=work, daemon=True).start()
        self.send({"job": jid})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    log("server", f"started, data root {DATA_ROOT}")
    port = int(os.environ.get("PORT", 8765))
    print(f"http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
