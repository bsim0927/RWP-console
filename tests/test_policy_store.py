"""Policy editing: validation, append-only versions, restore, and agreement with the pipeline."""

import pytest
import yaml

from sg import pipeline, policy_store, store
from sg.gate_store import GateError

OK = """# How gate results combine.
rules:
  - when: any_fail
    disposition: Reviewed and not covered (draft)
  - when: otherwise
    disposition: Coverable, subject to conditions
"""


def errors(text):
    return policy_store.validate(yaml.safe_load(text))


def test_conditions_match_what_reduce_gates_evaluates():
    _, flags = pipeline.reduce_gates({"rules": []}, [])
    assert set(policy_store.CONDITIONS) == set(flags) | {"otherwise"}


def test_a_good_policy_has_no_errors_or_warnings():
    assert errors(OK) == ([], [])


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[]", "YAML mapping"),
        ("rules: []", "at least one rule"),
        ("rules: [{when: any_bad, disposition: X}]", "when must be one of"),
        ("rules: [{when: otherwise, disposition: ''}]", "needs a disposition"),
        ("rules: [oops]", "must have a when and a disposition"),
    ],
)
def test_errors(text, message):
    err, _ = errors(text)
    assert any(message in e for e in err), err


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "rules: [{when: otherwise, disposition: Under review}, {when: any_fail, disposition: Under review}]",
            "never run",
        ),
        (
            "rules: [{when: any_fail, disposition: Under review}, {when: any_fail, disposition: Under review}]",
            "already appears above",
        ),
        ("rules: [{when: any_fail, disposition: Under review}]", "no otherwise rule"),
        ("rules: [{when: otherwise, disposition: Approved}]", "colours dispositions"),
    ],
)
def test_warnings(text, message):
    err, warn = errors(text)
    assert err == []
    assert any(message in w for w in warn), warn


@pytest.mark.usefixtures("db")
def test_save_is_append_only_and_the_newest_version_is_in_force():
    seeded = store.policy()
    out = policy_store.save(OK)
    assert out["id"] > seeded["id"]
    assert store.policy()["yaml"] == OK  # comments kept, text exactly as written
    assert policy_store.save(OK)["unchanged"]
    hist = policy_store.history()
    assert [h["id"] for h in hist] == [out["id"], seeded["id"]]
    assert [h["current"] for h in hist] == [True, False]


@pytest.mark.usefixtures("db")
def test_restore_brings_an_old_version_back_as_a_new_one():
    seeded = store.policy()
    policy_store.save(OK)
    out = policy_store.restore(seeded["id"])
    assert out["id"] > seeded["id"]
    assert store.policy()["yaml"] == seeded["yaml"]
    assert len(policy_store.history()) == 3


@pytest.mark.usefixtures("db")
def test_invalid_policies_and_unknown_versions_are_refused():
    before = store.policy()
    with pytest.raises(GateError, match="when must be one of"):
        policy_store.save("rules: [{when: sometimes, disposition: X}]")
    with pytest.raises(GateError, match="does not parse"):
        policy_store.save("rules: [unclosed")
    with pytest.raises(GateError, match="unknown policy version"):
        policy_store.restore(999999)
    assert store.policy() == before
