"""Contradictions across documents (decision F3).

Inside the gates every extracted field is a gate field, so two documents that state one differently are a
finding. Percentages and dollar amounts are compared in code; wording is left to a model when the run has one.
Only values from different documents count: one document quoting two figures is usually two share classes or
two dates, not a contradiction.

Outside the gates, only a marketing document that contradicts a filed one is a finding. A model reads the
marketing pages beside the filed documents' summary pages once per run, and every pair it reports must quote
both pages verbatim, or it is dropped.
"""

import json
import re

from .llm import call_claude_tool

MARKETING = {"deck"}
FILED = {"offering document", "governing agreement", "terms", "subscription"}
SUMMARY_SECTIONS = re.compile(r"summary of (principal )?terms|key terms|the offering|fees|expenses|risk", re.I)

PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
USD = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|k|mm|m|bn|b)?\b", re.I)
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def number(value):
    """("%", 1.35) or ("$", 500000.0) for the first figure in a value, else None."""
    m = PCT.search(value or "")
    if m:
        return "%", round(float(m.group(1)), 3)
    m = USD.search(value or "")
    if m:
        return "$", round(float(m.group(1).replace(",", "")) * SCALE.get((m.group(2) or "").lower(), 1), 2)
    return None


def kinds(catalog):
    """{file path: "marketing" | "filed" | "other"} from the catalog's document types."""
    out = {}
    for d in catalog or []:
        t = d.get("doc_type")
        out[d["path"]] = "marketing" if t in MARKETING else "filed" if t in FILED else "other"
    return out


def _entry(f, kind):
    return {"file": f["file"], "page": f["page"], "value": f["value"], "quote": f["quote"], "kind": kind}


def _finding(field, facts, kind_of, summary, source):
    values = [_entry(f, kind_of.get(f["file"], "other")) for f in facts]
    found = {v["kind"] for v in values}
    return {
        "field": field,
        "summary": summary,
        "values": values,
        "marketing_vs_filed": {"marketing", "filed"} <= found,
        "source": source,
    }


def by_field(facts):
    """{field: [facts]} for fields quoted in two or more documents."""
    groups: dict[str, list] = {}
    for f in facts:
        groups.setdefault(f["field"], []).append(f)
    return {k: v for k, v in groups.items() if len({f["file"] for f in v}) > 1}


def in_code(facts, kind_of):
    """Contradictions decidable from figures, and the fields left for a model to read."""
    found, wording = [], {}
    for field, group in by_field(facts).items():
        nums = [n for n in (number(f["value"]) for f in group) if n]
        if len(nums) < len(group) or len({u for u, _ in nums}) != 1:
            wording[field] = group
            continue
        per_file: dict[str, set] = {}
        for f, (_, x) in zip(group, nums, strict=True):
            per_file.setdefault(f["file"], set()).add(x)
        sets = list(per_file.values())
        if any(a != b for a in sets for b in sets):
            unit = nums[0][0]
            shown = ", ".join(f"{x:g}%" if unit == "%" else f"${x:,.0f}" for x in sorted({x for _, x in nums}))
            found.append(_finding(field, group, kind_of, f"Documents give {shown}", "code"))
    return found, wording


def claude_wording(gate_id, groups, kind_of):
    """Ask Claude which fields the documents state materially differently."""
    if not groups:
        return []
    schema = {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "differ": {"type": "boolean"},
                        "summary": {"type": "string"},
                    },
                    "required": ["field", "differ", "summary"],
                },
            }
        },
        "required": ["fields"],
    }
    system = (
        "You compare what different fund documents say about the same field. A field differs only when the "
        "documents state materially different facts. Ignore wording, formatting, rounding, and statements that "
        "cover different share classes, vehicles or dates. Summarise each difference in one sentence."
    )
    payload = {f: [_entry(x, kind_of.get(x["file"], "other")) for x in g] for f, g in groups.items()}
    out = call_claude_tool(system, json.dumps({"gate": gate_id, "fields": payload}), "compare_fields", schema)
    return [
        _finding(r["field"], groups[r["field"]], kind_of, r["summary"], "model")
        for r in out["fields"]
        if r.get("differ") and r.get("field") in groups
    ]


def marketing_pages(room, catalog, limit=30):
    """(marketing pages, filed summary pages) for the room-wide check, at most `limit` pages in all."""
    canon = [d for d in catalog or [] if d.get("canonical")]
    mk = [(d["path"], p) for d in canon if d["doc_type"] in MARKETING for p in range(1, d["pages"] + 1)][: limit // 2]
    fl = []
    for d in (d for d in canon if d["doc_type"] in FILED):
        hits = [s for s in d.get("sections") or [] if SUMMARY_SECTIONS.search(s["title"])]
        spans = [(s["start"], s["end"]) for s in hits] or ([(1, d["pages"])] if d["pages"] <= 12 else [])
        fl += [(d["path"], p) for a, b in spans for p in range(a, b + 1)]
    fl = list(dict.fromkeys(fl))[: limit - len(mk)]
    rows = lambda keys: [room.by_key[k] for k in keys if k in room.by_key]
    return rows(mk), rows(fl)


def claude_marketing(room, catalog):
    """Statements in marketing pages that a filed page contradicts, both sides quoted."""
    mk, fl = marketing_pages(room, catalog)
    if not mk or not fl:
        return []
    side = {
        "type": "object",
        "properties": {"file": {"type": "string"}, "page": {"type": "integer"}, "quote": {"type": "string"}},
        "required": ["file", "page", "quote"],
    }
    schema = {
        "type": "object",
        "properties": {
            "conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "summary": {"type": "string"},
                        "marketing": side,
                        "filed": side,
                    },
                    "required": ["topic", "summary", "marketing", "filed"],
                },
            }
        },
        "required": ["conflicts"],
    }
    fmt = lambda rows: "\n\n".join(f"[file: {p['file']} | page: {p['page']}]\n{p['text'][:4000]}" for p in rows)
    system = (
        "List factual statements in the MARKETING pages that a FILED page contradicts: figures, dates, sizes, "
        "terms, fees, track record basis, first closings or deals. Skip opinions and anything the filed pages do "
        "not address. Quote both sides VERBATIM with the exact file and page."
    )
    out = call_claude_tool(system, f"MARKETING:\n{fmt(mk)}\n\nFILED:\n{fmt(fl)}", "record_conflicts", schema)
    return out["conflicts"]


def verified(room, conflicts):
    """Keep a reported conflict only when both quotes are on their cited pages."""
    keep = []
    for c in conflicts:
        m, f = c["marketing"], c["filed"]
        if room.verify_quote(m["file"], m["page"], m["quote"]) and room.verify_quote(f["file"], f["page"], f["quote"]):
            keep.append({**c, "source": "model"})
    return keep


# Adapters by extractor name. Runs with an extractor that has none (stubs, fixtures) compare figures only.
WORDING = {"claude": claude_wording}
MARKETING_CHECK = {"claude": claude_marketing}
