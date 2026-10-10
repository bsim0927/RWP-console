"""A whole screening run against the database, with stub extractor and judge (no network)."""

import json
import time

import psycopg
import pytest

from sg import extractors, judges, llm, pipeline, store

pytestmark = pytest.mark.usefixtures("db")

PAGE = "Summary of Terms. The minimum investment is $250,000. Accredited investors may subscribe."


@pytest.fixture
def room(tmp_path):
    folder = tmp_path / "Acme Partners - Fund I"
    (folder / "_index").mkdir(parents=True)
    rec = {"file": "Acme Fund I - Term Sheet.pdf", "page": 1, "chars": len(PAGE), "text": PAGE}
    (folder / "_index" / "pages.jsonl").write_text(json.dumps(rec) + "\n")
    return folder


@pytest.fixture
def stubs(monkeypatch):
    def extractor(gate, room, pages):
        llm.record("stub", "stub-extractor", time.time(), usage={"input_tokens": 5, "output_tokens": 1})
        return [
            {
                "field": gate["extractor"]["fields"][0]["name"],
                "value": "x",
                "file": "Acme Fund I - Term Sheet.pdf",
                "page": 1,
                "quote": "The minimum investment is $250,000.",
            }
        ]

    def judge(gate, brief, questions):
        return {
            q["id"]: (
                {"true": 0.9, "false": 0.1} if q["type"] == "bool" else {o: 1 / len(q["options"]) for o in q["options"]}
            )
            for q in questions
        }

    monkeypatch.setitem(extractors.EXTRACTORS, "stub", extractor)
    monkeypatch.setitem(judges.JUDGES, "stub", judge)


@pytest.mark.usefixtures("stubs")
def test_a_screen_run_is_saved_with_its_gate_definitions_policy_and_calls(room, db):
    ref, summary, results = pipeline.run(room, "stub", "stub")
    fund_id = "Acme_Partners_-_Fund_I"
    assert ref == f"{fund_id}/{summary['run']}"
    saved = store.run(fund_id, summary["run"])
    assert saved["summary"]["disposition"] == summary["disposition"]
    assert [g["gate"] for g in saved["gates"]] == [g["id"] for g in pipeline.load_gates()]
    assert "# Screen run: Acme Partners - Fund I" in saved["markdown"]
    assert store.catalog(fund_id) is not None  # the run built and saved the room's catalog

    with psycopg.connect(db) as c:
        snap: dict[str, str] = dict(c.execute("select gate_id, gate_yaml from run_gates").fetchall())
        (policy_id,) = c.execute("select policy_id from runs").fetchall()[0]
    assert snap["operability"].startswith("id: operability")
    assert policy_id == store.policy()["id"]
    # One stub extractor call per automated gate, linked from the gate records.
    linked = {c["id"] for g in saved["gates"] for c in g.get("calls") or []}
    assert linked and linked <= {c["id"] for c in store.calls()}
