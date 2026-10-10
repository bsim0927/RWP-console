"""Section index for one document, built from its own structure. No model calls.

Sources, in the order they are trusted:
  bookmark  the PDF outline (sg.catalog.bookmarks)
  toc       a printed table of contents, each entry anchored to where its heading
            actually appears in the body. Printed page numbers are only a fallback,
            because they rarely match PDF pages (one PPM was offset by 3).
  term      two-column term labels such as "Minimum Purchase Amount:" in a summary
            of terms. Nested under the toc or bookmark section that contains them.
Every section records its source, so a reader knows how far to trust its boundaries.
"""

import re
import statistics

from .dataroom import norm

ROMAN = r"[IVXLC]+"
# Structural markers that are matched exactly at the start of a body line.
MARKER = re.compile(rf"^(article\s+{ROMAN.lower()}\b|section\s+\d+(?:\.\d+)*\b|item\s+\d+[a-z]?\.?)", re.I)
TOC_LINE = re.compile(r"^(?P<title>\S.*?\S)\s*(?:\.{2,}\s*(?P<p1>\d{1,3})?|\s+(?P<p2>\d{1,3}))\s*$")


def level_of(title):
    t = title.strip()
    if re.match(rf"^(article\s+{ROMAN}|item\s+\d|{ROMAN}\.\s)", t, re.I):
        return 1
    if re.match(r"^(section\s+\d|\d+(\.\d+)*\.?\s)", t, re.I):
        return 2
    return 1


def toc_entries(pages, scan=8):
    """Entries from the first pages that look like a table of contents (5+ leader lines)."""
    entries, toc_pages = [], []
    for p in pages[:scan]:
        found, pending = [], ""
        for line in p["text"].splitlines():
            line = " ".join(line.split())
            m = TOC_LINE.match(line)
            if not m:
                # A long title wraps: "ARTICLE IX ALLOCATION OF PROFITS AND" / "LOSSES ....".
                # Hold a marker-led line with no leader and join it to the next entry.
                pending = line if line and (MARKER.match(line) or re.match(rf"^({ROMAN}|\d+)\.\s", line)) else ""
                continue
            title = m.group("title").rstrip(". ")
            if pending and not MARKER.match(title) and not re.match(rf"^({ROMAN}|\d+)\.\s", title):
                title = f"{pending} {title}"
            pending = ""
            printed = m.group("p1") or m.group("p2")
            # Plain "Title 12" lines only count when the title carries a structural marker,
            # otherwise every sentence ending in a number would qualify.
            if not m.group("p1") and m.group("p2") and not MARKER.match(title) and "." not in line[-40:]:
                if not re.match(rf"^({ROMAN}|\d+)\.\s", title):
                    continue
            if len(title) < 3 or title.lower() in ("table of contents", "contents", "page"):
                continue
            found.append({"title": title, "printed": int(printed) if printed else None})
        if len(found) >= 5:
            entries += found
            toc_pages.append(p["page"])
    return entries, toc_pages


def heading_key(title):
    m = MARKER.match(title)
    if m:
        return "marker", norm(m.group(1)).rstrip(".")
    words = norm(re.sub(rf"^({ROMAN}|\d+)\.\s*", "", title)).split()
    # One word ("LOSSES") matches too many body lines to anchor anything.
    return ("words", " ".join(words[:6])) if len(words) >= 2 else ("skip", "")


