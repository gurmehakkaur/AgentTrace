"""OpenTelemetry in (P1) and a verdict from the caller's own check (P2). Offline, against the in-memory store."""

import asyncio
import gzip
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from agenttrace_sdk import ListSink, submit_verdict

TRACE = "5b8efff798038103d269b633813fc60c"
PLANTED_KEY = "sk-ant-api03-PLANTEDsecret0123456789_abcDEF"
T0 = 1_760_000_000 * 10**9  # an instant, in nanoseconds


def attr(key, value):
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}  # OTLP JSON sends int64 as a string
    return {"key": key, "value": {"stringValue": value}}


def span(span_id, name, op=None, *, parent=None, at=0, ms=1000, trace=TRACE, **attrs):
    attributes = ([attr("gen_ai.operation.name", op)] if op else []) + [attr(k.replace("__", "."), v) for k, v in attrs.items()]
    return {
        "traceId": trace.upper(), "spanId": span_id, "parentSpanId": parent or "", "name": name, "kind": 1,
        "startTimeUnixNano": str(T0 + at * 10**9), "endTimeUnixNano": str(T0 + at * 10**9 + ms * 10**6), "attributes": attributes,
    }


def body(*spans, service="renewal-bot"):
    return {"resourceSpans": [{"resource": {"attributes": [attr("service.name", service)]}, "scopeSpans": [{"scope": {"name": "x"}, "spans": list(spans)}]}]}


def two_agents():
    """A run from a harness we do not control: a planner agent that asks the model, then a writer that searches, then asks."""
    return body(
        span("a0000001", "invoke_agent planner", "invoke_agent", at=0, ms=3000, gen_ai__agent__name="planner"),
        span("b0000001", "chat claude", "chat", parent="a0000001", at=0, ms=2000, gen_ai__request__model="claude-haiku-5-5",
             gen_ai__usage__input_tokens=120, gen_ai__usage__output_tokens=30,
             gen_ai__input__messages='[{"role": "user", "content": "Brief for acme"}]',
             gen_ai__output__messages='[{"role": "assistant", "content": "Filter open tickets"}]'),
        span("a0000002", "invoke_agent writer", "invoke_agent", at=4, ms=5000, gen_ai__agent__name="writer"),
        span("b0000002", "execute_tool search", "execute_tool", parent="a0000002", at=4, ms=500, gen_ai__tool__name="search",
             gen_ai__tool__call__arguments='{"q": "open tickets"}', gen_ai__tool__call__result="[]"),
        span("b0000003", "chat claude", "chat", parent="a0000002", at=5, ms=3000, gen_ai__request__model="claude-haiku-5-5",
             gen_ai__output__messages="You have 0 open tickets."),
    )


@pytest.fixture
def key(store, login):
    login("ws-a", role="admin")
    with TestClient(app) as client:
        yield client.post("/v1/keys").json()["key"]


def send(payload, key, **kw):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **kw.pop("headers", {})}
    data = kw.pop("content", None)
    with TestClient(app) as client:
        return client.post("/v1/traces", content=data if data is not None else json.dumps(payload), headers=headers, **kw)


def read_run(trace=TRACE):
    with TestClient(app) as client:
        return client.get(f"/v1/runs/{trace}")


# --- P1: a trace becomes a run ---------------------------------------------------------------

def test_a_trace_from_another_harness_shows_up_as_a_run_with_its_agents_in_order(key, store):
    resp = send(two_agents(), key)
    assert resp.status_code == 200 and resp.json() == {}  # full success: partialSuccess left unset
    run = read_run().json()
    assert run["workflow"] == "renewal-bot" and run["forkable"] is False  # view only: nothing here can re-run it
    assert [(s["idx"], s["node_run_idx"], s["agent"], s["kind"]) for s in run["steps"]] == [
        (1, 1, "planner", "llm"), (2, 2, "writer", "tool"), (3, 2, "writer", "llm"),
    ]
    first, tool, last = run["steps"]
    assert first["model"] == "claude-haiku-5-5" and (first["tokens_in"], first["tokens_out"], first["latency_ms"]) == (120, 30, 2000)
    assert first["input"] == {"messages": [{"role": "user", "content": "Brief for acme"}]}  # a JSON string is read as structure
    assert first["output"] == [{"role": "assistant", "content": "Filter open tickets"}]
    assert (tool["tool_name"], tool["tool_args"], tool["tool_result"]) == ("search", {"q": "open tickets"}, [])
    assert last["output"] == "You have 0 open tickets."  # plain text stays text
    assert run["status"] == "ok" and "outcome" not in run or run.get("outcome") is None  # no verdict yet


def test_a_retried_export_does_not_make_a_second_run(key, store):
    send(two_agents(), key)
    again = send(two_agents(), key)
    assert again.status_code == 200
    assert len(store.runs) == 1 and len(store.steps) == 3


def test_a_gzip_body_works_and_a_bomb_does_not(key):
    raw = json.dumps(two_agents()).encode()
    assert send(None, key, content=gzip.compress(raw), headers={"Content-Encoding": "gzip"}).status_code == 200
    bomb = gzip.compress(b" " * (6 * 1024 * 1024))
    assert send(None, key, content=bomb, headers={"Content-Encoding": "gzip"}).status_code == 413


