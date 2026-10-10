#!/usr/bin/env python3
"""Usage: python3 catalog.py <data-room-folder>  -> the room's catalog, saved to the database"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sg.catalog import build  # noqa: E402

room_id, summary, docs = build(sys.argv[1])
print(json.dumps(summary, indent=2))
print(f"catalog saved: {room_id}")
