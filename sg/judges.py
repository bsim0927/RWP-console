"""Judges answer a gate's typed questions from the brief. Every adapter returns
{question_id: {option: probability}}. bool questions use options "true" / "false"."""
import json
import os

from .llm import call_claude_tool, record


def options_of(q):
    return ["true", "false"] if q["type"] == "bool" else q["options"]


def claude_judge(gate, brief, questions):
    """Dev fallback until Jev access: Claude returns a probability per option."""
    qs = [{"id": q["id"], "question": q["q"], "options": options_of(q)} for q in questions]
    schema = {"type": "object", "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "probabilities": {"type": "object", "additionalProperties": {"type": "number"}}},
        "required": ["id", "probabilities"]}}}, "required": ["answers"]}
    system = ("Answer each question using ONLY the facts in the brief. Return a probability for "
              "every option; they must sum to 1. If the brief does not support an answer, spread "
              "probability accordingly. Do not use outside knowledge.")
    out = call_claude_tool(system, json.dumps({"brief": brief, "questions": qs}), "answer", schema)
    return {a["id"]: a["probabilities"] for a in out["answers"]}


def brief_state(gate, brief):
    """Structured state for Jev: named fields so questions can point at them.
    Quotes only. File and page stay in our log, they are noise to the judge."""
    facts = {}
    for f in brief["facts"]:
        facts.setdefault(f["field"], []).append(f["quote"])
    return {"gate": gate["id"].replace("_", " "), "facts": facts,
            "not_found": brief["not_found"], "computed": brief["checks"]}


def jev_question(q):
    """Question IDs are not sent to Jev, so instructions must stand alone."""
    if q["type"] == "bool":
        out = {"type": "noul", "instructions": q["q"]}
        if q.get("criteria"):
            out["criteria"] = {"true": q["criteria"]["true"], "false": q["criteria"]["false"]}
        return out
    crit = q.get("criteria") or {o: o.replace("_", " ") for o in q["options"]}
    return {"type": "choice", "instructions": q["q"], "criteria": crit}


def jev_judge(gate, brief, questions):
    """One request, all questions in parallel. Docs: docs.typesafe.ai/api.md"""
    import time
    import urllib.error
    import urllib.request
    key = os.environ.get("JEV_API_KEY")
    if not key:
        raise SystemExit("JEV_API_KEY is not set")
    body = json.dumps({"state": brief_state(gate, brief),
                       "model": os.environ.get("SG_JEV_MODEL", "jev-latest"),
                       "questions": {q["id"]: jev_question(q) for q in questions}}).encode()
    req = urllib.request.Request(
        "https://api.typesafe.ai/v1/systemone", body,
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    model, t0 = os.environ.get("SG_JEV_MODEL", "jev-latest"), time.time()
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 529) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            err = f"Jev API HTTP {e.code}: {e.read().decode()[:500]}"
            record("jev", model, t0, ok=False, error=err, input_chars=len(body), attempts=attempt + 1)
            raise RuntimeError(err) from None
        except (urllib.error.URLError, TimeoutError) as e:
            record("jev", model, t0, ok=False, error=str(e), input_chars=len(body), attempts=attempt + 1)
            raise
    out = {}
    for q in questions:
        a = resp["answers"][q["id"]]
        if q["type"] == "bool":
            out[q["id"]] = {"true": a["noul"], "false": 1 - a["noul"]}
        else:
            out[q["id"]] = {o: a["probabilities"].get(o, 0.0) for o in q["options"]}
    out["_meta"] = {"model": resp.get("model"), "usage": resp.get("usage")}
    record("jev", resp.get("model") or model, t0, usage=resp.get("usage"), input_chars=len(body),
           attempts=attempt + 1, output={k: v for k, v in out.items() if k != "_meta"})
    return out


JUDGES = {"claude": claude_judge, "jev": jev_judge}
