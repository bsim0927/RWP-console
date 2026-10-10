#!/usr/bin/env python3
"""Usage: python3 catalog.py <data-room-folder>  -> catalog/<room>/documents.jsonl, summary.json"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sg.catalog import build  # noqa: E402

out, summary, docs = build(sys.argv[1])
print(json.dumps(summary, indent=2))
print(f"catalog: {out}")
