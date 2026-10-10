"""Load gates, run extract -> verify -> judge -> derive, reduce to a disposition, log it all."""
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from .dataroom import DataRoom
from .extractors import EXTRACTORS
from .catalog import load as load_catalog
from .judges import JUDGES
from .llm import CTX, TRACE
from .route import route

ROOT = Path(__file__).resolve().parent.parent


def load_gates(only=None):
    gates = [yaml.safe_load(p.read_text()) for p in sorted((ROOT / "gates").glob("*.yaml"))]
    return [g for g in gates if not only or g["id"] in only]


def code_checks(gate, facts):
    """Deterministic numbers. Jev is weak on arithmetic, so it never does any."""
    ctx = {"total_pct": None}
    recurring = {f["name"] for f in gate["extractor"]["fields"] if f.get("recurring")}
    vals = []
    for f in facts:
        if f["field"] in recurring:
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", f["value"])
            if m:
                vals.append(float(m.group(1)))
    if recurring:
        ctx["total_pct"] = round(sum(vals), 3) if vals else None
    return ctx


def resolve(questions, answers):
    """Turn probability tables into names the derive rules can use.
    bool  -> id = P(true).   choice -> id = top option, id_p = its probability."""
    env, conf = {}, {}
    for q in questions:
        probs = answers[q["id"]]
        top = max(probs, key=probs.get)
        if q["type"] == "bool":
            env[q["id"]] = probs.get("true", 0.0)
        else:
            env[q["id"]], env[q["id"] + "_p"] = top, probs[top]
        conf[q["id"]] = probs[top]
    return env, conf


def derive(rules, env):
    for r in rules:
        cond = r.get("if", "True")
        # Config is trusted and local. No builtins exposed to the expression.
        if eval(cond, {"__builtins__": {}}, env):
            return r["then"]
    return "Incomplete"


class Tracker:
    """Thread-safe record of pipeline steps, shared by the live viewer and the run log."""

    def __init__(self):
        self.t0 = time.time()
        self.steps = []
        self.lock = threading.Lock()

    def begin(self, gate, step):
        e = {"gate": gate, "step": step, "start": round(time.time() - self.t0, 3), "end": None, "detail": ""}
        with self.lock:
            self.steps.append(e)
        return e

    def end(self, e, detail=""):
        e["end"] = round(time.time() - self.t0, 3)
        e["detail"] = detail


def run_gate(gate, room, extractor, judge, tr, catalog=None):
    rec = {"gate": gate["id"], "gate_version": gate.get("version"),
           "extractor": extractor, "judge": judge}
    if gate.get("static_result"):
        e = tr.begin(gate["id"], "skipped")
        tr.end(e, gate["static_result"])
        rec.update(result=gate["static_result"], review=False, facts=[], rejected=[],
                   note="Gate not automated in this prototype.")
        return rec
    ex = gate["extractor"]
    calls = []
    TRACE.set(calls)  # this runs in the gate's own worker thread, so the context is per gate
    ctx = {"fund": room.name, "gate": gate["id"]}
    e = tr.begin(gate["id"], "retrieve")
    plan = []
    if ex.get("sources") and catalog:
        pages, plan = route(room, catalog, ex["sources"])
    if plan:
        tr.end(e, f"{len(pages)} pages from {len(plan)} sections")
    else:
        # No catalog match: fall back to keywords, and say so in the log.
        pages = room.retrieve(ex.get("keywords", []), ex.get("top_k", 6))
        plan = [{"doc": "(keyword fallback)", "section": "top pages by keyword count",
                 "pages": [], "why": "no catalog section matched this gate"}]
        tr.end(e, f"{len(pages)} pages by keyword fallback")
    e = tr.begin(gate["id"], "extract")
    CTX.set({**ctx, "step": "extract"})
    raw = EXTRACTORS[extractor](gate, room, pages)
    tr.end(e, f"{len(raw)} facts proposed")
    e = tr.begin(gate["id"], "verify")
    facts, rejected = [], []
    for f in raw:
        f["match"] = room.verify_quote(f["file"], f["page"], f["quote"])
        (facts if f["match"] else rejected).append(f)
    reflowed = sum(f["match"] == "reflowed" for f in facts)
    tr.end(e, f"{len(facts)} verified ({reflowed} across layout), {len(rejected)} rejected")
    names = {f["name"] for f in ex["fields"]}
    missing = sorted(names - {f["field"] for f in facts})
    checks = code_checks(gate, facts)
    brief = {"facts": facts, "not_found": missing, "checks": checks}
    questions = gate["questions"]
    e = tr.begin(gate["id"], "judge")
    CTX.set({**ctx, "step": "judge"})
    answers = JUDGES[judge](gate, brief, questions)
    tr.end(e, f"{len(questions)} questions")
    e = tr.begin(gate["id"], "derive")
    env, conf = resolve(questions, answers)
    env.update(checks)
    result = derive(gate["derive"], env)
    decisive = gate.get("review_if", {}).get("decisive", [q["id"] for q in questions])
    floor = gate.get("review_if", {}).get("min_confidence", 0.75)
    low = [i for i in decisive if conf[i] < floor]
    tr.end(e, result)
    rec.update(result=result, review=bool(low), low_confidence=low, brief=brief,
               rejected=rejected, questions=questions, answers=answers, env_for_rules=env,
               min_confidence=round(min(conf[i] for i in decisive), 3),
               pages_offered=[[p["file"], p["page"]] for p in pages], routing=plan,
               brief_sha=hashlib.sha256(json.dumps(brief, sort_keys=True).encode()).hexdigest()[:12],
               calls=calls)
    return rec


