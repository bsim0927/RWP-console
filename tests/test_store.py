"""The Postgres store: runs, model calls, catalogs, policy, gates, and the security posture of the schema."""

import json
import time

import psycopg
import pytest
import yaml

from sg import gate_store, store

pytestmark = pytest.mark.usefixtures("db")


def summary(fund="Acme - Fund I", stamp="20261001T120000", disposition="Coverable, subject to conditions"):
    return {
        "fund": fund,
        "run": stamp,
        "extractor": "claude",
        "judge": "jev",
        "disposition": disposition,
        "flags": {"any_fail": False, "any_incomplete": False, "any_review": False},
        "seconds": 1.5,
        # Deliberately not alphabetical: the console shows gates in pipeline order.
        "gates": {"track_record": {"result": "Pass"}, "investor_eligibility": {"result": "Pass"}},
    }


def gate_record(gate, result="Pass"):
    return {
        "gate": gate,
        "gate_version": 2,
        "result": result,
        "review": False,
        "min_confidence": 0.91,
        "answers": {"sufficient": {"true": 0.9, "false": 0.1}},
        "brief": {"facts": [], "not_found": []},
    }


# ---------- runs ----------


def test_run_round_trips_and_keeps_key_order():
    results = [gate_record("track_record"), gate_record("investor_eligibility", "Fail")]
    store.save_run("Acme_-_Fund_I", summary(), results, "# report", {"track_record": "id: track_record\n"})
    got = store.run("Acme_-_Fund_I", "20261001T120000")
    assert got["summary"] == summary()
    assert list(got["summary"]["gates"]) == ["track_record", "investor_eligibility"]  # json, not jsonb
    assert [g["gate"] for g in got["gates"]] == ["track_record", "investor_eligibility"]
    assert list(got["gates"][0]["answers"]["sufficient"]) == ["true", "false"]
    assert got["markdown"] == "# report"


def test_unknown_run_is_none():
    assert store.run("nobody", "20260101T000000") is None


def test_a_second_run_with_the_same_stamp_is_refused_unless_replacing():
    store.save_run("f", summary(), [gate_record("operability")], "")
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.save_run("f", summary(), [gate_record("operability")], "")
    store.save_run("f", summary(disposition="Under review"), [gate_record("operability", "Fail")], "", replace=True)
    got = store.run("f", "20261001T120000")
    assert got["summary"]["disposition"] == "Under review"
    assert [g["result"] for g in got["gates"]] == ["Fail"]  # the old gate rows were replaced, not appended


def test_listing_runs():
    for fid, stamp in [("a", "20261001T100000"), ("a", "20261003T100000"), ("b", "20261002T100000")]:
        store.save_run(fid, summary(fund=fid, stamp=stamp), [], "")
    assert store.stamps_by_fund() == {"a": ["20261003T100000", "20261001T100000"], "b": ["20261002T100000"]}
    assert store.run_stamps("a") == ["20261003T100000", "20261001T100000"]
    assert {k: v["run"] for k, v in store.latest_summaries().items()} == {
        "a": "20261003T100000",
        "b": "20261002T100000",
    }
    assert [s["run"] for s in store.summaries()] == ["20261003T100000", "20261002T100000", "20261001T100000"]
    assert [s["run"] for s in store.summaries("a", newest_first=False)] == ["20261001T100000", "20261003T100000"]
    assert all("fund_id" in s for s in store.summaries())
    assert [r["fund_id"] for r in store.runs_with_gates()] == ["a", "a", "b"]


# ---------- model calls ----------


def test_model_calls_are_recorded_once_with_epoch_timestamps():
    t = time.time()
    rec = {
        "id": "abc123def456",
        "ts": t,
        "fund": "Acme",
        "gate": "operability",
        "step": "judge",
        "provider": "anthropic",
        "model": "m",
        "seconds": 1.25,
        "ok": True,
        "input_tokens": 10,
    }
    store.record_call(rec)
    store.record_call(rec)
    [got] = store.calls()
    assert got["id"] == "abc123def456"
    assert got["ts"] == pytest.approx(t, abs=1e-3)
    assert got["seconds"] == 1.25 and isinstance(got["seconds"], float)
    assert got["output_tokens"] is None  # missing keys are stored as null


# ---------- catalogs ----------


