"""Deterministic document catalog for a data room.

Built once per room from _index/pages.jsonl plus the source PDFs, and saved to the database. No model calls.
Every label records where it came from, so a human can see what to trust.
Source files are never renamed or moved.
"""

import hashlib
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from . import store
from .dataroom import DataRoom, norm
from .sections import build_sections

# (doc_type, regex). Checked against the filename first, then each folder from deepest up.
# First match wins, so specific types sit above generic ones.
TYPE_RULES = [
    ("ddq", r"\bddq\b|due diligence questionnaire"),
    ("track record", r"track record|return performance|performance metrics|composite"),
    ("subscription", r"subscription|sub docs?\b|investor questionnaire"),
    ("governing agreement", r"\blpa\b|\bllca\b|limited partnership agreement|operating agreement|declaration of trust"),
    ("offering document", r"\bppm\b|private placement|offering mem|prospectus|10-12g|\bform 10\b|\bn-2\b"),
    ("terms", r"term sheet|summary of terms|key terms|fact ?(card|sheet)"),
    ("financials/audit", r"audit|financial statements|annual report|\b10-[kq]\b"),
    ("privacy", r"privacy"),
    (
        "policies/compliance",
        r"polic|compliance|code of|ethics|valuation|form adv|\badv\b|brochure|operational diligence",
    ),
    (
        "deal-level",
        r"case study|closing memo|\bnbp\b|acquisition summary|investment summary|deal examples|deal \d|investment #|underwriting|extension and upsize",
    ),
    ("news", r"news"),
    ("newsletter", r"newsletter"),
    ("research", r"white ?paper|research|market dynamics|commentary|outlook"),
    ("pipeline", r"pipeline"),
    ("team", r"biograph|\bbios?\b|team overview"),
    ("quarterly report", r"quarterly (update|report|letter)|investor (update|letter)"),
    ("tax", r"\btax\b|k-1"),
    ("deck", r"presentation|\bdeck\b|pitch|overview|executive summary|webinar"),
]

TIER = {
    "offering document": "core",
    "governing agreement": "core",
    "terms": "core",
    "subscription": "core",
    "ddq": "core",
    "track record": "core",
    "financials/audit": "core",
    "policies/compliance": "core",
    "deck": "supporting",
    "deal-level": "supporting",
    "pipeline": "supporting",
    "quarterly report": "supporting",
    "team": "supporting",
    "tax": "supporting",
    "news": "noise",
    "newsletter": "noise",
    "research": "noise",
    "privacy": "noise",
}

# Periodic documents: a new period is not a new version of the old one.
SERIES_TYPES = {"financials/audit", "quarterly report", "newsletter", "news", "research", "track record", "deal-level"}

STATUS_RANK = {"executed": 0, "final": 1, "unmarked": 2, "draft": 3, "archive": 4}

MONTHS = {
    m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}


def classify(path):
    # Underscores are word characters to regex, so "PPM_Feb" would dodge \bppm\b.
    parts = path.replace("_", " ").split("/")
    name = re.sub(r"\.pdf$", "", parts[-1], flags=re.I)
    for t, rx in TYPE_RULES:
        if re.search(rx, name, re.I):
            return t, "filename"
    for folder in reversed(parts[:-1]):
        if re.match(r"\d{2} ", folder):
            continue  # RWP's own numbered folders (01 Inbound, 02 Analysis...) are filing, not document types
        for t, rx in TYPE_RULES:
            if re.search(rx, folder, re.I):
                return t, f"folder: {folder}"
    return "unclassified", "none"


def status_of(path):
    p = path.lower().replace("_", " ")
    if "archive" in p:
        return "archive"
    if re.search(r"\bdraft\b", p):
        return "draft"
    if re.search(r"executed|signed|as ?filed", p):
        return "executed"
    if re.search(r"\bfinal\b|_vff?\b|\bvff?\b", p):
        return "final"
    return "unmarked"


