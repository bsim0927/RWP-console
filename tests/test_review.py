"""Analyst review: reviewers, gate reviews and manual checks (decisions G1, G2, C3, C4)."""

import psycopg
import pytest

from sg import review, store
from sg.review import ReviewError, effective

pytestmark = pytest.mark.usefixtures("db")

FUND, STAMP = "Acme_-_Fund_I", "20261001T120000"
CHECKS = [{"id": "custody", "q": "Can it be custodied?"}, {"id": "pricing", "q": "Can it be priced?"}]


@pytest.fixture
def run(db):
    gates = [
        {"gate": "operability", "result": "Pass", "review": False, "checks": CHECKS},
        {"gate": "track_record", "result": "Incomplete", "review": True},
    ]
    summary = {"fund": "Acme - Fund I", "run": STAMP, "disposition": "Under review", "gates": {}}
    store.save_run(FUND, summary, gates, "")


def test_the_cio_is_seeded_and_analysts_can_be_added():
    assert review.reviewers() == [{"id": "cio", "name": "CIO", "role": "cio", "active": True}]
    added = review.save_reviewer({"name": "Analyst Two"})
    assert added == {"id": "analyst_two", "name": "Analyst Two", "role": "analyst", "active": True}
    review.save_reviewer({"id": "analyst_two", "name": "Analyst Two", "role": "analyst", "active": False})
    with pytest.raises(ReviewError, match="role must be"):
        review.save_reviewer({"name": "Ex", "role": "boss"})


@pytest.mark.usefixtures("run")
def test_agree_clears_analyst_review_and_keeps_the_pipeline_result():
    out = review.add_review(FUND, STAMP, "track_record", "cio", "agree", "Composite is gross; asked for net.")
    e = out["track_record"]
    assert (e["result"], e["source"], e["reviewed"], e["needs_review"]) == ("Incomplete", "pipeline", True, False)
    assert e["review"]["reviewer"] == "CIO" and e["review"]["reason"] == "Composite is gross; asked for net."


@pytest.mark.usefixtures("run")
def test_an_override_needs_a_result_document_and_page():
    with pytest.raises(ReviewError, match="document and page"):
        review.add_review(FUND, STAMP, "track_record", "cio", "override", "Net record on file", result="Pass")
    with pytest.raises(ReviewError, match="sets the result"):
        review.add_review(FUND, STAMP, "track_record", "cio", "override", "x", result="Maybe", document="d", page=1)
    with pytest.raises(ReviewError, match="one-line reason"):
        review.add_review(FUND, STAMP, "track_record", "cio", "agree", "  ")
    out = review.add_review(
        FUND, STAMP, "track_record", "cio", "override", "Net record in the DDQ", "Pass", "DDQ.pdf", "12"
    )
    e = out["track_record"]
    assert (e["result"], e["source"], e["pipeline_result"]) == ("Pass", "override", "Incomplete")
    assert (e["review"]["document"], e["review"]["page"]) == ("DDQ.pdf", 12)


@pytest.mark.usefixtures("run")
def test_the_newest_review_is_in_force_and_history_is_kept():
    review.add_review(FUND, STAMP, "track_record", "cio", "override", "Net in DDQ", "Pass", "DDQ.pdf", 12)
    out = review.add_review(FUND, STAMP, "track_record", "cio", "agree", "DDQ figure is gross after all")
    e = out["track_record"]
    assert e["result"] == "Incomplete" and [h["verdict"] for h in e["history"]] == ["agree", "override"]


@pytest.mark.usefixtures("run")
def test_a_no_on_a_manual_check_fails_the_gate():
    out = review.for_run(FUND, STAMP)
    assert out["operability"]["pending_checks"] == ["custody", "pricing"]
    review.add_check(FUND, STAMP, "operability", "custody", True, "cio")
    out = review.add_check(FUND, STAMP, "operability", "pricing", False, "cio", "Not in the reporting system")
    e = out["operability"]
    assert (e["result"], e["source"], e["failed_checks"], e["pending_checks"]) == ("Fail", "check", ["pricing"], [])
    with pytest.raises(ReviewError, match="no manual check"):
        review.add_check(FUND, STAMP, "operability", "liquidity", True, "cio")
    with pytest.raises(ReviewError, match="yes or no"):
        review.add_check(FUND, STAMP, "operability", "custody", "yes", "cio")


@pytest.mark.usefixtures("run")
def test_reviews_need_an_active_reviewer_and_a_real_gate():
    review.save_reviewer({"id": "cio", "name": "CIO", "role": "cio", "active": False})
    with pytest.raises(ReviewError, match="active reviewer"):
        review.add_review(FUND, STAMP, "track_record", "cio", "agree", "ok")
    with pytest.raises(ReviewError, match="active reviewer"):
        review.add_review(FUND, STAMP, "track_record", "nobody", "agree", "ok")
    review.save_reviewer({"id": "cio", "name": "CIO", "role": "cio"})
    with pytest.raises(ReviewError, match="no gate"):
        review.add_review(FUND, STAMP, "key_person", "cio", "agree", "ok")


@pytest.mark.usefixtures("run")
def test_latest_by_fund_reads_each_funds_newest_run():
    review.add_check(FUND, STAMP, "operability", "pricing", False, "cio")
    latest = review.latest_by_fund()
    assert latest[FUND]["operability"]["result"] == "Fail"
    assert latest[FUND]["track_record"]["needs_review"] is True


def test_an_override_without_its_source_is_refused_by_the_database_too(db, run):
    with psycopg.connect(db) as c, pytest.raises(psycopg.errors.CheckViolation):
        run_id = c.execute("select id from runs").fetchall()[0][0]
        c.execute(
            "insert into gate_reviews (run_id, gate_id, reviewer_id, verdict, result, reason)"
            " values (%s, 'track_record', 'cio', 'override', 'Pass', 'x')",
            (run_id,),
        )


def test_effective_without_a_review_is_the_pipeline_result():
    e = effective({"result": "Pass", "review": True, "checks": CHECKS})
    assert (e["result"], e["needs_review"], e["pending_checks"]) == ("Pass", True, ["custody", "pricing"])
