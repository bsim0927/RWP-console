"""Quote verification. Every case runs against each implementation in IMPLS, so the Rust
port is held to exactly the Python behaviour."""

import json
import random
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from sg import dataroom
from sg.dataroom import DataRoom

IMPLS: dict[str, Callable[[str, str], str | None]] = {"python": dataroom.match_quote_py}
if dataroom.match_quote_rs:
    IMPLS["rust"] = dataroom.match_quote_rs


def filler(n):
    return " ".join(f"x{i}" for i in range(n))


# A mixin, so unittest does not collect it on its own. mypy checks it as a TestCase.
_Base = unittest.TestCase if TYPE_CHECKING else object


class MatchQuoteCases(_Base):  # type: ignore[valid-type,misc]
    match: Callable[[str, str], str | None]  # set by the per-implementation subclasses below

    def m(self, text, quote):
        return type(self).match(text, quote)

    # exact

    def test_exact_substring(self):
        self.assertEqual(self.m("The minimum investment is $250,000.", "minimum investment is $250,000"), "exact")

    def test_exact_ignores_case_and_whitespace(self):
        self.assertEqual(self.m("Minimum\n  Investment:\t$1,000,000", "minimum investment: $1,000,000"), "exact")

    def test_exact_treats_nbsp_as_space(self):
        self.assertEqual(self.m("accredited investors only", "accredited investors only"), "exact")

    def test_exact_works_for_short_quotes(self):
        self.assertEqual(self.m("Fee: 2%", "fee: 2%"), "exact")

    # no match

    def test_empty_quote(self):
        self.assertIsNone(self.m("anything", ""))

    def test_empty_page(self):
        self.assertIsNone(self.m("", "a quote that is long enough"))

    def test_absent_quote(self):
        self.assertIsNone(self.m("The fund charges a 2% management fee.", "the fund charges no management fee at all"))

    def test_words_out_of_order(self):
        self.assertIsNone(self.m("one two three four five six", "one three two four five six"))

    def test_short_quote_never_reflows(self):
        # Four words, in order, split by a label: too short to trust a loose match.
        self.assertIsNone(self.m("minimum Amount: investment is high", "minimum investment is high"))

    # reflowed

    def test_two_column_label_between_words(self):
        page = "The minimum Amount: initial investment in the Fund is $250,000"
        quote = "the minimum initial investment in the fund is $250,000"
        self.assertEqual(self.m(page, quote), "reflowed")

    def test_punctuation_differences_reflow(self):
        page = "Management fee - 1.5% per annum, payable quarterly"
        quote = "management fee: 1.5% per annum payable quarterly"
        self.assertEqual(self.m(page, quote), "reflowed")

    def test_curly_apostrophe(self):
        page = "the Fund’s general partner may waive the minimum"
        quote = "the fund's general partner may waive the minimum"
        self.assertEqual(self.m(page, quote), "reflowed")

    def test_gap_of_five_words_allowed(self):
        q = "alpha bravo charlie delta echo"
        self.assertEqual(self.m(f"alpha bravo {filler(5)} charlie delta echo", q), "reflowed")

    def test_gap_of_six_words_rejected(self):
        # MAX_GAP = 6 means the next word sits at most 6 positions on, so 5 words between.
        q = "alpha bravo charlie delta echo"
        self.assertIsNone(self.m(f"alpha bravo {filler(6)} charlie delta echo", q))

    def test_total_span_limit(self):
        # Five words allow a span of 5 * 1.3 + 4 = 10.5 words. Each gap is legal, the total is not.
        q = "alpha bravo charlie delta echo"
        ok = f"alpha {filler(2)} bravo {filler(2)} charlie delta echo"  # span 9
        too_long = f"alpha {filler(3)} bravo {filler(3)} charlie delta echo"  # span 11
        self.assertEqual(self.m(ok, q), "reflowed")
        self.assertIsNone(self.m(too_long, q))

    def test_tries_every_occurrence_of_first_word(self):
        page = f"alpha {filler(9)} alpha bravo charlie {filler(1)} delta echo"
        self.assertEqual(self.m(page, "alpha bravo charlie delta echo"), "reflowed")

    def test_match_at_end_of_page(self):
        self.assertEqual(
            self.m(f"{filler(3)} alpha bravo x charlie delta echo", "alpha bravo charlie delta echo"), "reflowed"
        )

    def test_dollar_percent_and_decimal_are_word_characters(self):
        # "$2.5" and "2.5" are different words, so this quote does not reflow.
        self.assertIsNone(self.m("fee of 2.5 per cent annually here", "fee of $2.5 per cent annually here"))

    def test_repeated_word_tries_every_occurrence(self):
        # w1 appears at 1 and 4. From 1, w2 at 8 is out of reach; from 4 it is not.
        # Every gap is legal and the span is 16 <= 17.
        q = " ".join(f"w{i}" for i in range(10))
        page = "w0 w1 f f w1 f f f w2 " + " ".join(f"w{i}" for i in range(3, 10))
        self.assertEqual(self.m(page, q), "reflowed")

    def test_repeated_word_still_respects_span(self):
        q = " ".join(f"w{i}" for i in range(10))
        page = "w0 w1 f f w1 f f f f f w2 " + " ".join(f"w{i} f" for i in range(3, 10))
        self.assertIsNone(self.m(page, q))

    def test_whitespace_only_quote(self):
        # norm("  ") is "", and "" is in every page, so this must be caught first.
        self.assertIsNone(self.m("any page at all", "   \n\t"))
        self.assertIsNone(self.m("", " "))


