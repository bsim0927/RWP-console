"""The disposition after review, and its confirmation and CIO sign-off (decision F5)."""

import pytest

from sg import disposition, review, store
from sg.review import ReviewError

FUND, STAMP = "Acme_-_Fund_I", "20261001T120000"
CHECKS = [{"id": "custody", "q": "Can it be custodied?"}]


def save(*gates):
    summary = {"fund": "Acme - Fund I", "run": STAMP, "disposition": "Under review", "gates": {}}
    store.save_run(FUND, summary, list(gates), "")


@pytest.fixture
def analyst(db):
    review.save_reviewer({"id": "analyst_a", "name": "Analyst A", "role": "analyst"})


def test_a_draft_names_what_blocks_confirmation(db):
    save(
        {"gate": "operability", "result": "Pass", "review": False, "checks": CHECKS},
        {"gate": "track_record", "result": "Pass", "review": True},
    )
    d = disposition.for_run(FUND, STAMP)
    assert d["state"] == "draft" and d["disposition"].startswith("Under review (analyst")
    assert d["blockers"] == ["review track record", "answer the custody (operability) check"]
    with pytest.raises(ReviewError, match="before confirming, review track record"):
        disposition.confirm(FUND, STAMP, "cio")


def test_once_reviewed_the_disposition_follows_the_reviewed_results(db):
    save(
        {"gate": "operability", "result": "Pass", "review": False, "checks": CHECKS},
        {"gate": "track_record", "result": "Pass", "review": True},
    )
    review.add_check(FUND, STAMP, "operability", "custody", True, "cio")
    review.add_review(FUND, STAMP, "track_record", "cio", "agree", "Net fund-level record")
    d = disposition.confirm(FUND, STAMP, "cio", "All gates met")
    assert d["disposition"] == "Coverable, subject to conditions"
    assert (
        d["state"] == "confirmed"
        and d["confirmed"]["reviewer"] == "CIO"
        and d["confirmed"]["reason"] == "All gates met"
    )
    with pytest.raises(ReviewError, match="already confirmed"):
        disposition.confirm(FUND, STAMP, "cio")


@pytest.mark.usefixtures("analyst")
def test_not_covered_needs_the_cios_sign_off():
    save({"gate": "investor_eligibility", "result": "Fail", "review": False})
    d = disposition.confirm(FUND, STAMP, "analyst_a")
    assert d["needs_signoff"] and d["state"] == "awaiting_signoff"
    assert disposition.decided_on_by_fund() == {}  # not final until the CIO signs off
    with pytest.raises(ReviewError, match="signed off by the CIO"):
        disposition.confirm(FUND, STAMP, "analyst_a")
    d = disposition.confirm(FUND, STAMP, "cio", "Institutions only")
    assert d["state"] == "signed_off" and d["signed_off"]["reviewer"] == "CIO"
    assert list(disposition.decided_on_by_fund()) == [FUND]


def test_a_cio_confirming_not_covered_signs_it_off_at_once(db):
    save({"gate": "investor_eligibility", "result": "Fail", "review": False})
    assert disposition.confirm(FUND, STAMP, "cio")["state"] == "signed_off"


def test_a_review_that_changes_the_disposition_reopens_the_draft(db):
    save({"gate": "investor_eligibility", "result": "Pass", "review": False})
    assert disposition.confirm(FUND, STAMP, "cio")["state"] == "confirmed"
    review.add_review(FUND, STAMP, "investor_eligibility", "cio", "override", "Institutions only", "Fail", "PPM.pdf", 3)
    d = disposition.for_run(FUND, STAMP)
    assert d["disposition"].startswith("Reviewed and not covered") and d["state"] == "draft"
    assert [h["disposition"] for h in d["history"]] == ["Coverable, subject to conditions"]


def test_latest_by_fund_carries_the_reviewed_gates_and_the_decision(db):
    save({"gate": "operability", "result": "Pass", "review": False, "checks": CHECKS})
    review.add_check(FUND, STAMP, "operability", "custody", False, "cio")
    latest = disposition.latest_by_fund()[FUND]
    assert latest["run"] == STAMP
    assert latest["gates"]["operability"]["result"] == "Fail"
    assert latest["decision"]["disposition"].startswith("Reviewed and not covered")


def test_decide_with_no_gates_is_the_policy_fallthrough(db):
    d = disposition.decide({}, {"rules": [{"when": "otherwise", "disposition": "Coverable"}]})
    assert (d["disposition"], d["state"], d["blockers"]) == ("Coverable", "draft", [])
