#!/usr/bin/env python3
"""Build the console's data root from a Google Drive download: one folder per fund, fund documents only.

    uv run python scripts/reorganize_data_root.py <drive-download> <new-data-root>          # show the plan
    uv run python scripts/reorganize_data_root.py <drive-download> <new-data-root> --yes    # copy

The Drive keeps funds under numbered stage folders (1-Intake, 2-Managers, ...) beside the firm's own folders,
and a large download arrives split into parts (RWP-<stamp>-1-001, -002, ...). The console uses none of that:
it wants <new-data-root>/<Manager - Strategy>/ with the fund's files. This script copies:

  - every fund folder: a folder directly under a stage folder that holds at least one indexed data room
    (so 1-Intake and 2-Managers, and not 3-Process or 6-Research), merged across the download parts;
  - everything inside it, keeping its subfolders and its _index, except Markdown (.md) files, which are notes
    written on the Drive, not documents from the fund.

Firm folders, top-level files, _inbox and every .md file stay behind. A page index that names a file the way
it was spelled before Drive's download replaced characters such as ' with _ is pointed at the downloaded file. The download is only read, never
changed; <new-data-root> must be new or empty. Two different files at the same place in one fund are reported
and the first is kept.
"""

import argparse
import filecmp
import json
import re
import shutil
import sys
from pathlib import Path

DRIVE_PART = re.compile(r".+-\d{8}T\d{6}Z-\d+-\d{3}$")
STAGE = re.compile(r"^\d+-")
SKIP_FILES = {".DS_Store", "desktop.ini", "Thumbs.db"}
DRIVE_REPLACES = re.compile(r"['\"*:<>?|]")  # characters a Drive download writes as _


def layers(download):
    """The download's parts, each at the folder that holds the stage folders."""
    parts = [p for p in sorted(download.iterdir()) if p.is_dir() and DRIVE_PART.match(p.name)] or [download]
    out = []
    for p in parts:
        kids = [c for c in p.iterdir() if c.is_dir() and not c.name.startswith(".")]
        out.append(kids[0] if len(kids) == 1 and not any(STAGE.match(c.name) for c in kids) else p)
    return out


def fund_folders(download):
    """{fund name: [its folder in each part]} for every stage folder that holds an indexed data room."""
    stages: dict[str, list[Path]] = {}
    for layer in layers(download):
        for s in layer.iterdir():
            if s.is_dir() and STAGE.match(s.name):
                stages.setdefault(s.name, []).append(s)
    funds: dict[str, list[Path]] = {}
    clashes = []
    for name, dirs in sorted(stages.items()):
        if not any(next(d.glob("*/_index/pages.jsonl"), None) for d in dirs):
            continue  # a firm folder (process, research, letters...), not a fund stage
        for d in dirs:
            for f in sorted(d.iterdir()):
                if f.is_dir() and not f.name.startswith(("_", ".")):
                    if f.name in funds and funds[f.name][0].parent.name != name:
                        clashes.append(f"{f.name}: under both {funds[f.name][0].parent.name} and {name}")
                    funds.setdefault(f.name, []).append(f)
    return funds, clashes


def plan(funds):
    """(copies [(src, relative dest)], skipped .md count, conflicts) across every fund."""
    copies, skipped_md, conflicts = [], 0, []
    for name, dirs in sorted(funds.items()):
        seen: dict[Path, Path] = {}
        for d in dirs:
            for src in sorted(p for p in d.rglob("*") if p.is_file()):
                if src.name in SKIP_FILES:
                    continue
                if src.suffix.lower() == ".md":
                    skipped_md += 1
                    continue
                rel = Path(name) / src.relative_to(d)
                if rel in seen:
                    if not filecmp.cmp(seen[rel], src, shallow=False):
                        conflicts.append(f"{rel}: differs between download parts; keeping {seen[rel]}")
                    continue
                seen[rel] = src
                copies.append((src, rel))
    return copies, skipped_md, conflicts


def repair_index(room):
    """Point index entries at the downloaded spelling of their file. Returns how many pages were repointed."""
    idx = room / "_index" / "pages.jsonl"
    if not idx.exists():
        return 0
    lines, fixed = [], 0
    for line in idx.read_text().splitlines():
        rec = json.loads(line)
        if not (room / rec["file"]).exists() and (room / DRIVE_REPLACES.sub("_", rec["file"])).exists():
            rec["file"], fixed = DRIVE_REPLACES.sub("_", rec["file"]), fixed + 1
        lines.append(json.dumps(rec))
    if fixed:
        idx.write_text("\n".join(lines) + "\n")
    return fixed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("download", type=Path, help="the Drive download (the folder holding the RWP-<stamp> parts)")
    ap.add_argument("dest", type=Path, help="the new data root; must be new or empty")
    ap.add_argument("--yes", action="store_true", help="copy (default: show the plan only)")
    a = ap.parse_args()
    if a.dest.exists() and any(a.dest.iterdir()):
        sys.exit(f"{a.dest} is not empty; choose a new folder")
    if a.dest.resolve().is_relative_to(a.download.resolve()):
        sys.exit("the new data root must be outside the download")
    funds, clashes = fund_folders(a.download)
    copies, skipped_md, conflicts = plan(funds)
    indexed = sum((d / "_index" / "pages.jsonl").exists() for dirs in funds.values() for d in dirs)
    with_files = len({rel.parts[0] for _, rel in copies})
    size = sum(src.stat().st_size for src, _ in copies)
    print(f"from: {a.download}  ({len(layers(a.download))} download part(s))")
    print(f"to:   {a.dest}")
    print(
        f"funds: {with_files} with documents ({indexed} with a page index); {len(funds) - with_files} hold only notes"
    )
    print(f"files: {len(copies)} to copy, {size / 1e6:,.0f} MB; {skipped_md} .md files left behind")
    for line in clashes + conflicts:
        print(f"  ! {line}")
    if not a.yes:
        print("dry run; re-run with --yes to copy")
        return
    for src, rel in copies:
        out = a.dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    repointed = sum(repair_index(room) for room in a.dest.iterdir() if room.is_dir())
    print(f"copied {len(copies)} files into {with_files} fund folders; {repointed} indexed pages repointed at")
    print(f"their downloaded file name. Point RWP_DATA_ROOT at {a.dest}")


if __name__ == "__main__":
    main()
