#!/usr/bin/env python3
"""One-off import of PIPELINE.md's statuses and owners into the database named by DATABASE_URL.

    uv run python scripts/import_pipeline_md.py <PIPELINE.md> <data-root>          # show the mapping
    uv run python scripts/import_pipeline_md.py <PIPELINE.md> <data-root> --yes    # import

After this the console never reads PIPELINE.md again: statuses live in fund_status and move only by the CIO.
Each row is matched to a data room under <data-root> by manager and strategy, as the console used to match
it. A row with no data room is still kept, under the slug of "Manager - Strategy", so a room filed later with
that name picks it up. The row's last action, next action and material date go in the import note. Owners
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


def room_for(row, rooms):
    """The data room whose folder names this row's manager and shares the most strategy words."""
    best, score = None, -1
    for name in rooms:
        mgr, _, strat = name.partition(" - ")
        if words(row["Manager"]) and words(row["Manager"]) <= words(mgr) | words(name):
            s = len(words(strat) & words(row.get("Strategy", "")))
            if s > score:
                best, score = name, s
    return best


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
    rooms = sorted({p.parent.parent.name for p in a.data_root.rglob("_index/pages.jsonl")})
    plan = []
    for r in rows(text):
        room = room_for(r, rooms)
        name = room or f"{r['Manager']} - {r['Strategy']}".strip(" -")
        plan.append((slug(name), bool(room), r))
    target = urlsplit(db.url())
    print(f"target: {target.hostname}:{target.port}{target.path} as {target.username}")
    for fid, matched, r in plan:
        print(f"  {r['Status']:<24} {fid}{'' if matched else '   (no data room yet)'}")
    print(f"found:  {len(plan)} rows, {sum(m for _, m, _ in plan)} matched to a data room")
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