def parse_date(name):
    """Best-effort as-of date from a filename. Returns (label, sort_key) or (None, None)."""
    n = name.lower().replace("_", " ")
    m = re.search(r"\bq([1-4])\s*[-_ ]?\s*'?(20\d{2})\b", n)
    if m:
        y, q = int(m.group(2)), int(m.group(1))
        return f"{y}-Q{q}", (y, q * 3, 31)
    m = re.search(r"\b(20\d{2})\s*[-_ ]?\s*q([1-4])\b", n)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        return f"{y}-Q{q}", (y, q * 3, 31)
    m = re.search(r"(20\d{2})[.\-_](\d{2})[.\-_](\d{2})", n)
    if m:
        y, mo, d = map(int, m.groups())
        return f"{y}-{mo:02d}-{d:02d}", (y, mo, d)
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})\b", n)
    if m:
        mo, d, y = MONTHS[m.group(1)], int(m.group(2)), int(m.group(3))
        return f"{y}-{mo:02d}-{d:02d}", (y, mo, d)
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b", n)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y}-{mo:02d}-{d:02d}", (y, mo, d)
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(20\d{2})\b", n)
    if m:
        mo, y = MONTHS[m.group(1)], int(m.group(2))
        return f"{y}-{mo:02d}", (y, mo, 0)
    m = re.search(r"\b(20\d{2})\b", n)
    if m:
        return m.group(1), (int(m.group(1)), 0, 0)
    return None, None


