#!/usr/bin/env python3
"""One-off import of the pre-database local state into the database named by DATABASE_URL.

    uv run python scripts/import_local_state.py            # show what would be imported, and where
    uv run python scripts/import_local_state.py --yes      # import

Reads runs/<fund>/<stamp>/ (summary.json, gates/*.json, summary.md), runs/calls.jsonl and
catalog/<room>/ (summary.json, documents.jsonl). Re-running is safe: runs and catalogs are replaced,
calls already present are skipped. The files are left on disk as an archive.
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sg import db, store  # noqa: E402


def read_json(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def local_runs():
    for rdir in sorted((ROOT / "runs").glob("*/*/")):
        s = read_json(rdir / "summary.json")
        if not s:
            continue
        gates = [g for g in (read_json(p) for p in sorted((rdir / "gates").glob("*.json"))) if g]
        order = list(s.get("gates") or {})  # pipeline order, as the summary recorded it
        gates.sort(key=lambda g: order.index(g["gate"]) if g.get("gate") in order else len(order))
        md = rdir / "summary.md"
        yield rdir.parent.name, s, gates, md.read_text() if md.exists() else ""


def local_calls():
    log = ROOT / "runs" / "calls.jsonl"
    for line in log.read_text().splitlines() if log.exists() else []:
        try:
            yield json.loads(line)
        except ValueError:
            continue


def local_catalogs():
    for cdir in sorted((ROOT / "catalog").glob("*/")):
        s, docs = read_json(cdir / "summary.json"), cdir / "documents.jsonl"
        if s and docs.exists():
            yield cdir.name, s.get("room") or cdir.name, [json.loads(x) for x in docs.open()], s


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--yes", action="store_true", help="write to the database (default: dry run)")
    a = ap.parse_args()
    runs, calls, cats = list(local_runs()), list(local_calls()), list(local_catalogs())
    target = urlsplit(db.url())
    print(f"target: {target.hostname}:{target.port}{target.path} as {target.username}")
    print(f"found:  {len(runs)} runs, {len(calls)} model calls, {len(cats)} catalogs")
    if not a.yes:
        print("dry run; re-run with --yes to import")
        return
    for fund_id, s, gates, md in runs:
        store.save_run(fund_id, s, gates, md, replace=True)
    for c in calls:
        store.record_call(c)
    for room_id, name, docs, s in cats:
        store.save_catalog(room_id, name, docs, s)
    print(
        f"imported: {len(store.summaries())} runs, {len(store.calls())} calls, "
        f"{len(store.catalog_summaries())} catalogs now in the database"
    )


if __name__ == "__main__":
    main()
