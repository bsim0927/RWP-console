#!/usr/bin/env python3
"""Usage: python3 screen.py <data-room-folder> [--extractor claude] [--judge claude|jev] [--gates a,b]"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sg.pipeline import run

ap = argparse.ArgumentParser()
ap.add_argument("data_room", help="folder containing _index/pages.jsonl")
ap.add_argument("--extractor", default="claude", choices=["claude"])
ap.add_argument("--judge", default="jev", choices=["claude", "jev"])
ap.add_argument("--gates", help="comma-separated gate ids")
a = ap.parse_args()
out, summary, results = run(a.data_room, a.extractor, a.judge, a.gates.split(",") if a.gates else None)
print(f"{summary['fund']}: {summary['disposition']}")
for r in results:
    print(f"  {r['gate']:<22} {r['result']:<22} review={r.get('review')}")
print(f"log: {out}")