def title_stem(path):
    """Filename with dates, version and status markers removed, for version grouping."""
    s = re.sub(r"\.pdf$", "", path.split("/")[-1], flags=re.I).lower()
    s = re.sub(r"\bq[1-4]\s*[-_ ]?\s*'?20\d{2}\b|\b20\d{2}\s*[-_ ]?\s*q[1-4]\b", " ", s)
    s = re.sub(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2},?\s+)?20\d{2}\b", " ", s)
    s = re.sub(r"\d{1,4}[.\-_/]\d{1,2}[.\-_/]\d{2,4}", " ", s)
    s = re.sub(r"\b20\d{2}\b", " ", s)
    s = re.sub(r"\b(draft|final|archive|executed|signed|as ?filed|vff?|vexecut\w*|v\d+)\b", " ", s)
    s = re.sub(r"\(\d+\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def vehicle_hint(path):
    m = re.search(r"\b(fund|capital|partners)[ _]+(i{1,3}|iv|v|vi{0,3}|ix|x|\d{1,2})\b", path, re.I)
    return f"{m.group(1).title()} {m.group(2).upper()}" if m else None


def bookmarks(pdf):
    """PDF outline via poppler's pdftohtml. Returns [{title, level, page}]."""
    try:
        xml = subprocess.run(
            ["pdftohtml", "-xml", "-i", "-stdout", "-f", "1", "-l", "1", str(pdf)],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    out, level = [], 0
    for tok in re.finditer(r"<outline>|</outline>|<item page=\"(\d+)\">(.*?)</item>", xml, re.S):
        t = tok.group(0)
        if t == "<outline>":
            level += 1
        elif t == "</outline>":
            level -= 1
        else:
            title = " ".join(re.sub(r"<[^>]+>", "", tok.group(2)).split())
            # "Slide 3" or "Page 3" carries no structure. "Slide 3: Fees" does.
            if title and not re.fullmatch(r"(slide|page)\s*\d+", title, re.I):
                out.append({"title": title, "level": level, "page": int(tok.group(1))})
    return out


def word_shingles(pages, k=8):
    w = norm(" ".join(p["text"] for p in pages)).split()
    return {hashlib.md5(" ".join(w[i : i + k]).encode(), usedforsecurity=False).digest() for i in range(len(w) - k)}


def containment(a, b):
    if min(len(a), len(b)) < 20:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def build(folder):
    room = DataRoom(folder)
    files = defaultdict(list)
    for p in room.pages:
        files[p["file"]].append(p)
    docs = []
    for path, pages in sorted(files.items()):
        pages.sort(key=lambda p: p["page"])
        text = "".join(norm(p["text"]) for p in pages)
        pdf = room.folder / path
        byte_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()[:16] if pdf.exists() else None
        doc_type, type_source = classify(path)
        tier = TIER.get(doc_type, "review")
        as_of, sort_key, date_source = None, None, None
        for i, part in enumerate(reversed(path.split("/"))):
            # Filename first, then the nearest folder: F&FC files its ADVs as 2022/F&FC ADV Part 2.pdf.
            as_of, sort_key = parse_date(part)
            if as_of:
                date_source = "filename" if i == 0 else f"folder: {part}"
                break
        marks = bookmarks(pdf) if pdf.exists() else []
        sections, structure = build_sections(pages, marks)
        docs.append(
            {
                "doc_id": hashlib.md5(path.encode(), usedforsecurity=False).hexdigest()[:10],
                "path": path,
                "name": path.split("/")[-1],
                "folder": "/".join(path.split("/")[:-1]),
                "pages": len(pages),
                "chars": sum(p["chars"] for p in pages),
                "scan_pages": sum(p["chars"] < 50 for p in pages),
                "byte_hash": byte_hash,
                "text_hash": hashlib.sha256(text.encode()).hexdigest()[:16],
                "doc_type": doc_type,
                "type_source": type_source,
                "tier": tier,
                "status": status_of(path),
                "as_of": as_of,
                "date_source": date_source,
                "_sort": sort_key,
                "vehicle_hint": vehicle_hint(path),
                "stem": title_stem(path),
                "sections": sections,
                "structure": structure,
                "duplicate_of": None,
                "series": None,
                "version_group": None,
                "group_reason": None,
                "canonical": True,
                "superseded_by": None,
            }
        )

    def preference(d):
        # Lower sorts first: best status, then newest date, then shortest path.
        k = d["_sort"] or (0, 0, 0)
        return (STATUS_RANK[d["status"]], tuple(-x for x in k), len(d["path"]))

    # 1. Exact duplicates: identical extracted text. The only automatic collapse.
    by_text = defaultdict(list)
    for d in docs:
        if d["chars"] > 200:
            by_text[d["text_hash"]].append(d)
    for group in by_text.values():
        if len(group) > 1:
            keep = min(group, key=preference)
            for d in group:
                if d is not keep:
                    d["duplicate_of"], d["canonical"] = keep["doc_id"], False

    live = [d for d in docs if not d["duplicate_of"]]

    # 2. Series. Periodic documents with one title and many periods (audits by year,
    #    quarterly statements, monthly notes). Grouped for display; every member stays canonical.
    by_stem = defaultdict(list)
    for d in live:
        if d["stem"] and d["doc_type"] != "unclassified":
            by_stem[(d["doc_type"], d["stem"])].append(d)
    for (t, _), members in by_stem.items():
        if t in SERIES_TYPES and len(members) > 1:
            sid = min(m["doc_id"] for m in members)
            for d in members:
                d["series"] = sid

    # 3. Version groups. Two ways in, and nothing chains beyond them:
    #    a) same type and title stem (not a series type), e.g. the Q2 and Q3 deck;
    #    b) a draft or archive file linked to its single best same-type match, at >= 60%
    #       overlap. Similar text alone never links two final files: templated case studies
    #       and sibling-property PPMs (96% overlap) look alike and are different documents.
    group_of, reason = {}, {}
    for (t, _), members in by_stem.items():
        if t not in SERIES_TYPES and len(members) > 1:
            gid = min(m["doc_id"] for m in members)
            for d in members:
                group_of[d["doc_id"]] = gid
            reason[gid] = "same title, different date or status"
    shingle_cache = {}

    def sh(d):
        # 8-word shingles. Line-level comparison fails across re-flowed versions of one
        # document (a draft and final PPM: 0.21 by line, 0.83 by 8-word run).
        if d["doc_id"] not in shingle_cache:
            shingle_cache[d["doc_id"]] = word_shingles(files[d["path"]])
        return shingle_cache[d["doc_id"]]

    for d in live:
        if d["status"] not in ("draft", "archive") or d["doc_id"] in group_of or d["doc_type"] in SERIES_TYPES:
            continue
        cands = [
            o for o in live if o is not d and o["doc_type"] == d["doc_type"] and o["status"] not in ("draft", "archive")
        ]
        scored = [(containment(sh(d), sh(o)), o) for o in cands]
        if scored:
            c, best = max(scored, key=lambda x: x[0])
            if c >= 0.6:
                gid = group_of.setdefault(best["doc_id"], best["doc_id"])
                group_of[d["doc_id"]] = gid
                reason.setdefault(gid, f"draft or archive with {c:.0%} text overlap")
    groups = defaultdict(list)
    for d in live:
        if d["doc_id"] in group_of:
            groups[group_of[d["doc_id"]]].append(d)
    for gid, members in groups.items():
        if len(members) < 2:
            continue
        ranked = sorted(members, key=preference)
        order = lambda d: preference(d)[:2]  # status, then date. Path length is not evidence.
        if order(ranked[0]) == order(ranked[1]):
            # Cannot tell which is current. Keep all, and say so.
            for d in members:
                d["version_group"] = gid
                d["group_reason"] = (reason.get(gid) or "") + "; cannot tell which is current, review"
            continue
        for d in members:
            d["version_group"], d["group_reason"] = gid, reason.get(gid)
            if d is not ranked[0]:
                d["canonical"], d["superseded_by"] = False, ranked[0]["doc_id"]

    for d in docs:
        d.pop("_sort")
    summary = summarize(room.name, docs)
    room_id = re.sub(r"[^\w.-]+", "_", room.name)
    store.save_catalog(room_id, room.name, docs, summary)
    return room_id, summary, docs


def summarize(name, docs):
    pages = lambda ds: sum(d["pages"] for d in ds)
    canon = [d for d in docs if d["canonical"]]
    tiers: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "pages": 0})
    for d in canon:
        tiers[d["tier"]]["files"] += 1
        tiers[d["tier"]]["pages"] += d["pages"]
    return {
        "room": name,
        "files": len(docs),
        "pages": pages(docs),
        "exact_duplicates": {
            "files": sum(1 for d in docs if d["duplicate_of"]),
            "pages": pages([d for d in docs if d["duplicate_of"]]),
        },
        "superseded": {
            "files": sum(1 for d in docs if d["superseded_by"]),
            "pages": pages([d for d in docs if d["superseded_by"]]),
        },
        "canonical": {"files": len(canon), "pages": pages(canon)},
        "by_tier": dict(tiers),
        "core_pages": tiers["core"]["pages"],
        "type_sources": {
            k: sum(1 for d in docs if d["type_source"].split(":")[0] == k) for k in ("filename", "folder", "none")
        },
        "with_bookmarks": sum(1 for d in docs if d["structure"]["method"] == "bookmarks"),
        "with_toc": sum(1 for d in docs if d["structure"]["method"].startswith("toc")),
        "with_terms": sum(1 for d in docs if d["structure"]["terms"]),
        "unstructured": sum(1 for d in docs if not d["sections"]),
        "sections": sum(len(d["sections"]) for d in docs),
        "scan_pages": sum(d["scan_pages"] for d in docs),
    }


def load(folder):
    """Catalog docs for a room, building it when missing or from before the section index."""
    hit = store.catalog(re.sub(r"[^\w.-]+", "_", Path(folder).name))
    if hit and hit[1] and all("structure" in d for d in hit[1]):
        return hit[1]
    return build(folder)[2]
