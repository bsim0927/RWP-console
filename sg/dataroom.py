"""Load a data room index (_index/pages.jsonl) and retrieve pages for a gate."""
import json
import re
from pathlib import Path


MAX_GAP = 6  # words that may sit between two quoted words, e.g. a left-column label


def words(s):
    return re.findall(r"[a-z0-9$%.]+", s.lower().replace("’", "'"))


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


class DataRoom:
    def __init__(self, folder):
        self.folder = Path(folder)
        idx = self.folder / "_index" / "pages.jsonl"
        if not idx.exists():
            raise SystemExit(f"no index at {idx}")
        self.pages = [json.loads(line) for line in idx.open()]
        self.by_key = {(p["file"], p["page"]): p for p in self.pages}
        self.name = self.folder.name

    def retrieve(self, keywords, top_k=6, max_chars=6000):
        """Keyword-count ranking. Crude on purpose; swap for embeddings later."""
        kws = [k.lower() for k in keywords]
        scored = []
        for p in self.pages:
            t = p["text"].lower()
            score = sum(t.count(k) for k in kws)
            if score:
                scored.append((score, p))
        scored.sort(key=lambda x: -x[0])
        return [dict(p, text=p["text"][:max_chars]) for _, p in scored[:top_k]]

    def verify_quote(self, file, page, quote):
        """'exact', 'reflowed', or None. Reflowed means every word of the quote appears on the
        page in order, interrupted only by short runs such as a two-column label ("Amount:")."""
        p = self.by_key.get((file, page))
        if not (p and quote):
            return None
        if norm(quote) in norm(p["text"]):
            return "exact"
        q, t = words(quote), words(p["text"])
        if len(q) < 5:
            return None
        for start in (i for i, w in enumerate(t) if w == q[0]):
            j, pos, ok = 1, start, True
            while j < len(q):
                nxt = next((k for k in range(pos + 1, min(pos + 1 + MAX_GAP, len(t))) if t[k] == q[j]), None)
                if nxt is None:
                    ok = False
                    break
                pos, j = nxt, j + 1
            if ok and pos - start + 1 <= len(q) * 1.3 + 4:
                return "reflowed"
        return None
