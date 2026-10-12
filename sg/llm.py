"""Minimal Claude Messages API call with forced tool use, via urllib (no SDK needed)."""

import contextvars
import json
import os
import time
import urllib.error
import urllib.request
import uuid

from . import store
from .env import load_env

# Call tracing. The pipeline sets CTX (fund, gate, step) and TRACE (a list) per gate; every model call
# appends one record there and to the model_calls table, so failed runs still leave a trail.
CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("sg_ctx", default={})  # noqa: B039  read-only, replaced via set()
TRACE: contextvars.ContextVar[list | None] = contextvars.ContextVar("sg_trace", default=None)


def record(provider, model, t0, *, usage=None, ok=True, error=None, output=None, input_chars=0, attempts=1):
    usage = usage or {}
    rec = {
        "id": uuid.uuid4().hex[:12],
        "ts": round(t0, 3),
        **CTX.get(),
        "provider": provider,
        "model": model,
        "seconds": round(time.time() - t0, 3),
        "ok": ok,
        "error": error,
        "attempts": attempts,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "input_chars": input_chars,
        "output": None if output is None else json.dumps(output)[:1500],
    }
    trace = TRACE.get()
    if trace is not None:
        trace.append(rec)
    store.record_call(rec)
    return rec


load_env()


# Output ceiling per call. A fee gate that quotes every layer wherever it appears can run past 4k tokens;
# 16k is the documented ceiling for a non-streaming request. SG_CLAUDE_MAX_TOKENS overrides it.
MAX_TOKENS = 16000


def call_claude_tool(system, user, tool_name, schema):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    body = {
        "model": os.environ.get("SG_CLAUDE_MODEL", "claude-sonnet-5-5"),
        "max_tokens": int(os.environ.get("SG_CLAUDE_MAX_TOKENS", MAX_TOKENS)),
        "system": system + f" Respond only by calling the {tool_name} tool.",
        "messages": [{"role": "user", "content": user}],
        "tools": [{"name": tool_name, "description": "Return the result.", "input_schema": schema}],
        "tool_choice": {"type": "auto"},
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        json.dumps(body).encode(),
        {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    t0, chars = time.time(), len(body["system"]) + len(user)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310  fixed https URL
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        err = f"Anthropic API HTTP {e.code}: {e.read().decode()[:500]}"
        record("anthropic", body["model"], t0, ok=False, error=err, input_chars=chars)
        raise RuntimeError(err) from None
    except (urllib.error.URLError, TimeoutError) as e:
        record("anthropic", body["model"], t0, ok=False, error=str(e), input_chars=chars)
        raise
    model = resp.get("model", body["model"])
    # A cut-off or declined response still arrives as HTTP 200, so check why the model stopped before
    # reading its tool call: a truncated call is partial or empty, never a result.
    stop = resp.get("stop_reason")
    if stop in ("max_tokens", "refusal"):
        why = (
            f"response cut off at max_tokens ({body['max_tokens']}); raise SG_CLAUDE_MAX_TOKENS"
            if stop == "max_tokens"
            else f"model declined: {(resp.get('stop_details') or {}).get('category') or 'no category'}"
        )
        record("anthropic", model, t0, usage=resp.get("usage"), ok=False, error=why, input_chars=chars)
        raise RuntimeError(f"{tool_name}: {why}")
    for block in resp["content"]:
        if block["type"] == "tool_use":
            missing = [k for k in schema.get("required", []) if k not in block["input"]]
            if missing:
                why = f"tool call is missing {', '.join(missing)}"
                record("anthropic", model, t0, usage=resp.get("usage"), ok=False, error=why, input_chars=chars)
                raise RuntimeError(f"{tool_name}: {why}")
            record(
                "anthropic",
                model,
                t0,
                usage=resp.get("usage"),
                output=block["input"],
                input_chars=chars,
            )
            return block["input"]
    record(
        "anthropic",
        model,
        t0,
        usage=resp.get("usage"),
        ok=False,
        error="no tool_use block in response",
        input_chars=chars,
    )
    raise RuntimeError("no tool_use block in response")
