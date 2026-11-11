"""Contradictions across documents (decision F3)."""

from sg import consistency
from sg.consistency import in_code, kinds, number, verified

KIND = {"Terms.pdf": "filed", "Deck.pdf": "marketing", "DDQ.pdf": "other"}


def fact(field, value, file, page=1):
    return {"field": field, "value": value, "file": file, "page": page, "quote": value}


def test_number_reads_the_first_percentage_or_dollar_amount():
    assert number("1.35% of NAV") == ("%", 1.35)
    assert number("$500,000") == ("$", 500000.0)
    assert number("$5 million minimum") == ("$", 5000000.0)
    assert number("$10k") == ("$", 10000.0)
    assert number("accredited investors") is None


def test_figures_that_differ_between_documents_are_a_finding():
    found, wording = in_code(
        [fact("management_fee", "1.35%", "Terms.pdf"), fact("management_fee", "1.55%", "Deck.pdf")], KIND
    )
    assert wording == {}
    assert [(c["field"], c["summary"], c["marketing_vs_filed"], c["source"]) for c in found] == [
        ("management_fee", "Documents give 1.35%, 1.55%", True, "code")
    ]


def test_matching_figures_and_figures_inside_one_document_are_not():
    same = [fact("minimum_investment", "$25,000", "Terms.pdf"), fact("minimum_investment", "$25k", "DDQ.pdf")]
    assert in_code(same, KIND) == ([], {})
    one_doc = [
        fact("servicing_fee", "0.85% Class S", "Terms.pdf"),
        fact("servicing_fee", "0.25% Class D", "Terms.pdf", 2),
    ]
    assert in_code(one_doc, KIND) == ([], {})  # two share classes, not a contradiction


def test_wording_is_left_for_a_model():
    facts = [
        fact("administrator", "Harbor Fund Services", "Terms.pdf"),
        fact("administrator", "Monroe affiliate", "DDQ.pdf"),
    ]
    found, wording = in_code(facts, KIND)
    assert found == [] and list(wording) == ["administrator"]


def test_kinds_come_from_document_types():
    cat = [
        {"path": "a.pdf", "doc_type": "deck"},
        {"path": "b.pdf", "doc_type": "offering document"},
        {"path": "c.pdf", "doc_type": "ddq"},
    ]
    assert kinds(cat) == {"a.pdf": "marketing", "b.pdf": "filed", "c.pdf": "other"}


class Room:
    def __init__(self, pages):
        self.by_key = {(f, p): {"file": f, "page": p, "text": t} for (f, p), t in pages.items()}

    def verify_quote(self, file, page, quote):
        row = self.by_key.get((file, page))
        return "exact" if row and quote in row["text"] else None


def test_a_reported_conflict_is_kept_only_when_both_quotes_are_on_their_pages():
    room = Room({("Deck.pdf", 1): "Targeting $400 million.", ("Terms.pdf", 2): "Fund size: $250 million."})
    good = {
        "topic": "Size",
        "summary": "s",
        "marketing": {"file": "Deck.pdf", "page": 1, "quote": "Targeting $400 million."},
        "filed": {"file": "Terms.pdf", "page": 2, "quote": "Fund size: $250 million."},
    }
    made_up = {**good, "filed": {"file": "Terms.pdf", "page": 2, "quote": "Fund size: $900 million."}}
    assert verified(room, [good, made_up]) == [{**good, "source": "model"}]


def test_marketing_pages_take_decks_and_the_filed_summary_sections():
    room = Room({("Deck.pdf", 1): "d1", ("Deck.pdf", 2): "d2", ("PPM.pdf", 7): "terms", ("PPM.pdf", 30): "risk"})
    cat = [
        {"path": "Deck.pdf", "doc_type": "deck", "canonical": True, "pages": 2},
        {
            "path": "PPM.pdf",
            "doc_type": "offering document",
            "canonical": True,
            "pages": 80,
            "sections": [{"title": "Summary of Terms", "start": 7, "end": 7}, {"title": "Tax", "start": 50, "end": 60}],
        },
    ]
    mk, fl = consistency.marketing_pages(room, cat)
    assert [(p["file"], p["page"]) for p in mk] == [("Deck.pdf", 1), ("Deck.pdf", 2)]
    assert [(p["file"], p["page"]) for p in fl] == [("PPM.pdf", 7)]
