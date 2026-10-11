"""Intake (decisions F2, B5) and the five-business-day screen clock (G4)."""

from datetime import date

import pytest

from sg import clock, pipeline, store


def test_due_is_five_business_days_after_filing():
    assert clock.due(date(2026, 10, 5)) == date(2026, 10, 12)  # Monday -> next Monday
    assert clock.due(date(2026, 10, 9)) == date(2026, 10, 16)  # Friday -> next Friday
    assert clock.due(date(2026, 10, 10)) == date(2026, 10, 16)  # filed on a Saturday


def test_business_days_between():
    assert clock.business_days_between(date(2026, 10, 9), date(2026, 10, 12)) == 1  # over a weekend
    assert clock.business_days_between(date(2026, 10, 12), date(2026, 10, 9)) == -1
    assert clock.business_days_between(date(2026, 10, 12), date(2026, 10, 12)) == 0


def test_clock_status():
    filed, today = "2026-10-05", date(2026, 10, 8)
    assert clock.status(None, None, today) is None
    assert clock.status(filed, None, today) == {
        "filed_on": filed,
        "due": "2026-10-12",
        "done": False,
        "days_left": 2,
        "late": False,
    }
    late = lambda done, today: (clock.status(filed, done, today) or {})["late"]
    assert late(None, date(2026, 10, 13))
    assert not late("2026-10-12", date(2026, 10, 20))  # done on the due date
    assert late("2026-10-13", date(2026, 10, 20))  # a late screen stays late


@pytest.mark.usefixtures("db")
def test_intake_round_trip_partial_updates_and_clearing():
    assert store.intake("f") == dict.fromkeys(store.INTAKE_FIELDS)
    store.save_intake("f", {"referred_by": "A. Adviser", "filed_on": "2026-10-05", "share_class": "Class I"})
    store.save_intake("f", {"owner": " Analyst A "})
    assert store.intake("f") == {
        "referred_by": "A. Adviser",
        "owner": "Analyst A",
        "sponsor_deadline": None,
        "filed_on": "2026-10-05",
        "share_class": "Class I",
    }
    store.save_intake("f", {"share_class": ""})
    assert store.intake("f")["share_class"] is None
    assert set(store.intakes()) == {"f"}


@pytest.mark.usefixtures("db")
def test_intake_refuses_unknown_fields_and_bad_dates():
    with pytest.raises(ValueError, match="unknown intake field status"):
        store.save_intake("f", {"status": "Covered"})  # status moves are the CIO's, never the tool's
    with pytest.raises(ValueError, match="filed_on must be a date"):
        store.save_intake("f", {"filed_on": "10/05/2026"})


def test_only_fee_gates_read_the_share_class():
    fee = {"id": "cost", "extractor": {"rules": "Quote fees.", "fields": [{"name": "m", "recurring": True}]}}
    other = {"id": "ops", "extractor": {"rules": "Quote.", "fields": [{"name": "admin"}]}}
    assert pipeline.for_share_class(fee, "Class I")["extractor"]["rules"] == (
        "Quote fees. The analyst chose share class Class I: screen that class."
    )
    assert pipeline.for_share_class(other, "Class I") is other
    assert pipeline.for_share_class(fee, None) is fee
