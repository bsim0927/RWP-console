"""Document search: page text, plus the file names and paths that evidence fields cite."""

import json
import tempfile
import unittest
from pathlib import Path

from sg.datasource import LocalSource

PPM = "01 Inbound/Monroe Capital OpCo - PPM.pdf"


class Search(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.room = self.root / "Monroe Capital - ABF"
        (self.room / "_index").mkdir(parents=True)
        rows = [
            {"file": PPM, "page": 1, "text": "PRIVATE PLACEMENT MEMORANDUM\nMonroe Capital ABF OpCo"},
            {"file": PPM, "page": 64, "text": "A purchase of our Shares is appropriate only for accredited investors."},
            {"file": "01 Inbound/Dataroom/Term Sheet.pdf", "page": 2, "text": "Minimum purchase: $10,000."},
        ]
        (self.room / "_index" / "pages.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.addCleanup(self.tmp.cleanup)

    def search(self, q):
        return LocalSource(self.root).search(q)

    def test_finds_file_by_the_name_evidence_cites(self):
        for q in ("Monroe Capital OpCo - PPM.pdf", PPM, "opco ppm"):
            hits = self.search(q)
            self.assertTrue(hits, q)
            self.assertEqual((hits[0]["file"], hits[0]["page"], hits[0]["by_name"]), (PPM, 1, True), q)
            self.assertEqual(hits[0]["path"], f"Monroe Capital - ABF/{PPM}")

    def test_name_match_lists_the_file_once(self):
        self.assertEqual(len(self.search("PPM.pdf")), 1)

    def test_name_matches_rank_above_page_text(self):
        hits = self.search("inbound")
        self.assertEqual([h["by_name"] for h in hits], [True, True])
        hits = self.search("accredited")
        self.assertEqual([(h["file"], h["page"]) for h in hits], [(PPM, 64)])
        self.assertNotIn("by_name", hits[0])

    def test_name_needs_every_word(self):
        self.assertEqual(self.search("PPM term"), [])
