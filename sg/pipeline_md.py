"""PIPELINE.md, the CIO's pipeline table: read it, and write a fund's screen results into its row (decision G3).

Results go to both Supabase and the row. Only cells whose column already exists are written, and never Status:
moving a fund's status is the CIO's alone. Everything else in the file stays byte for byte, line endings
included, and the write is atomic.
"""

import os
import re
import tempfile
from pathlib import Path

NEVER = {"Status"}


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _rule(cells):
    return all(set(c) <= set("-: ") for c in cells)


def parse(text):
    """{"updated", "sections": [{"title", "rows": [{header: cell}]}]} with ** stripped from cells."""
    sections: list[dict] = []
    cur: dict | None = None
    header: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur, header = {"title": line[3:].strip(), "rows": []}, None
            sections.append(cur)
        elif line.startswith("|") and cur is not None:
            cells = [c.replace("**", "") for c in _cells(line)]
            if header is None:
                header = cells
            elif not _rule(cells):
                cur["rows"].append(dict(zip(header, cells, strict=False)))
        else:
            header = None
    upd = re.search(r"Last updated:\s*(\S+)", text)
    return {"updated": upd and upd.group(1), "sections": [s for s in sections if s["rows"]]}


def _words(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def match(name, rows):
    """Folder 'Manager - Strategy' -> the row for that manager with the most strategy words in common."""
    mgr, _, strat = name.partition(" - ")
    best, score = None, -1
    for r in rows:
        m = _words(r.get("Manager", ""))
        if m and m <= _words(mgr) | _words(name):
            s = len(_words(strat) & _words(r.get("Strategy", "")))
            if s > score:
                best, score = r, s
    return best


def update(text, name, values, today):
    """(new text, columns written) with the fund's row set to `values` where those columns exist."""
    bad = NEVER & set(values)
    if bad:
        raise ValueError(f"the tool never writes {', '.join(sorted(bad))}")
    lines = text.splitlines(keepends=True)
    rows: list[tuple[int, list[str], dict]] = []  # (line index, header, row)
    header: list[str] | None = None
    for i, line in enumerate(lines):
        if line.startswith("|"):
            cells = _cells(line)
            if header is None:
                header = cells
            elif not _rule(cells):
                rows.append((i, header, dict(zip(header, [c.replace("**", "") for c in cells], strict=False))))
        else:
            header = None
    hit = match(name, [r for _, _, r in rows])
    if hit is None:
        return text, []
    i, head, _ = next(x for x in rows if x[2] is hit)
    cells = _cells(lines[i])
    written = []
    for col, v in values.items():
        if col in head and v is not None:
            k = head.index(col)
            new = str(v).replace("|", "/").replace("\n", " ").strip()
            if k < len(cells) and cells[k].replace("**", "") != new:
                cells[k] = new
                written.append(col)
    if not written:
        return text, []
    end = lines[i][len(lines[i].rstrip("\r\n")) :]
    lines[i] = "| " + " | ".join(cells) + " |" + end
    out = "".join(lines)
    out = re.sub(r"(Last updated:\s*)\S+", lambda m: m.group(1) + today, out, count=1)
    return out, written


def write(path: Path, name, values, today):
    """Update the file in place, atomically. Returns the columns written."""
    text = path.read_bytes().decode()
    new, written = update(text, name, values, today)
    if written:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".pipeline-", suffix=".md")
        with os.fdopen(fd, "wb") as f:
            f.write(new.encode())
        os.replace(tmp, path)
    return written
