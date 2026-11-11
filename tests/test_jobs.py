"""Screen jobs and the event log in the database, and a screen run through the WSGI app end to end."""

import io
import json
import time
from wsgiref.util import setup_testing_defaults

import psycopg
import pytest

import server
from sg import extractors, jobs, judges, llm

pytestmark = pytest.mark.usefixtures("db")


def test_a_job_is_queued_claimed_once_and_finished():
    jid = jobs.create("f", "Fund", "claude", "jev", ["operability"])
    assert jobs.get(jid)["status"] == "running"  # a queued job shows as starting
    assert jobs.claim(jid)["fund_id"] == "f"
    assert jobs.claim(jid) is None  # a second run of the same job is refused
    jobs.progress(jid, [{"gate": "operability", "step": "retrieve", "start": 0, "end": None, "detail": ""}])
    assert jobs.get(jid)["steps"][0]["step"] == "retrieve"
    jobs.finish(jid, [], run_stamp="20261012T100000")
    j = jobs.get(jid)
    assert (j["status"], j["run"], j["error"]) == ("done", "20261012T100000", None)
    assert j["seconds"] is not None and jobs.recent()[0]["id"] == jid
    assert jobs.get("nope") is None


def test_a_job_that_stops_reporting_is_reported_as_cut_off(db):
    jid = jobs.create("f", "Fund", "claude", "jev", [])
    jobs.claim(jid)
    with psycopg.connect(db) as c:
        c.execute("update screen_jobs set updated_at = now() - interval '20 minutes' where id = %s", (jid,))
    j = jobs.get(jid)
    assert j["status"] == "error" and "stopped without finishing" in j["error"]


def test_events_come_back_oldest_first_with_their_extras():
    jobs.log("job", "first", job="a")
    jobs.log("auth", "a sign-in failed", "warn")
    evs = jobs.events()
    assert [(e["kind"], e["level"], e["msg"]) for e in evs] == [
        ("job", "info", "first"),
        ("auth", "warn", "a sign-in failed"),
    ]
    assert evs[0]["job"] == "a" and evs[0]["t"] <= time.time()


def post(path, body=None):
    raw = json.dumps(body or {}).encode()
    environ = {
        "REQUEST_METHOD": "POST",
        "SCRIPT_NAME": "",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "wsgi.input": io.BytesIO(raw),
    }
    setup_testing_defaults(environ)
    got: dict[str, str] = {}
    out = b"".join(server.app(environ, lambda status, headers: got.update(status=status)))
    return got["status"], json.loads(out)


def test_a_screen_runs_inside_its_own_request_and_the_job_records_it(tmp_path, monkeypatch):
    room = tmp_path / "Acme Partners - Fund I"
    (room / "_index").mkdir(parents=True)
    page = "Summary of Terms. Accredited investors may subscribe."
    (room / "_index" / "pages.jsonl").write_text(
        json.dumps({"file": "Terms.pdf", "page": 1, "chars": 9, "text": page}) + "\n"
    )
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)
    monkeypatch.delenv("SITE_PASSWORD", raising=False)

    def extractor(gate, room, pages):
        llm.record("stub", "stub", time.time())
        return []

    def judge(gate, brief, questions):
        return {
            q["id"]: (
                {"true": 0.9, "false": 0.1} if q["type"] == "bool" else {o: 1 / len(q["options"]) for o in q["options"]}
            )
            for q in questions
        }

    monkeypatch.setitem(extractors.EXTRACTORS, "stub", extractor)
    monkeypatch.setitem(judges.JUDGES, "stub", judge)

    status, out = post("/api/screen", {"fund": "Acme_Partners_-_Fund_I", "extractor": "stub", "judge": "stub"})
    assert status == "200 OK"
    jid = out["job"]
    status, out = post(f"/api/screen/{jid}/run")
    assert status == "200 OK" and out["status"] == "done"
    j = jobs.get(jid)
    assert j["status"] == "done" and j["run"] == out["run"]
    assert {e["gate"] for e in j["steps"]} >= {"catalog", "operability"} and all(
        e["end"] is not None for e in j["steps"]
    )
    assert post(f"/api/screen/{jid}/run")[0] == "409 Conflict"
    assert any(e["msg"].startswith("screen finished: Acme Partners - Fund I") for e in jobs.events())
