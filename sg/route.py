"""Route a gate to the sections it needs, using the catalog. No model calls.

A gate's `sources` block names document types (in priority order) and section-title
patterns. For each canonical document of those types, take the sections whose titles
match. A short document with no matching section is read whole. Every choice is logged
with its reason, so a reader can see exactly what the extractor was shown.
"""

import re


def route(room, docs, sources):
    # Either list may be absent on a gate edited in the console; route with whatever is there.
    types = sources.get("doc_types") or []
    patterns = sources.get("sections") or []
    pat = re.compile("|".join(patterns), re.I) if patterns else None
    whole_under = sources.get("whole_docs_under", 12)
    per_section = sources.get("max_section_pages", 12)
    budget = sources.get("max_pages", 40)

    candidates = [d for d in docs if d["canonical"] and d["doc_type"] in types]
    candidates.sort(key=lambda d: (types.index(d["doc_type"]), -d["pages"]))
    plan, chosen = [], []  # chosen: (file, page, section title)
    seen = set()

    def take(d, start, end, title, why):
        nonlocal budget
        pages = [p for p in range(start, end + 1) if (d["path"], p) not in seen]
        cut = pages[: min(per_section, budget)]
        if not cut:
            if end >= start and budget > 0:
                plan.append(
                    {
                        "doc": d["name"],
                        "doc_type": d["doc_type"],
                        "section": title,
                        "pages": [start, end],
                        "why": why + ", pages already included",
                        "truncated": False,
                    }
                )
            return
        for p in cut:
            seen.add((d["path"], p))
            chosen.append((d["path"], p, title))
        budget -= len(cut)
        plan.append(
            {
                "doc": d["name"],
                "doc_type": d["doc_type"],
                "section": title,
                "pages": [cut[0], cut[-1]],
                "why": why,
                "truncated": len(cut) < len(pages),
            }
        )

    for d in candidates:
        if budget <= 0:
            break
        hits = [s for s in d.get("sections") or [] if pat and pat.search(s["title"])]
        # A broad parent and its matching children both hit; keep the narrower children.
        hits = [
            s
            for s in hits
            if not any(o is not s and o["level"] > s["level"] and s["start"] <= o["start"] <= s["end"] for o in hits)
        ]
        for s in hits:
            if budget <= 0:
                break
            take(d, s["start"], s["end"], s["title"], f"{s['source']} section title matches")
        if not hits and d["pages"] <= whole_under:
            take(d, 1, d["pages"], "(whole document)", f"short {d['doc_type']}, read whole")

    pages = []
    for path, p, title in chosen:
        row = room.by_key.get((path, p))
        if row:
            pages.append(dict(row, text=row["text"][:6000], section=title))
    return pages, plan