for _name, _fn in IMPLS.items():
    _cls = type(f"MatchQuote_{_name}", (MatchQuoteCases, unittest.TestCase), {"match": staticmethod(_fn)})
    globals()[_cls.__name__] = _cls
del _cls  # or unittest collects the last class twice


@unittest.skipUnless("rust" in IMPLS, "Rust extension not built (run ./build-rust.sh)")
class Parity(unittest.TestCase):
    """Random pages and quotes from a small vocabulary, so repeats, gaps and near misses are common."""

    VOCAB = ["the", "fund", "fee", "of", "2%", "$1.5", "investor", "minimum", "a", "B", "Fund's", "’s", "3(c)(7)"]

    def test_random_pages_agree(self):
        rng = random.Random(7)
        for _ in range(20000):
            page = " ".join(rng.choice(self.VOCAB) for _ in range(rng.randint(0, 40)))
            pw = page.split()
            if pw and rng.random() < 0.7:
                i = rng.randrange(len(pw))
                span = pw[i : i + rng.randint(1, 15)]
                kept = [w for w in span if rng.random() > 0.25]  # drop words to make gaps
                if rng.random() < 0.3:
                    kept.insert(rng.randint(0, len(kept)), rng.choice(self.VOCAB))
                quote = " ".join(kept)
            else:
                quote = " ".join(rng.choice(self.VOCAB) for _ in range(rng.randint(0, 10)))
            with self.subTest(page=page, quote=quote):
                self.assertEqual(IMPLS["rust"](page, quote), IMPLS["python"](page, quote))

    def test_unicode_whitespace_and_case_agree(self):
        odd = [" ", " ", "　", "\x1c", "\x1f", "\x85", "​", "﻿", "\t", "\n"]
        letters = ["İ", "K", "Σ", "ß", "I", "a", "1", "%"]
        rng = random.Random(11)
        for _ in range(5000):
            page = "".join(rng.choice(odd + letters) for _ in range(rng.randint(0, 30)))
            quote = "".join(rng.choice(odd + letters) for _ in range(rng.randint(1, 10)))
            with self.subTest(page=repr(page), quote=repr(quote)):
                self.assertEqual(IMPLS["rust"](page, quote), IMPLS["python"](page, quote))


def brute_force(text, quote):
    """The rule written out directly: try every in-order placement of the quote's words."""
    if not dataroom.norm(quote):
        return None
    if dataroom.norm(quote) in dataroom.norm(text):
        return "exact"
    q, t = dataroom.words(quote), dataroom.words(text)
    if len(q) < 5:
        return None

    def ends(j, pos):  # every position the last quote word can land on, from q[j] at pos
        if j == len(q) - 1:
            yield pos
            return
        for k in range(pos + 1, min(pos + 1 + dataroom.MAX_GAP, len(t))):
            if t[k] == q[j + 1]:
                yield from ends(j + 1, k)

    for start in range(len(t)):
        if t[start] == q[0] and any(e - start + 1 <= len(q) * 1.3 + 4 for e in ends(0, start)):
            return "reflowed"
    return None


class AgainstBruteForce(unittest.TestCase):
    """Few distinct words, so repeats, competing paths and the span limit all come up."""

    def test_random_cases(self):
        rng = random.Random(3)
        vocab = ["a", "b", "c", "d", "x"]
        hits = 0
        for _ in range(20000):
            page = " ".join(rng.choice(vocab) for _ in range(rng.randint(5, 30)))
            quote = " ".join(rng.choice(vocab[:4]) for _ in range(rng.randint(5, 9)))
            want = brute_force(page, quote)
            hits += want == "reflowed"
            for name, fn in IMPLS.items():
                with self.subTest(impl=name, page=page, quote=quote):
                    self.assertEqual(fn(page, quote), want)
        self.assertGreater(hits, 500)  # the generator must actually exercise reflowed matches


class Dispatch(unittest.TestCase):
    def test_lone_surrogate_falls_back_to_python(self):
        page = "bad \ud800 text: the minimum investment is $250,000"
        self.assertEqual(dataroom.match_quote(page, "minimum investment is $250,000"), "exact")


class DataRoomVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        idx = Path(self.tmp.name) / "_index"
        idx.mkdir()
        rows = [{"file": "a.pdf", "page": 3, "text": "The minimum investment is $250,000."}]
        (idx / "pages.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        self.room = DataRoom(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_quote_on_cited_page(self):
        self.assertEqual(self.room.verify_quote("a.pdf", 3, "minimum investment is $250,000"), "exact")

    def test_wrong_page(self):
        self.assertIsNone(self.room.verify_quote("a.pdf", 4, "minimum investment is $250,000"))

    def test_unknown_file(self):
        self.assertIsNone(self.room.verify_quote("b.pdf", 3, "minimum investment is $250,000"))

    def test_missing_quote(self):
        self.assertIsNone(self.room.verify_quote("a.pdf", 3, None))


if __name__ == "__main__":
    unittest.main()
