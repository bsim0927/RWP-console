"""call_claude_tool: a cut-off, declined or incomplete answer fails loudly and is logged as failed."""

import io
import json

import pytest

from sg import llm

SCHEMA = {"type": "object", "properties": {"facts": {"type": "array"}}, "required": ["facts"]}


@pytest.fixture
def api(monkeypatch):
    """Answer the next request with `reply`; collect what llm.record logs."""
    logged: list[dict] = []
    reply: dict = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(llm.store, "record_call", logged.append)
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout: io.BytesIO(json.dumps(reply).encode()))
    return reply, logged


def answer(stop, tool_input, **extra):
    return {
        "model": "m",
        "stop_reason": stop,
        "usage": {"output_tokens": 9},
        **extra,
        "content": [{"type": "tool_use", "name": "record_facts", "input": tool_input}],
    }


def test_a_complete_tool_call_is_returned_and_logged(api):
    reply, logged = api
    reply.update(answer("tool_use", {"facts": [1]}))
    assert llm.call_claude_tool("sys", "user", "record_facts", SCHEMA) == {"facts": [1]}
    assert logged[-1]["ok"] is True


def test_a_response_cut_off_at_max_tokens_is_a_logged_failure(api):
    reply, logged = api
    reply.update(answer("max_tokens", {}))
    with pytest.raises(RuntimeError, match="record_facts: response cut off at max_tokens \\(16000\\)"):
        llm.call_claude_tool("sys", "user", "record_facts", SCHEMA)
    assert logged[-1]["ok"] is False and "max_tokens" in logged[-1]["error"]


def test_a_refusal_names_its_category(api):
    reply, logged = api
    reply.update(answer("refusal", {}, stop_details={"type": "refusal", "category": "cyber"}))
    with pytest.raises(RuntimeError, match="model declined: cyber"):
        llm.call_claude_tool("sys", "user", "record_facts", SCHEMA)
    assert logged[-1]["ok"] is False


def test_a_tool_call_missing_a_required_field_is_a_logged_failure(api):
    reply, logged = api
    reply.update(answer("tool_use", {"notes": "x"}))
    with pytest.raises(RuntimeError, match="record_facts: tool call is missing facts"):
        llm.call_claude_tool("sys", "user", "record_facts", SCHEMA)
    assert logged[-1]["ok"] is False


def test_the_output_ceiling_can_be_raised(api, monkeypatch):
    reply, _ = api
    reply.update(answer("max_tokens", {}))
    monkeypatch.setenv("SG_CLAUDE_MAX_TOKENS", "32000")
    with pytest.raises(RuntimeError, match="\\(32000\\)"):
        llm.call_claude_tool("sys", "user", "record_facts", SCHEMA)