def test_catalog_save_replaces_and_keeps_document_order():
    assert store.catalog("room") is None
    store.save_catalog("room", "Room", [{"doc_id": "b"}, {"doc_id": "a"}], {"files": 2})
    store.save_catalog("room", "Room", [{"doc_id": "z", "structure": {}}, {"doc_id": "y"}], {"files": 2, "v": 2})
    summ, docs = store.catalog("room")
    assert summ == {"files": 2, "v": 2}
    assert [d["doc_id"] for d in docs] == ["z", "y"]
    assert store.catalog_summaries() == {"room": {"files": 2, "v": 2}}


# ---------- policy ----------


def test_the_newest_policy_is_in_force():
    seeded = store.policy()
    assert yaml.safe_load(seeded["yaml"])["rules"][-1]["when"] == "otherwise"
    new_id = store.save_policy("rules: []\n")
    assert store.policy() == {"id": new_id, "yaml": "rules: []\n"}


# ---------- gates ----------

NEW_GATE = """id: custody_check
version: 1
extractor:
  keywords: [custodian]
  fields:
    - { name: custodian }
questions:
  - { id: sufficient, type: bool, q: "Is a custodian named?" }
derive:
  - { if: "sufficient < 0.7", then: Incomplete }
  - { then: Pass }
"""


def test_seeded_gates_are_the_five_shipped_ones_in_order():
    assert [g["file"] for g in gate_store.current()] == [
        "1_investor_eligibility.yaml",
        "2_total_annual_cost.yaml",
        "3_operability.yaml",
        "4_track_record.yaml",
        "5_disclosure_history.yaml",
    ]
    assert gate_store.current()[0]["text"].startswith("id: investor_eligibility")


def test_gate_lifecycle_create_edit_delete_restore():
    assert gate_store.create({"text": NEW_GATE})["file"] == "6_custody_check.yaml"
    edited = NEW_GATE.replace("Is a custodian named?", "Is an independent custodian named?")
    out = gate_store.update("6_custody_check.yaml", {"text": edited})
    assert out["version"] == 2  # content changed, version bumped for the analyst
    assert "version: 2" in gate_store.current()[-1]["text"]
    assert gate_store.update("6_custody_check.yaml", {"text": gate_store.current()[-1]["text"]})["unchanged"]

    gate_store.remove("6_custody_check.yaml")
    assert "custody_check" not in [g["id"] for g in gate_store.current()]
    hist = gate_store.history("6_custody_check.yaml")
    assert [h["reason"] for h in hist] == ["deleted", "edit"]
    assert hist[1]["text"] == NEW_GATE  # the pre-edit text, comments and all

    restored = gate_store.restore(hist[0]["file"])
    assert restored["file"].endswith("_custody_check.yaml")


def test_restoring_over_a_live_gate_is_a_new_version_never_a_step_back():
    gate_store.create({"text": NEW_GATE})
    gate_store.update("6_custody_check.yaml", {"text": NEW_GATE.replace("custodian]", "custodian, custody]")})
    old = gate_store.history("6_custody_check.yaml")[0]
    out = gate_store.restore(old["file"])
    assert out["version"] == 3


def test_reorder_and_unknown_files():
    files = [g["file"] for g in gate_store.current()]
    out = gate_store.reorder(files[::-1])
    assert out["order"][0] == "1_disclosure_history.yaml"
    assert [g["id"] for g in gate_store.current()][0] == "disclosure_history"
    with pytest.raises(gate_store.GateError):
        gate_store.reorder(files[:2])
    with pytest.raises(gate_store.GateError):
        gate_store.update("9_nope.yaml", {"text": NEW_GATE})
    with pytest.raises(gate_store.GateError):
        gate_store.restore("not-a-number")


def test_duplicate_gate_ids_are_rejected():
    dup = NEW_GATE.replace("id: custody_check", "id: operability")
    with pytest.raises(gate_store.GateError, match="already used by 3_operability.yaml"):
        gate_store.create({"text": dup})


# ---------- security ----------


def test_every_table_has_row_level_security(db):
    """RLS on with no policies keeps every table closed to Supabase's public Data API."""
    with psycopg.connect(db) as c:
        rows = c.execute(
            """select c.relname, c.relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
               where n.nspname = 'public' and c.relkind = 'r'"""
        ).fetchall()
    assert rows, "no tables found"
    assert [name for name, rls in rows if not rls] == []


def test_payload_columns_are_json_not_jsonb(db):
    """jsonb reorders object keys; the console relies on the order the pipeline wrote."""
    with psycopg.connect(db) as c:
        rows = c.execute(
            """select table_name || '.' || column_name, data_type from information_schema.columns
               where table_schema = 'public' and data_type in ('json', 'jsonb')"""
        ).fetchall()
    assert {t for _, t in rows} == {"json"}, json.dumps(rows)
