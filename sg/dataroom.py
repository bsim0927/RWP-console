"""Load a data room index (_index/pages.jsonl) and retrieve pages for a gate."""
import json
import re
from pathlib import Path


MAX_GAP = 6  # the next quoted word is at most this many words on (5 between), e.g. a left-column label


def words(s):
    return re.findall(r"[a-z0-9$%.]+", s.lower().replace("’", "'"))


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def match_quote_py(text, quote):
    """'exact', 'reflowed', or None. Reflowed means every word of the quote appears on the
    page in order, interrupted only by short runs such as a two-column label ("Amount:")."""
    if not quote or not norm(quote):
        return None
    if norm(quote) in norm(text):
        return "exact"
    q, t = words(quote), words(text)
    if len(q) < 5:
        return None
    for start in (i for i, w in enumerate(t) if w == q[0]):
        # Every position the current quote word can sit at. Keeping all of them, not just the
        # nearest, matters when a word repeats: a later "the" may be the one that reaches on.
        reach = {start}
        for w in q[1:]:
            reach = {k for p in reach for k in range(p + 1, min(p + 1 + MAX_GAP, len(t))) if t[k] == w}
            if not reach:
                break
        if reach and min(reach) - start + 1 <= len(q) * 1.3 + 4:
            return "reflowed"
    return None


try:
    # Rust build of match_quote_py, held to it by tests/test_match_quote.py. Built by ./build-rust.sh.
    from ._verify import match_quote as match_quote_rs
except ImportError:
    match_quote_rs = None


def match_quote(text, quote):
    if match_quote_rs:
        try:
            return match_quote_rs(text, quote)
        except UnicodeEncodeError:
            pass  # a lone surrogate in the text, which Rust strings cannot hold
    return match_quote_py(text, quote)


class DataRoom:
    def __init__(self, folder):
        self.folder = Path(folder)
        idx = self.folder / "_index" / "pages.jsonl"
        if not idx.exists():
            raise SystemExit(f"no index at {idx}")
        with idx.open() as fh:
            self.pages = [json.loads(line) for line in fh]
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
        p = self.by_key.get((file, page))
        return match_quote(p["text"], quote) if p else None
