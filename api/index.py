"""Vercel's function for the whole console: vercel.json rewrites every path here, to the WSGI app in server.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the bundle's root, where server.py lives

from server import app  # noqa: E402,F401  (Vercel's runtime looks for `app`)
