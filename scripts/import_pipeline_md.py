#!/usr/bin/env python3
"""One-off import of PIPELINE.md's statuses and owners into the database named by DATABASE_URL.

    uv run python scripts/import_pipeline_md.py <PIPELINE.md> <data-root>          # show the mapping
    uv run python scripts/import_pipeline_md.py <PIPELINE.md> <data-root> --yes    # import

After this the console never reads PIPELINE.md again: statuses live in fund_status and move only by the CIO.
Each row is matched to a fund folder under <data-root> (indexed or not) by its manager and at least one telling
strategy word, and each folder goes to one row at most. A row with no folder is still kept, under the slug of
"Manager - Strategy", so a folder filed later with that name picks it up. The row's last action, next action and material date go in the import note. Owners
fill an empty intake owner only. Re-running is safe: funds that already have a status are skipped.
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sg import db, fund_status, store  # noqa: E402

slug = lambda n: re.sub(r"[^\w.-]+", "_", n)


def rows(text):
    """Every table row, as {header: cell} with ** stripped."""
    out, header = [], None
    for line in text.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
        elif not all(set(c) <= set("-: ") for c in cells):
            out.append(dict(zip(header, cells, strict=False)))
    return [r for r in out if r.get("Manager") and r.get("Status")]


def words(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


GENERIC = {"fund", "funds", "and", "the", "of", "for", "a", "an"}  # shared by too many strategies to tell them apart


PLACEHOLDER = {"tbd", "unidentified", "unknown"}  # a folder whose strategy is not known yet


def initials(text):
    return "".join(w[0] for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in GENERIC)


def fit(row, name):
    """How well a fund folder fits a row: the strategy words they share, or None when it is not this fund.
    The managers must match (either name may be the longer: "HPS" and "HPS BlackRock"), and so must at least
    one telling strategy word, or an acronym ("ABF" for "Asset-Backed Finance"), so that two funds from one
    manager (BREIT and BCRED) never share a folder. A folder named for the manager alone, or with a placeholder
    strategy ("TBD"), fits on the manager."""
    mgr, _, strat = name.partition(" - ")
    m, fm = words(row["Manager"]), words(mgr)
    if not m or not fm or not (m <= fm | words(name) or fm <= m):
        return None
    if not strat or words(strat) <= PLACEHOLDER:
        return 0
    shared = (words(strat) & words(row.get("Strategy", ""))) - GENERIC
    acronym = any(len(w) > 1 and w in initials(row.get("Strategy", "")) for w in words(strat) - GENERIC)
    return len(shared) + acronym or None


def assign(rows_, rooms):
    """{row index: folder}, each folder given to at most one row, best fit first."""
    fits = sorted(
        ((f, i, name) for i, r in enumerate(rows_) for name in rooms if (f := fit(r, name)) is not None),
        key=lambda x: -x[0],
    )
    out: dict[int, str] = {}
    for _, i, name in fits:
        if i not in out and name not in out.values():
            out[i] = name
    return out


def note_for(row, updated):
    keep = [
        f"{k}: {row[k]}"
        for k in ("Last action", "Material on file", "Next action")
        if row.get(k) not in (None, "", "–")
    ]
    return f"Imported from PIPELINE.md ({updated or 'undated'}). " + "; ".join(keep)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pipeline_md", type=Path)
    ap.add_argument("data_root", type=Path)
    ap.add_argument("--yes", action="store_true", help="write to the database (default: dry run)")
    a = ap.parse_args()
    text = a.pipeline_md.read_text(errors="replace")
    updated = (re.search(r"Last updated:\s*(\S+)", text) or [None, None])[1]
    # Every fund folder, indexed or not: the data root's own folders, and indexed rooms wherever they sit.
    rooms = {p.parent.parent.name for p in a.data_root.rglob("_index/pages.jsonl")}
    rooms |= {d.name for d in a.data_root.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))}
    table = rows(text)
    match = assign(table, sorted(rooms))
    plan = []
    for i, r in enumerate(table):
        name = match.get(i) or f"{r['Manager']} - {r['Strategy']}".strip(" -")
        plan.append((slug(name), i in match, r))
    target = urlsplit(db.url())
    print(f"target: {target.hostname}:{target.port}{target.path} as {target.username}")
    for fid, matched, r in plan:
        print(f"  {r['Status']:<24} {fid}{'' if matched else '   (no data room yet)'}")
    print(f"found:  {len(plan)} rows, {sum(m for _, m, _ in plan)} matched to a fund folder")
    if not a.yes:
        print("dry run; re-run with --yes to import")
        return
    added = owners = 0
    for fid, _, r in plan:
        added += fund_status.import_status(fid, r["Status"], note_for(r, updated))
        owner = r.get("Owner", "").strip()
        if owner and owner.lower() != "unassigned" and not store.intake(fid)["owner"]:
            store.save_intake(fid, {"owner": owner})
            owners += 1
    print(f"imported: {added} statuses ({len(plan) - added} funds already had one), {owners} owners")


if __name__ == "__main__":
    main()
