"""A whole screening run against the database, with stub extractor and judge (no network)."""

import json
import time

import psycopg
import pytest

from sg import consistency, extractors, judges, llm, pipeline, store
from sg.dataroom import DataRoom

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


@pytest.mark.usefixtures("stubs")
def test_the_chosen_share_class_reaches_the_fee_gate_and_the_run_record(room, monkeypatch):
    seen = {}
    stub = extractors.EXTRACTORS["stub"]

    def spy(gate, room, pages):
        seen[gate["id"]] = gate["extractor"].get("rules", "")
        return stub(gate, room, pages)

    monkeypatch.setitem(extractors.EXTRACTORS, "stub", spy)
    store.save_intake("Acme_Partners_-_Fund_I", {"share_class": "Class I"})
    _, summary, _ = pipeline.run(room, "stub", "stub")
    assert seen["total_annual_cost"].endswith("The analyst chose share class Class I: screen that class.")
    assert "Class I" not in seen["operability"]
    assert summary["share_class"] == "Class I"
    assert "Share class screened: Class I." in store.run("Acme_Partners_-_Fund_I", summary["run"])["markdown"]


@pytest.mark.usefixtures("stubs")
def test_contradictions_are_found_and_a_failed_comparison_does_not_stop_the_screen(tmp_path, monkeypatch):
    folder = tmp_path / "Acme Partners - Fund I"
    (folder / "_index").mkdir(parents=True)
    terms, deck = "Acme Fund I - Term Sheet.pdf", "Acme Fund I - Deck.pdf"
    said = {
        terms: ("Minimum: $250,000", "Administrator: Harbor Fund Services"),
        deck: ("Minimum: $100,000", "Administrator: Monroe Admin, an affiliate"),
    }
    (folder / "_index" / "pages.jsonl").write_text(
        "".join(json.dumps({"file": f, "page": 1, "chars": 80, "text": ". ".join(t)}) + "\n" for f, t in said.items())
    )

    def two_documents(gate, room, pages):
        if gate["id"] != "operability":
            return []
        return [
            {"field": field, "value": quote.split(": ")[1], "file": file, "page": 1, "quote": quote}
            for file, quotes in said.items()
            for field, quote in zip(("custody", "administrator"), quotes, strict=True)
        ]

    def wording(gate_id, groups, kind_of):
        raise RuntimeError("model unavailable")

    monkeypatch.setitem(extractors.EXTRACTORS, "stub", two_documents)
    monkeypatch.setitem(consistency.WORDING, "stub", wording)
    _, summary, results = pipeline.run(folder, "stub", "stub")
    ops = next(r for r in results if r["gate"] == "operability")
    assert [(c["field"], c["summary"]) for c in ops["contradictions"]] == [
        ("custody", "Documents give $100,000, $250,000")
    ]
    assert ops["compare_error"] == "RuntimeError: model unavailable"  # the administrator wording was not compared
    assert summary["marketing_contradictions"] == [] and summary["marketing_check_error"] is None


def test_check_marketing_reports_a_failed_call_without_raising(room, monkeypatch):
    def boom(room, catalog):
        raise RuntimeError("model unavailable")

    monkeypatch.setitem(consistency.MARKETING_CHECK, "stub", boom)
    found, err = pipeline.check_marketing(DataRoom(room), [], "stub", pipeline.Tracker())
    assert found == [] and err == "RuntimeError: model unavailable"