def test_protobuf_is_refused_with_a_way_forward_and_junk_is_a_400(key):
    refused = send(None, key, content=b"\x0a\x00", headers={"Content-Type": "application/x-protobuf"})
    assert refused.status_code == 415 and "JSON" in refused.json()["detail"]
    assert send(None, key, content=b"not json").status_code == 400
    assert send({"resourceSpans": [{"scopeSpans": [{"spans": [{"nonsense": 1}]}]}]}, key).status_code == 400


def test_the_workspace_comes_from_the_key_and_a_bad_key_gets_nothing(key, store, login):
    assert send(two_agents(), "at_live_" + "0" * 40).status_code == 401
    assert send(two_agents(), "not-a-key").status_code == 401
    send(two_agents(), key)
    assert store.runs[TRACE]["workspace"] == "ws-a"
    login("ws-b", role="member")
    assert read_run().status_code == 404  # another organization cannot read it


def test_the_same_trace_id_from_another_workspace_is_reported_not_merged(key, store, login):
    send(two_agents(), key)
    login("ws-b", role="admin")
    with TestClient(app) as client:
        other = client.post("/v1/keys").json()["key"]
    resp = send(two_agents(), other)
    assert resp.status_code == 200 and resp.json()["partialSuccess"]["rejectedSpans"] > 0
    assert store.runs[TRACE]["workspace"] == "ws-a"


def test_a_trace_with_no_genai_spans_is_rejected_by_name_and_the_rest_still_arrive(key, store):
    plain = span("c0000001", "GET /health", at=0, trace="1" * 32)
    resp = send(body(plain, *two_agents()["resourceSpans"][0]["scopeSpans"][0]["spans"]), key)
    partial = resp.json()["partialSuccess"]
    assert partial["rejectedSpans"] == 1 and "gen_ai" in partial["errorMessage"]
    assert TRACE in store.runs and "1" * 32 not in store.runs


def test_a_step_with_no_agent_span_is_named_by_its_span_and_a_tool_joins_the_step_before_it(key):
    loose = body(
        span("d0000001", "chat claude", "chat", at=0, gen_ai__output__messages="plan"),
        span("d0000002", "execute_tool search", "execute_tool", at=1, gen_ai__tool__name="search"),
        span("d0000003", "chat other", "chat", at=2, gen_ai__agent__name="critic", gen_ai__output__messages="ok"),
    )
    send(loose, key)
    steps = read_run().json()["steps"]
    assert [(s["agent"], s["node_run_idx"], s["kind"]) for s in steps] == [("chat claude", 1, "llm"), ("chat claude", 1, "tool"), ("critic", 2, "llm")]


def test_a_secret_in_a_prompt_or_a_tool_call_is_redacted_before_it_is_stored(key, store):
    leaky = body(
        span("e0000001", "chat", "chat", at=0, gen_ai__input__messages=json.dumps([{"role": "user", "content": f"use {PLANTED_KEY}"}]),
             gen_ai__output__messages=f"ok {PLANTED_KEY}"),
        span("e0000002", "tool", "execute_tool", at=1, gen_ai__tool__name="t", gen_ai__tool__call__arguments=json.dumps({"api_key": PLANTED_KEY})),
    )
    send(leaky, key)
    assert PLANTED_KEY not in json.dumps(read_run().json())


def test_state_the_harness_attached_to_an_agent_turn_is_kept_on_that_turns_last_step(key):
    payload = two_agents()
    for s in payload["resourceSpans"][0]["scopeSpans"][0]["spans"]:
        if s["spanId"] == "a0000002":
            s["attributes"].append(attr("agenttrace.state_after", json.dumps({"answer": "0 open tickets"})))
    send(payload, key)
    steps = read_run().json()["steps"]
    assert [s["state_after"] for s in steps] == [None, None, {"answer": "0 open tickets"}]


def test_a_huge_trace_is_rejected_whole_rather_than_cut_short(key, store):
    many = body(*[span(f"{i:016x}", "chat", "chat", at=i, gen_ai__output__messages="x") for i in range(1, 302)])
    resp = send(many, key)
    assert resp.json()["partialSuccess"]["rejectedSpans"] == 301 and not store.runs


# --- P2: the run gets a verdict from the caller's own check ----------------------------------

def test_a_run_from_p1_gets_right_or_wrong_from_a_check_the_caller_wrote(key, store):
    send(two_agents(), key)
    assert store.runs[TRACE].get("outcome") is None  # no verdict yet

    class OverHttp:
        """The SDK's sink interface, pointed at the in-process API with the same ingest key."""
        async def start_run(self, run): ...
        async def add_steps(self, run_id, steps): ...
        async def finish_run(self, run_id, status, outcome=None, oracle_detail=None):
            with TestClient(app) as client:
                r = client.post(f"/v1/runs/{run_id}/finish", json={"status": status, "outcome": outcome, "oracle_detail": oracle_detail},
                                headers={"Authorization": f"Bearer {key}"})
            assert r.status_code == 200

    def says_five(state):
        return state["answer"] == "5 open tickets", f"the run said {state['answer']!r}"

    outcome = asyncio.run(submit_verdict(OverHttp(), TRACE, says_five, {"answer": "0 open tickets"}))
    assert outcome == "fail"
    run = read_run().json()
    assert run["outcome"] == "fail"
    assert run["oracle_detail"]["verdict"] == {"kind": "code", "name": "says_five", "passed": False, "reason": "the run said '0 open tickets'"}
    with TestClient(app) as client:  # and the Runs page's list shows it as wrong
        listed = client.get("/v1/runs?kind=recorded").json()
    assert [(r["id"], r["outcome"]) for r in listed] == [(TRACE, "fail")]
