"""Load gates, run extract -> verify -> judge -> derive, reduce to a disposition, save it to the database."""

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import consistency, gate_store, store
from .catalog import load as load_catalog
from .dataroom import DataRoom
from .extractors import EXTRACTORS
from .judges import JUDGES
from .llm import CTX, TRACE
from .route import route

ROOT = Path(__file__).resolve().parent.parent


def load_gates(only=None, with_yaml=False):
    """Live gates in pipeline order. with_yaml also returns {id: definition text} for the run record."""
    live = gate_store.current()
    gates = [g for g in (yaml.safe_load(x["text"]) for x in live) if not only or g["id"] in only]
    return (gates, {x["id"]: x["text"] for x in live}) if with_yaml else gates


def code_checks(gate, facts):
    """Deterministic numbers. Jev is weak on arithmetic, so it never does any.
    Each counted (recurring) fee layer is summed once; a layer quoted at two rates means the
    documents disagree, and then there is no honest total."""
    counted = {f["name"] for f in gate["extractor"]["fields"] if f.get("recurring")}
    rates: dict[str, set[float]] = {}
    for f in facts:
        m = f["field"] in counted and re.search(r"(\d+(?:\.\d+)?)\s*%", f["value"])
        if m:
            rates.setdefault(f["field"], set()).add(round(float(m.group(1)), 3))
    conflicts = {k: sorted(v) for k, v in rates.items() if len(v) > 1}
    total = round(sum(min(v) for v in rates.values()), 3) if rates and not conflicts else None
    return {"total_pct": total, "fees_disagree": bool(conflicts), "fee_conflicts": conflicts}


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


def holds(cond, env):
    # Config is trusted and local. No builtins exposed to the expression.
    return bool(eval(cond if cond is not None else "True", {"__builtins__": {}}, env))


def derive(rules, env):
    for r in rules:
        if holds(r.get("if"), env):
            return r["then"]
    return "Incomplete"


def raise_flags(flags, env):
    """What the analyst should know beyond the result, e.g. QP-only. A flag without a condition always shows."""
    return [f["flag"] for f in flags or [] if holds(f.get("if"), env)]


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


def for_share_class(gate, share_class):
    """A fee gate reads the analyst's chosen share class (decision B5); other gates are unchanged."""
    ex = gate.get("extractor") or {}
    if not share_class or not any(f.get("recurring") for f in ex.get("fields", [])):
        return gate
    rules = f"{ex.get('rules', '')} The analyst chose share class {share_class}: screen that class.".strip()
    return {**gate, "extractor": {**ex, "rules": rules}}


def run_gate(gate, room, extractor, judge, tr, catalog=None, share_class=None):
    gate = for_share_class(gate, share_class)
    rec = {"gate": gate["id"], "gate_version": gate.get("version"), "extractor": extractor, "judge": judge}
    if gate.get("static_result"):
        e = tr.begin(gate["id"], "skipped")
        tr.end(e, gate["static_result"])
        rec.update(
            result=gate["static_result"],
            flags=[],
            review=False,
            facts=[],
            rejected=[],
            note="Gate not automated in this prototype.",
        )
        return rec
    ex = gate["extractor"]
    calls: list[dict] = []
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
        plan = [
            {
                "doc": "(keyword fallback)",
                "section": "top pages by keyword count",
                "pages": [],
                "why": "no catalog section matched this gate",
            }
        ]
        tr.end(e, f"{len(pages)} pages by keyword fallback")
    e = tr.begin(gate["id"], "extract")
    CTX.set({**ctx, "step": "extract"})
    raw = EXTRACTORS[extractor](gate, room, pages)
    tr.end(e, f"{len(raw)} facts proposed")
    e = tr.begin(gate["id"], "verify")
    facts: list[dict] = []
    rejected: list[dict] = []
    for f in raw:
        f["match"] = room.verify_quote(f["file"], f["page"], f["quote"])
        (facts if f["match"] else rejected).append(f)
    reflowed = sum(f["match"] == "reflowed" for f in facts)
    # Two documents stating a gate field differently is a finding (decision F3): figures in code, wording by
    # the run's model when it has one.
    kind_of = consistency.kinds(catalog)
    contradictions, wording = consistency.in_code(facts, kind_of)
    compare, compare_error = consistency.WORDING.get(extractor), None
    if compare and wording:
        CTX.set({**ctx, "step": "compare"})
        try:
            contradictions += compare(gate["id"], wording, kind_of)
        except Exception as err:  # the call is in model_calls; the screen goes on with the figures
            compare_error = f"{type(err).__name__}: {err}"
    tr.end(
        e,
        f"{len(facts)} verified ({reflowed} across layout), {len(rejected)} rejected, "
        f"{len(contradictions)} contradiction{'' if len(contradictions) == 1 else 's'}",
    )
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
    env.update({k: checks[k] for k in gate_store.CHECK_NAMES})
    result = derive(gate["derive"], env)
    flags = raise_flags(gate.get("flags"), env)
    decisive = gate.get("review_if", {}).get("decisive", [q["id"] for q in questions])
    floor = gate.get("review_if", {}).get("min_confidence", 0.75)
    low = [i for i in decisive if conf[i] < floor]
    tr.end(e, result + "".join(f" · {f}" for f in flags))
    rec.update(
        result=result,
        flags=flags,
        checks=gate.get("checks") or [],
        contradictions=contradictions,
        compare_error=compare_error,
        review=bool(low),
        low_confidence=low,
        brief=brief,
        rejected=rejected,
        questions=questions,
        answers=answers,
        env_for_rules=env,
        min_confidence=round(min(conf[i] for i in decisive), 3),
        pages_offered=[[p["file"], p["page"]] for p in pages],
        routing=plan,
        brief_sha=hashlib.sha256(json.dumps(brief, sort_keys=True).encode()).hexdigest()[:12],
        calls=calls,
    )
    return rec