def locate(entries, pages, after):
    """Page where each entry's heading starts in the body. Monotonic: never before the previous one."""
    lines_by_page = []
    for p in pages:
        if p["page"] <= after:
            continue
        lines = [norm(l) for l in p["text"].splitlines() if l.strip()]
        lines_by_page.append((p["page"], lines))
    floor = after + 1
    for e in entries:
        kind, key = heading_key(e["title"])
        e["start"] = None
        if kind == "skip":
            continue
        for page, lines in lines_by_page:
            if page < floor:
                continue
            for i, line in enumerate(lines):
                if kind == "marker":
                    hit = line.startswith(key) and (len(line) == len(key) or not line[len(key)].isalnum())
                else:
                    stripped = re.sub(rf"^({ROMAN.lower()}|\d+)\.\s*", "", line)
                    joined = (stripped + " " + (lines[i + 1] if i + 1 < len(lines) else "")).strip()
                    hit = len(line) < 120 and joined.startswith(key)
                if hit:
                    e["start"], e["located"] = page, "body heading"
                    break
            if e["start"]:
                floor = e["start"]
                break
    offsets = [e["start"] - e["printed"] for e in entries if e["start"] and e["printed"]]
    # Printed numbers are only trusted when the headings we did find agree on one offset.
    # A draft's stale ToC (one draft PPM listed page 266 of 137) must not place anything.
    off = None
    if offsets and max(offsets) - min(offsets) <= 2:
        off = round(statistics.median(offsets))
    n_last = max(p["page"] for p in pages)
    for i, e in enumerate(entries):
        if e["start"] or not e["printed"] or off is None:
            continue
        guess = e["printed"] + off
        before = max([x["start"] for x in entries[:i] if x["start"]] or [after + 1])
        later = [x["start"] for x in entries[i + 1 :] if x["start"] and x.get("located") == "body heading"]
        nxt = min(later) if later else n_last
        if after < guess <= n_last and before <= guess <= nxt:
            e["start"], e["located"] = guess, f"printed page + offset {off:+d}"
    return off


def term_labels(pages):
    """Two-column term sheets: a label at column 0, then 2+ spaces, then the text.
    A label may wrap onto following lines and ends with a colon."""
    out = []
    for p in pages:
        lines = p["text"].splitlines()
        i = 0
        while i < len(lines):
            m = re.match(r"^(\S.{0,45}?)\s{2,}\S", lines[i])
            if m and m.group(1)[0].isupper():
                label, j = m.group(1).strip(), i
                while not label.endswith(":") and j + 1 < len(lines) and j - i < 3:
                    n = re.match(r"^(\S.{0,40}?)(\s{2,}\S|\s*$)", lines[j + 1])
                    if not n:
                        break
                    label, j = f"{label} {n.group(1).strip()}", j + 1
                if label.endswith(":") and 2 < len(label) < 60:
                    out.append({"title": label.rstrip(":").strip(), "start": p["page"], "level": 3, "source": "term"})
                i = j + 1
            else:
                i += 1
    return out


def close(sections, n_pages):
    """End page for each section: the page before the next section at the same or higher level."""
    for i, s in enumerate(sections):
        s["end"] = n_pages
        for nxt in sections[i + 1 :]:
            if nxt["level"] <= s["level"]:
                s["end"] = max(s["start"], nxt["start"] - (0 if nxt["start"] == s["start"] else 1))
                break
    return sections


def build_sections(pages, marks):
    """pages: this document's index rows sorted by page. marks: sg.catalog.bookmarks output."""
    n = len(pages)
    if marks:
        top = [{"title": b["title"], "start": b["page"], "level": b["level"], "source": "bookmark"} for b in marks]
        toc_pages, note = [], "bookmarks"
    else:
        entries, toc_pages = toc_entries(pages)
        top, note = [], "no structure found"
        if entries:
            off = locate(entries, pages, after=max(toc_pages))
            top = [
                {
                    "title": e["title"],
                    "start": e["start"],
                    "level": level_of(e["title"]),
                    "source": "toc",
                    "located": e.get("located"),
                }
                for e in entries
                if e["start"]
            ]
            note = f"toc on p.{','.join(map(str, toc_pages))}, {len(top)}/{len(entries)} entries placed"
            if off is not None:
                note += f", printed-page offset {off:+d}"
    terms = [t for t in term_labels(pages) if t["start"] not in toc_pages]
    # Within a page keep the document's own order: toc and bookmark entries first, in
    # their listed order, then term labels in reading order.
    for i, x in enumerate(top + terms):
        x["_o"] = (0 if x["source"] != "term" else 1, i)
    secs = sorted(top + terms, key=lambda x: (x["start"], x["_o"]))
    for x in secs:
        x.pop("_o")
    # Keep term labels only where there are several: one stray "Note:" is not a term sheet.
    if len(terms) < 4:
        secs = [s for s in secs if s["source"] != "term"]
    close(secs, n)
    covered = set()
    for s in secs:
        covered.update(range(s["start"], s["end"] + 1))
    return secs, {
        "method": note,
        "terms": len([s for s in secs if s["source"] == "term"]),
        "coverage": round(len(covered) / n, 2) if n else 0,
    }
