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
from sg import clock, disposition, gate_store, monitor, note, pipeline_md, policy_store, review, store  # noqa: E402
from sg.catalog import build as build_catalog  # noqa: E402
from sg.pipeline import ROOT, Tracker, load_gates, run  # noqa: E402

JOBS: dict[str, dict] = {}
LOG: collections.deque[dict] = collections.deque(maxlen=1000)  # in-memory event log, newest last
WEB = ROOT / "web"

DATA_ROOT = Path(
    sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RWP_DATA_ROOT", str(Path.home() / "Desktop/RWP"))
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


# ---------- one file tree over the Drive download parts ----------
# A large Drive download arrives as RWP-<stamp>-1-001, -002, ... each holding part of the same RWP/ tree.
# The Files view lays the parts over each other so the analyst sees one RWP/ folder. Nothing on disk moves.

DRIVE_PART = re.compile(r".+-\d{8}T\d{6}Z-\d+-\d{3}$")


def layers():
    parts = [p for p in sorted(DATA_ROOT.iterdir()) if p.is_dir() and DRIVE_PART.match(p.name)]
    if not parts:
        return [DATA_ROOT]
    out = []
    for p in parts:
        kids = [c for c in p.iterdir() if c.is_dir() and not c.name.startswith(".")]
        out.append(kids[0] if len(kids) == 1 and not any(c.is_file() for c in p.iterdir()) else p)
    return out


def to_virtual(rel):
    """Real path (relative to the data root) -> path inside the merged tree."""
    p = (DATA_ROOT / rel).resolve()
    for layer in layers():
        if p.is_relative_to(layer.resolve()):
            v = p.relative_to(layer.resolve())
            return "" if str(v) == "." else str(v)
    return rel


def real_candidates(v):
    return [layer / v for layer in layers() if inside(layer, layer / v) and (layer / v).exists()]


def merged_listing(v):
    entries: dict[str, dict] = {}
    for d in real_candidates(v):
        if not d.is_dir():
            continue
        for c in d.iterdir():
            if c.name.startswith(".") or c.name == "_index":
                continue
            st = c.stat()
            e = entries.get(c.name)
            room = c.is_dir() and (c / "_index" / "pages.jsonl").exists()
            if e:  # the same folder in more than one part
                e["parts"] += 1
                e["mtime"] = max(e["mtime"], st.st_mtime)
                e["room"] = e["room"] or room
                continue
            entries[c.name] = {
                "name": c.name,
                "dir": c.is_dir(),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "path": f"{v}/{c.name}" if v else c.name,
                "real": str(c.relative_to(DATA_ROOT)),
                "room": room,
                "parts": 1,
            }
    return sorted(entries.values(), key=lambda e: (not e["dir"], e["name"].lower()))


# ---------- pipeline (tables in PIPELINE.md) ----------
# The console reads every row and writes a fund's screen results into its own row (decision G3), never its Status.
# RWP_PIPELINE_WRITE=0 turns the writing off.

PIPELINE_WRITE = os.environ.get("RWP_PIPELINE_WRITE", "1") != "0"
STATE_WORDS = {
    "draft": "draft",
    "confirmed": "confirmed",
    "awaiting_signoff": "awaiting CIO sign-off",
    "signed_off": "signed off",
}


def pipeline_file():
    return next(iter(sorted(DATA_ROOT.rglob("PIPELINE.md"))), None)


def parse_pipeline():
    src = pipeline_file()
    if not src:
        return {"source": None, "updated": None, "sections": []}
    return {"source": str(src.relative_to(DATA_ROOT)), **pipeline_md.parse(src.read_text(errors="replace"))}


match_pipeline = pipeline_md.match


def pipeline_values(fid):
    """The cells the tool owns in a fund's row. Next action always says who acts next, so it never goes stale."""
    intake = store.intake(fid)
    values = {
        "Owner": intake["owner"],
        "Referred by": intake["referred_by"],
        "Sponsor deadline": intake["sponsor_deadline"],
    }
    clk = screen_clock(intake, disposition.decided_on_by_fund().get(fid, []))
    if clk:
        values["Screen due"] = clk["due"]
    latest = disposition.latest_by_fund().get(fid)
    if latest:
        d, r = latest["decision"], latest["run"]
        values["Last action"] = (
            f"Screened {r[:4]}-{r[4:6]}-{r[6:8]}: {d['disposition'].split(' (')[0]} ({STATE_WORDS[d['state']]})"
        )
        if d["blockers"]:
            values["Next action"] = "Analyst to " + "; ".join(d["blockers"])
        elif d["state"] == "awaiting_signoff":
            values["Next action"] = "CIO sign-off"
        elif d["state"] == "draft":
            values["Next action"] = "Confirm the disposition"
        elif d["disposition"].startswith("Under review"):
            values["Next action"] = "Manager to provide the requested documents"
        else:
            values["Next action"] = "CIO to update the status"
    return values


def sync_pipeline(fid):
    """Write the fund's results into its PIPELINE.md row. A failure is logged, never raised: the database
    already holds the result."""
    folder, src = discover().get(fid), pipeline_file()
    if not PIPELINE_WRITE or not folder or not src:
        return
    try:
        written = pipeline_md.write(src, folder.name, pipeline_values(fid), date.today().isoformat())
    except Exception as e:
        log("pipeline", f"could not update PIPELINE.md for {folder.name}: {type(e).__name__}: {e}", "error")
        return
    if written:
        log("pipeline", f"PIPELINE.md row for {folder.name}: {', '.join(written)}")


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
        rel = qs.get("path", [""])[0].lstrip("/")
        p = DATA_ROOT / rel
        if inside(DATA_ROOT, p) and p.exists():
            return p
        hits = real_candidates(rel)  # a path in the merged tree
        return hits[0] if hits else None

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
            pipe = [r for s in parse_pipeline()["sections"] for r in s["rows"]]
            out = []
            stamps, latest, catalogs = store.stamps_by_fund(), store.latest_summaries(), store.catalog_summaries()
            intakes, reviewed, decided = store.intakes(), disposition.latest_by_fund(), disposition.decided_on_by_fund()
            for fid, folder in sorted(rooms.items()):
                rs = stamps.get(fid, [])
                rel = folder.relative_to(DATA_ROOT)
                intake = intakes.get(fid) or dict.fromkeys(store.INTAKE_FIELDS)
                out.append(
                    {
                        "id": fid,
                        "name": folder.name,
                        "path": str(rel),
                        "vpath": to_virtual(str(rel)),
                        "stage": next((p for p in rel.parts if re.match(r"\d-", p)), None),
                        "runs": rs,
                        "latest": with_review(latest.get(fid), reviewed.get(fid)),
                        "catalog": catalogs.get(fid),
                        "pipeline": match_pipeline(folder.name, pipe),
                        "intake": intake,
                        "clock": screen_clock(intake, decided.get(fid, [])),
                    }
                )
            return self.send(out)
        if parts == ["api", "runs"]:
            return self.send(store.summaries())
        if parts == ["api", "analytics"]:
            return self.send(analytics())
        if parts == ["api", "pipeline"]:
            return self.send(parse_pipeline())
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
            v = to_virtual(qs.get("path", [""])[0].strip("/"))
            if v and not any(d.is_dir() for d in real_candidates(v)):
                return self.send({"error": "not a folder"}, code=404)
            return self.send(
                {
                    "path": v,
                    "root": layers()[0].name if len(layers()) > 1 else DATA_ROOT.name,
                    "parts": len(layers()),
                    "entries": merged_listing(v),
                }
            )
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
        sync_pipeline(parts[2])
        self.send(out)
        return True

    def review_write(self):
        """Reviewers, gate reviews and manual-check answers. Each answer is a new row, never an edit."""
        path = urlparse(self.path).path
        parts = [unquote(p) for p in path.split("/") if p]
        is_note = parts[:2] == ["api", "note"] and len(parts) == 4
        if path not in ("/api/reviewers", "/api/review", "/api/check", "/api/disposition") and not is_note:
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
        if path in ("/api/review", "/api/check", "/api/disposition"):
            sync_pipeline(b.get("fund"))
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
                sync_pipeline(body["fund"])
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