def check_marketing(room, catalog, extractor, tr):
    """Room-wide (decision F3): marketing statements a filed document contradicts. Needs a model adapter, so
    stub and fixture runs skip it. Returns (findings, error)."""
    fn = consistency.MARKETING_CHECK.get(extractor)
    if not fn:
        return [], None
    e = tr.begin("consistency", "compare")
    CTX.set({"fund": room.name, "gate": "consistency", "step": "compare"})
    try:
        found = consistency.verified(room, fn(room, catalog))
    except Exception as err:  # the call is in model_calls; the screen goes on without this check
        tr.end(e, "failed")
        return [], f"{type(err).__name__}: {err}"
    tr.end(e, f"{len(found)} marketing statement{'' if len(found) == 1 else 's'} contradicted")
    return found, None


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
    pol = store.policy()
    policy = yaml.safe_load(pol["yaml"])
    tr = tracker or Tracker()
    gates, gate_yaml = load_gates(only, with_yaml=True)
    e = tr.begin("catalog", "catalog")
    catalog = load_catalog(data_room)
    tr.end(e, f"{sum(d['canonical'] for d in catalog)} canonical documents")
    fund_id = re.sub(r"[^\w.-]+", "_", room.name)
    share_class = store.intake(fund_id)["share_class"]
    with ThreadPoolExecutor(max_workers=len(gates) + 1) as pool:
        marketing = pool.submit(check_marketing, room, catalog, extractor, tr)
        results = list(pool.map(lambda g: run_gate(g, room, extractor, judge, tr, catalog, share_class), gates))
        marketing_found, marketing_error = marketing.result()
    for r in results:
        r["timeline"] = [e for e in tr.steps if e["gate"] == r["gate"]]
    disposition, flags = reduce_gates(policy, results)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    summary = {
        "fund": room.name,
        "run": stamp,
        "extractor": extractor,
        "judge": judge,
        "share_class": share_class,
        "disposition": disposition,
        "flags": flags,
        "marketing_contradictions": marketing_found,
        "marketing_check_error": marketing_error,
        "seconds": round(time.time() - tr.t0, 2),
        "gates": {
            r["gate"]: {
                "result": r["result"],
                "flags": r.get("flags", []),
                "review": r.get("review"),
                "min_confidence": r.get("min_confidence"),
            }
            for r in results
        },
    }
    store.save_run(fund_id, summary, results, render_md(summary, results), gate_yaml, pol["id"])
    return f"{fund_id}/{stamp}", summary, results


def render_md(summary, results):
    L = [
        f"# Screen run: {summary['fund']}",
        "",
        f"Run {summary['run']}. Extractor `{summary['extractor']}`, judge `{summary['judge']}`."
        + (f" Share class screened: {summary['share_class']}." if summary.get("share_class") else ""),
        "",
        f"**{summary['disposition']}**",
        "",
        "| Gate | Result | Flags | Analyst review | Evidence |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        ev = "; ".join(f"{f['file'].split('/')[-1]} p.{f['page']}" for f in r.get("brief", {}).get("facts", [])[:4])
        flags = "; ".join(r.get("flags") or []) or "none"
        L.append(f"| {r['gate']} | {r['result']} | {flags} | {'yes' if r.get('review') else 'no'} | {ev or 'none'} |")
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
        for c in r.get("contradictions") or []:
            where = "; ".join(f"{v['file'].split('/')[-1]} p.{v['page']}: {v['value']}" for v in c["values"])
            L.append(f"- Documents disagree on **{c['field']}**: {c['summary']} ({where})")
        if r["rejected"]:
            L.append(f"- Rejected, quote not on cited page: {len(r['rejected'])}")
        L.append("")
    if summary.get("marketing_contradictions"):
        L += ["## Marketing against filed documents", ""]
        for c in summary["marketing_contradictions"]:
            m, f = c["marketing"], c["filed"]
            L.append(
                f'- **{c["topic"]}**: {c["summary"]} Marketing: "{m["quote"]}" ({m["file"].split("/")[-1]} p.{m["page"]}). '
                f'Filed: "{f["quote"]}" ({f["file"].split("/")[-1]} p.{f["page"]}).'
            )
        L.append("")
    return "\n".join(L)
