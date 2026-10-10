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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sg.catalog import build as build_catalog  # noqa: E402
from sg import gate_store, monitor  # noqa: E402
from sg.pipeline import ROOT, Tracker, load_gates, run  # noqa: E402

JOBS = {}
LOG = collections.deque(maxlen=1000)  # in-memory event log, newest last
WEB = ROOT / "web"
RUNS = ROOT / "runs"

DATA_ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RWP_DATA_ROOT", str(Path.home() / "Desktop/RWP"))).resolve()
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


def runs_for(fid):
    d = RUNS / fid
    return sorted([p.name for p in d.iterdir() if p.is_dir()], reverse=True) if d.exists() else []


def read_json(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


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
    entries = {}
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
            entries[c.name] = {"name": c.name, "dir": c.is_dir(), "size": st.st_size, "mtime": st.st_mtime,
                               "path": f"{v}/{c.name}" if v else c.name,
                               "real": str(c.relative_to(DATA_ROOT)), "room": room, "parts": 1}
    return sorted(entries.values(), key=lambda e: (not e["dir"], e["name"].lower()))


# ---------- pipeline (tables in PIPELINE.md, read-only) ----------

def parse_pipeline():
    src = next(iter(sorted(DATA_ROOT.rglob("PIPELINE.md"))), None)
    if not src:
        return {"source": None, "updated": None, "sections": []}
    text = src.read_text(errors="replace")
    sections, cur, header = [], None, None
    for line in text.splitlines():
        if line.startswith("## "):
            cur, header = {"title": line[3:].strip(), "rows": []}, None
            sections.append(cur)
        elif line.startswith("|") and cur is not None:
            cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
            if header is None:
                header = cells
            elif not all(set(c) <= set("-: ") for c in cells):
                cur["rows"].append(dict(zip(header, cells)))
        else:
            header = None
    upd = re.search(r"Last updated:\s*(\S+)", text)
    return {"source": str(src.relative_to(DATA_ROOT)), "updated": upd and upd.group(1),
            "sections": [s for s in sections if s["rows"]]}


def match_pipeline(name, rows):
    """Folder 'Manager - Strategy' -> the pipeline row for that manager with the most strategy words in common."""
    mgr, _, strat = name.partition(" - ")
    words = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))
    best, score = None, -1
    for r in rows:
        m = words(r.get("Manager", ""))
        if m and m <= words(mgr) | words(name):
            s = len(words(strat) & words(r.get("Strategy", "")))
            if s > score:
                best, score = r, s
    return best


# ---------- full-text search over indexed pages (lazy, mtime-cached) ----------

_PAGES = {}


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
    out = []
    for fid, folder in rooms.items():
        for p in room_pages(folder):
            t = p["text"].lower()
            if all(term in t for term in terms):
                i = t.find(terms[0])
                snip = re.sub(r"\s+", " ", p["text"][max(0, i - 120): i + 200]).strip()
                out.append({"fund": fid, "room": folder.name, "file": p["file"], "page": p["page"],
                            "path": str((folder / p["file"]).relative_to(DATA_ROOT)),
                            "snippet": snip, "score": sum(t.count(term) for term in terms)})
    out.sort(key=lambda r: -r["score"])
    return out[:limit]


# ---------- analytics over every logged run ----------

def all_runs():
    out = []
    if not RUNS.exists():
        return out
    for fdir in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        for rdir in sorted(p for p in fdir.iterdir() if p.is_dir()):
            s = read_json(rdir / "summary.json")
            if s:
                out.append(dict(s, fund_id=fdir.name))
    out.sort(key=lambda s: s["run"], reverse=True)
    return out


