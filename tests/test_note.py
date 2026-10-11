"""The screen note and the "what the manager must provide" list (decisions F1, F4)."""

import psycopg
import pytest

from sg import note, review, store
from sg.review import ReviewError

FUND, STAMP = "Acme_-_Fund_I", "20261001T120000"
OPS_YAML = """id: operability
extractor:
  fields:
    - { name: administrator, ask: "The administrator's name" }
    - { name: valuation_policy, ask: "The written valuation policy" }
    - { name: custody }
"""


def eff(**results):
    return {g: {"result": r} for g, r in results.items()}


def rec(gate, missing=(), contradictions=()):
    return {"gate": gate, "brief": {"facts": [], "not_found": list(missing)}, "contradictions": list(contradictions)}


def test_requests_cover_only_open_gates_reconciling_first_then_asked_fields():
    disagree = {"field": "management_fee", "summary": "Documents give 1.35%, 1.55%"}
    records = [
        rec("investor_eligibility", missing=["investor_standard"]),
        rec("total_annual_cost", contradictions=[disagree]),
        rec("operability", missing=["valuation_policy", "custody"]),
        rec("track_record"),
    ]
    asks = {
        "investor_eligibility": {"investor_standard": "Who may invest"},
        "operability": note.asks_from({"operability": OPS_YAML})["operability"],
    }
    got = note.provide_list(
        records,
        eff(
            investor_eligibility="Pass",
            total_annual_cost="Incomplete",
            operability="Incomplete",
            track_record="Incomplete",
        ),
        asks,
    )
    assert got == [
        "Reconcile the management fee: Documents give 1.35%, 1.55%",
        "The written valuation policy",  # custody has no ask: it is the analyst's check, not the manager's
        "Documents that close the track record gate",
    ]


def test_the_request_list_stops_at_eight():
    records = [rec(f"g{i}", missing=["a", "b"]) for i in range(6)]
    asks = {f"g{i}": {"a": f"A{i}", "b": f"B{i}"} for i in range(6)}
    assert len(note.provide_list(records, {f"g{i}": {"result": "Incomplete"} for i in range(6)}, asks)) == 8


@pytest.fixture
def run(db):
    gates = [
        {
            "gate": "operability",
            "result": "Incomplete",
            "review": False,
            "flags": ["Affiliated administrator"],
            "brief": {
                "facts": [{"field": "administrator", "value": "MCMA", "file": "PPM.pdf", "page": 4}],
                "not_found": ["valuation_policy"],
            },
        },
        {
            "gate": "investor_eligibility",
            "result": "Pass",
            "review": False,
            "flags": ["QP-only"],
            "brief": {"facts": [], "not_found": []},
        },
    ]
    summary = {"fund": "Acme - Fund I", "run": STAMP, "extractor": "stub", "disposition": "Under review", "gates": {}}
    store.save_run(
        FUND, summary, gates, "", {"operability": OPS_YAML, "investor_eligibility": "id: investor_eligibility\n"}
    )
    store.save_intake(FUND, {"referred_by": "Adviser network", "filed_on": "2026-10-05"})


@pytest.mark.usefixtures("run")
def test_a_draft_holds_the_header_gates_findings_and_requests():
    v = note.draft(FUND, STAMP)
    assert len(v) == 1 and v[0]["author"] == "tool" and v[0]["model"] is None
    body = v[0]["body"]
    assert body.startswith("# Acme - Fund I: screen note")
    assert "**Referred by:** Adviser network" in body and "**Screen due:** 2026-10-12" in body
    assert "1 of 2 gates pass. Open: operability." in body
    assert "| Operability | Incomplete | administrator: MCMA (PPM.pdf p.4); flag: Affiliated administrator |" in body
    assert "| Investor eligibility | Pass | flag: QP-only |" in body
    assert "## What the manager must provide\n\n1. The written valuation policy\n" in body


@pytest.mark.usefixtures("run")
def test_the_draft_reflects_analyst_review(monkeypatch):
    review.add_review(
        FUND, STAMP, "operability", "cio", "override", "Policy received by email", "Pass", "Policy.pdf", 1
    )
    body = note.draft(FUND, STAMP)[0]["body"]
    assert (
        "| Operability | Pass (analyst; screen said Incomplete) |" in body
        and "analyst: Policy received by email" in body
    )
    assert "Nothing: no gate is waiting on the manager." in body


@pytest.mark.usefixtures("run")
def test_a_failed_model_summary_falls_back_to_the_plain_one(monkeypatch):
    def boom(outline):
        raise RuntimeError("down")

    monkeypatch.setitem(note.SUMMARY_WRITERS, "stub", boom)
    v = note.draft(FUND, STAMP)[0]
    assert "1 of 2 gates pass." in v["body"] and "(Model summary unavailable: RuntimeError.)" in v["body"]
    assert v["model"] is None
    monkeypatch.setitem(note.SUMMARY_WRITERS, "stub", lambda outline: "A credit fund with one gate open.")
    v = note.draft(FUND, STAMP)[0]
    assert "A credit fund with one gate open." in v["body"] and v["model"] == "stub"


@pytest.mark.usefixtures("run")
def test_analyst_edits_are_new_versions():
    note.draft(FUND, STAMP)
    with pytest.raises(ReviewError, match="empty"):
        note.edit(FUND, STAMP, "  ", "cio")
    with pytest.raises(ReviewError, match="active reviewer"):
        note.edit(FUND, STAMP, "# Note", "nobody")
    v = note.edit(FUND, STAMP, "# Note\n\nEdited.", "cio")
    assert [(x["author"], x["reviewer"]) for x in v] == [("analyst", "CIO"), ("tool", None)]


def test_an_analyst_version_needs_its_reviewer_in_the_database_too(db, run):
    with psycopg.connect(db) as c, pytest.raises(psycopg.errors.CheckViolation):
        run_id = c.execute("select id from runs").fetchall()[0][0]
        c.execute("insert into screen_notes (run_id, body, author) values (%s, 'x', 'analyst')", (run_id,))
