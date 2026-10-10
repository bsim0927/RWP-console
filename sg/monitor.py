"""Agent monitoring: every screen run as a trace of model calls with timing, tokens and outputs.

Runs written after call tracing carry exact per-call records (gate JSON "calls", also runs/calls.jsonl).
Older runs are backfilled from their step timeline and the judge's recorded usage, and say so.
Calls in calls.jsonl that belong to no saved run come from runs that failed or are still going.
"""

import json
import time
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / "runs"
PROVIDER = {"claude": "anthropic", "jev": "jev"}
LLM_EXTRACTORS, LLM_JUDGES = {"claude"}, {"claude", "jev"}


def _read(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _backfill(g, s):
    """Rebuild the two model calls of a gate from its timeline when the run predates tracing."""
    tl = {e["step"]: e for e in g.get("timeline") or []}
    out = []
    dur = lambda e: round((e["end"] if e.get("end") is not None else e["start"]) - e["start"], 3)
    if "extract" in tl and s.get("extractor") in LLM_EXTRACTORS:
        n = len((g.get("brief") or {}).get("facts") or []) + len(g.get("rejected") or [])
        out.append(
            {
                "id": None,
                "step": "extract",
                "provider": PROVIDER.get(s["extractor"]),
                "model": None,
                "seconds": dur(tl["extract"]),
                "ok": True,
                "input_tokens": None,
                "output_tokens": None,
                "output": json.dumps({"facts_proposed": n}),
                "backfilled": True,
            }
        )
    if "judge" in tl and s.get("judge") in LLM_JUDGES:
        meta = (g.get("answers") or {}).get("_meta") or {}
        usage = meta.get("usage") or {}
        out.append(
            {
                "id": None,
                "step": "judge",
                "provider": PROVIDER.get(s["judge"]),
                "model": meta.get("model"),
                "seconds": dur(tl["judge"]),
                "ok": True,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "output": json.dumps({k: v for k, v in (g.get("answers") or {}).items() if k != "_meta"})[:1500],
                "backfilled": True,
            }
        )
    return out


def report():
    runs, calls, linked = [], [], set()
    if RUNS.exists():
        for fdir in sorted(p for p in RUNS.iterdir() if p.is_dir()):
            for rdir in sorted(p for p in fdir.iterdir() if p.is_dir()):
                s = _read(rdir / "summary.json")
                if not s:
                    continue
                gates = []
                for gp in sorted((rdir / "gates").glob("*.json")):
                    g = _read(gp) or {}
                    gc = g["calls"] if g.get("calls") is not None else _backfill(g, s)
                    for c in gc:
                        c = {
                            **c,
                            "run": s["run"],
                            "fund": s["fund"],
                            "fund_id": fdir.name,
                            "gate": g.get("gate", gp.stem),
                        }
                        c.setdefault("backfilled", False)
                        if c.get("ts") is None:  # backfilled: the run stamp is the best clock we have
                            c["ts"] = time.mktime(time.strptime(s["run"], "%Y%m%dT%H%M%S"))
                        calls.append(c)
                        if c.get("id"):
                            linked.add(c["id"])
                    b = g.get("brief") or {}
                    gates.append(
                        {
                            "gate": g.get("gate", gp.stem),
                            "result": g.get("result"),
                            "review": bool(g.get("review")),
                            "min_confidence": g.get("min_confidence"),
                            "timeline": g.get("timeline") or [],
                            "facts": len(b.get("facts") or []),
                            "rejected": len(g.get("rejected") or []),
                            "not_found": b.get("not_found") or [],
                            "calls": [
                                c
                                for c in calls
                                if c["run"] == s["run"]
                                and c["fund_id"] == fdir.name
                                and c["gate"] == g.get("gate", gp.stem)
                            ],
                        }
                    )
                mine = [c for c in calls if c["run"] == s["run"] and c["fund_id"] == fdir.name]
                runs.append(
                    {
                        "fund": s["fund"],
                        "fund_id": fdir.name,
                        "run": s["run"],
                        "extractor": s.get("extractor"),
                        "judge": s.get("judge"),
                        "disposition": s.get("disposition"),
                        "seconds": s.get("seconds"),
                        "agentic": bool(mine),
                        "traced": any(not c["backfilled"] for c in mine),
                        "calls": len(mine),
                        "errors": sum(not c["ok"] for c in mine),
                        "input_tokens": sum(c.get("input_tokens") or 0 for c in mine),
                        "output_tokens": sum(c.get("output_tokens") or 0 for c in mine),
                        "facts_proposed": sum(g["facts"] + g["rejected"] for g in gates),
                        "facts_verified": sum(g["facts"] for g in gates),
                        "gates": gates,
                    }
                )
    log = RUNS / "calls.jsonl"
    if log.exists():
        for line in log.read_text().splitlines():
            try:
                c = json.loads(line)
            except ValueError:
                continue
            if c.get("id") not in linked:  # failed or unfinished run
                calls.append({**c, "run": None, "fund_id": None, "backfilled": False})
    runs.sort(key=lambda r: r["run"], reverse=True)
    calls.sort(key=lambda c: (c.get("ts") or 0, c.get("run") or ""), reverse=True)
    return {"runs": runs, "calls": calls}