def analytics():
    """One row per gate per run: result, confidence, evidence counts, tokens, step seconds."""
    rows = []
    for s in all_runs():
        for gp in sorted((RUNS / s["fund_id"] / s["run"] / "gates").glob("*.json")):
            g = read_json(gp) or {}
            b = g.get("brief") or {}
            usage = ((g.get("answers") or {}).get("_meta") or {}).get("usage") or {}
            steps = {e["step"]: round((e["end"] if e["end"] is not None else e["start"]) - e["start"], 3)
                     for e in g.get("timeline") or []}
            rows.append({"fund": s["fund"], "fund_id": s["fund_id"], "run": s["run"],
                         "extractor": s.get("extractor"), "judge": s.get("judge"),
                         "gate": g.get("gate", gp.stem), "result": g.get("result"),
                         "review": bool(g.get("review")), "min_confidence": g.get("min_confidence"),
                         "facts": len(b.get("facts") or []), "rejected": len(g.get("rejected") or []),
                         "not_found": len(b.get("not_found") or []),
                         "pages_offered": len(g.get("pages_offered") or []),
                         "tokens_in": usage.get("input_tokens", 0), "tokens_out": usage.get("output_tokens", 0),
                         "steps": steps})
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
            log("http", f"GET {unquote(self.path)}", "warn" if self._code >= 400 else "info",
                status=self._code, ms=round(1000 * (time.time() - t0)))

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
            for fid, folder in sorted(rooms.items()):
                rs = runs_for(fid)
                rel = folder.relative_to(DATA_ROOT)
                out.append({"id": fid, "name": folder.name, "path": str(rel), "vpath": to_virtual(str(rel)),
                            "stage": next((p for p in rel.parts if re.match(r"\d-", p)), None),
                            "runs": rs, "latest": read_json(RUNS / fid / rs[0] / "summary.json") if rs else None,
                            "catalog": read_json(ROOT / "catalog" / fid / "summary.json"),
                            "pipeline": match_pipeline(folder.name, pipe)})
            return self.send(out)
        if parts == ["api", "runs"]:
            return self.send(all_runs())
        if parts == ["api", "analytics"]:
            return self.send(analytics())
        if parts == ["api", "pipeline"]:
            return self.send(parse_pipeline())
        if parts == ["api", "agent"]:
            out = monitor.report()
            out["jobs"] = [{"id": k, "fund": j["fund"], "fund_id": j["fund_id"], "status": j["status"],
                            "started": j["started"], "extractor": j["extractor"], "judge": j["judge"],
                            "elapsed": round(time.time() - j["tr"].t0, 1) if j["status"] == "running" else j.get("seconds"),
                            "run": j.get("run"), "error": j.get("error"), "steps": list(j["tr"].steps)} for k, j in JOBS.items()][::-1]
            return self.send(out)
        if parts == ["api", "gates", "history"]:
            return self.send(gate_store.history(qs.get("file", [None])[0]))
        if parts == ["api", "config"]:
            gates = [{"file": p.name, "text": p.read_text(), "parsed": yaml.safe_load(p.read_text())}
                     for p in gate_store.files()]
            pol = (ROOT / "policy.yaml").read_text()
            return self.send({"gates": gates, "policy": {"text": pol, "parsed": yaml.safe_load(pol)}})
        if parts == ["api", "logs"]:
            jobs = [{"id": k, "fund": j["fund"], "fund_id": j["fund_id"], "status": j["status"], "started": j["started"],
                     "extractor": j["extractor"], "judge": j["judge"],
                     "elapsed": round(time.time() - j["tr"].t0, 1) if j["status"] == "running" else j.get("seconds"),
                     "run": j.get("run"), "error": j.get("error")} for k, j in JOBS.items()]
            return self.send({"events": list(LOG), "jobs": jobs[::-1]})
        if parts == ["api", "meta"]:
            return self.send({"data_root": str(DATA_ROOT), "rooms": len(rooms),
                              "running": sum(j["status"] == "running" for j in JOBS.values())})
        if parts == ["api", "search"]:
            fund = qs.get("fund", [None])[0]
            return self.send(search(qs.get("q", [""])[0], {fund: rooms[fund]} if fund in rooms else rooms))
        if parts == ["api", "fs"]:
            v = to_virtual(qs.get("path", [""])[0].strip("/"))
            if v and not any(d.is_dir() for d in real_candidates(v)):
                return self.send({"error": "not a folder"}, code=404)
            return self.send({"path": v, "root": layers()[0].name if len(layers()) > 1 else DATA_ROOT.name,
                              "parts": len(layers()), "entries": merged_listing(v)})
        if parts == ["api", "raw"]:
            p = self.data_path(qs)
            if p is None or not p.is_file():
                return self.send({"error": "not found"}, code=404)
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or p.suffix.lower() in TEXT_EXT:
                ctype = "text/plain; charset=utf-8"
            return self.send(p.read_bytes(), ctype,
                             extra={"Content-Disposition": f'inline; filename="{slug(p.name)}"'})
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
            base = RUNS / fid / stamp
            if not inside(RUNS, base) or not base.exists():
                return self.send({"error": "not found"}, code=404)
            summary = json.loads((base / "summary.json").read_text())
            gates = [json.loads(p.read_text()) for p in sorted((base / "gates").glob("*.json"))]
            md = base / "summary.md"
            room = rooms.get(fid)
            return self.send({"summary": summary, "gates": gates, "markdown": md.read_text() if md.exists() else "",
                              "room_path": str(room.relative_to(DATA_ROOT)) if room else None})
        if parts[:2] == ["api", "job"] and len(parts) == 3:
            j = JOBS.get(parts[2])
            if not j:
                return self.send({"error": "unknown job"}, code=404)
            return self.send({"status": j["status"], "run": j.get("run"), "error": j.get("error"),
                              "elapsed": round(time.time() - j["tr"].t0, 2),
                              "gates": j["gates"], "steps": list(j["tr"].steps)})
        if parts[:2] == ["api", "catalog"] and len(parts) == 3:
            folder = rooms.get(parts[2])
            if not folder:
                return self.send({"error": "unknown fund"}, code=404)
            base = ROOT / "catalog" / parts[2]
            if not (base / "documents.jsonl").exists():
                log("catalog", f"building catalog for {folder.name}")
                build_catalog(folder)
            docs = [json.loads(line) for line in (base / "documents.jsonl").open()]
            return self.send({"summary": json.loads((base / "summary.json").read_text()), "docs": docs,
                              "room_path": str(folder.relative_to(DATA_ROOT))})
        if parts[:2] == ["api", "history"] and len(parts) == 3:
            rows = []
            for stamp in sorted(runs_for(parts[2])[::-1]):
                rows.append(json.loads((RUNS / parts[2] / stamp / "summary.json").read_text()))
            return self.send(rows)
        self.send({"error": "not found"}, code=404)

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

    def do_PUT(self):
        if not self.gate_write("PUT"):
            self.send({"error": "not found"}, code=404)

    def do_DELETE(self):
        if not self.gate_write("DELETE"):
            self.send({"error": "not found"}, code=404)

    def do_POST(self):
        if self.gate_write("POST"):
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
        job = {"status": "running", "tr": tr, "gates": [g["id"] for g in load_gates()],
               "fund": folder.name, "fund_id": body["fund"], "extractor": ex, "judge": jd, "started": time.time()}
        jid = uuid.uuid4().hex[:10]
        JOBS[jid] = job
        log("job", f"screen started: {folder.name} (extractor {ex}, judge {jd})", job=jid)

        def work():
            try:
                out, summary, _ = run(folder, ex, jd, tracker=tr)
                job.update(status="done", run=out.name, seconds=summary.get("seconds"))
                log("job", f"screen finished: {folder.name}: {summary['disposition']}", job=jid, run=out.name)
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