def reduce_gates(policy, results):
    flags = {
        "any_fail": any(r["result"] == "Fail" for r in results),
        "any_incomplete": any(r["result"] in ("Incomplete", "Not yet run") for r in results),
        "any_review": any(r.get("review") for r in results),
    }
    for rule in policy["rules"]:
        if rule.get("when") == "otherwise" or flags.get(rule["when"]):
            return rule["disposition"], flags
    return "Under review", flags


def run(data_room, extractor, judge, only=None, tracker=None):
    room = DataRoom(data_room)
    policy = yaml.safe_load((ROOT / "policy.yaml").read_text())
    tr = tracker or Tracker()
    gates = load_gates(only)
    e = tr.begin("catalog", "catalog")
    catalog = load_catalog(data_room)
    tr.end(e, f"{sum(d['canonical'] for d in catalog)} canonical documents")
    with ThreadPoolExecutor(max_workers=len(gates)) as pool:
        results = list(pool.map(lambda g: run_gate(g, room, extractor, judge, tr, catalog), gates))
    for r in results:
        r["timeline"] = [e for e in tr.steps if e["gate"] == r["gate"]]
    disposition, flags = reduce_gates(policy, results)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = ROOT / "runs" / re.sub(r"[^\w.-]+", "_", room.name) / stamp
    (out / "gates").mkdir(parents=True)
    for r in results:
        (out / "gates" / f"{r['gate']}.json").write_text(json.dumps(r, indent=2))
    summary = {"fund": room.name, "run": stamp, "extractor": extractor, "judge": judge,
               "disposition": disposition, "flags": flags,
               "seconds": round(time.time() - tr.t0, 2),
               "gates": {r["gate"]: {"result": r["result"], "review": r.get("review"),
                                     "min_confidence": r.get("min_confidence")} for r in results}}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "summary.md").write_text(render_md(summary, results))
    with (ROOT / "runs" / "index.jsonl").open("a") as fh:
        fh.write(json.dumps(summary) + "\n")
    return out, summary, results


def render_md(summary, results):
    L = [f"# Screen run: {summary['fund']}", "",
         f"Run {summary['run']}. Extractor `{summary['extractor']}`, judge `{summary['judge']}`.", "",
         f"**{summary['disposition']}**", "", "| Gate | Result | Analyst review | Evidence |", "|---|---|---|---|"]
    for r in results:
        ev = "; ".join(f"{f['file'].split('/')[-1]} p.{f['page']}" for f in r.get("brief", {}).get("facts", [])[:4])
        L.append(f"| {r['gate']} | {r['result']} | {'yes' if r.get('review') else 'no'} | {ev or 'none'} |")
    L.append("")
    for r in results:
        b = r.get("brief")
        if not b:
            continue
        L += [f"## {r['gate']}", ""]
        for f in b["facts"]:
            L.append(f"- **{f['field']}**: {f['value']}  ({f['file'].split('/')[-1]}, p.{f['page']})")
        if b["not_found"]:
            L.append(f"- Not found: {', '.join(b['not_found'])}")
        if r["rejected"]:
            L.append(f"- Rejected, quote not on cited page: {len(r['rejected'])}")
        L.append("")
    return "\n".join(L)
