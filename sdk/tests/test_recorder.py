"""Phase 2 'Done when': a fake 2-node workflow with a mocked LLM produces the expected steps,
node_run_idx values, state_after on last steps only, and a redacted fake API key."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from agenttrace_sdk import ListSink, TracedLLM, UndeclaredWriteError, node, tool, trace_run

PLANTED_KEY = "sk-ant-api03-PLANTEDsecret0123456789_abcDEF"


def run(coro):
    return asyncio.run(coro)


class Block:
    """Stands in for an Anthropic content block (a pydantic model with model_dump)."""

    def __init__(self, text: str) -> None:
        self.text = text

    def model_dump(self, mode: str = "python") -> dict:
        return {"type": "text", "text": self.text}


class FakeClient:
    """Mocked AsyncAnthropic: replies from a script, records what it was called with."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[Block(self._replies.pop(0))],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )


@tool(side_effect=False)
async def search_tickets(org_id: str, statuses: list[str], limit: int = 25) -> dict:
    return {"count": 3, "statuses": statuses}


@tool(side_effect=True)
async def send_email(to: str) -> str:
    return "sent"


@node("planner", reads=["request"], writes=["plan"])
async def planner(state, llm, tools):
    reply = await llm.create(
        model="claude-haiku-5-5",
        temperature=0.7,
        max_tokens=512,
        system="You are the planner.",
        messages=[{"role": "user", "content": state["request"]}],
    )
    return {"plan": reply.content[0].text}


@node("researcher", reads=["plan"], writes=["findings"])
async def researcher(state, llm, tools):
    found = await search_tickets("org_42", ["new", "open", "pending", "hold"])
    reply = await llm.create(
        model="claude-haiku-5-5",
        max_tokens=256,
        messages=[{"role": "user", "content": f"{state['plan']} {found}"}],
    )
    return {"findings": reply.content[0].text}


async def two_node_workflow(sink, replies=("plan: all tickets", "found 3 open")):
    client = FakeClient(list(replies))
    state = {"request": f"Brief for ACME. api key is {PLANTED_KEY}"}
    async with trace_run("renewal_brief", sink) as r:
        state |= await planner(state, TracedLLM(client, "planner"), None)
        state |= await researcher(state, TracedLLM(client, "researcher"), None)
    return r, state, client


def test_two_node_workflow_records_expected_steps():
    sink = ListSink()
    r, _, _ = run(two_node_workflow(sink))
    steps = sink.steps_for(r.id)

    assert [s["idx"] for s in steps] == [1, 2, 3]
    assert [s["node_run_idx"] for s in steps] == [1, 2, 2]
    assert [(s["agent"], s["kind"]) for s in steps] == [
        ("planner", "llm"), ("researcher", "tool"), ("researcher", "llm"),
    ]
    assert {s["origin"] for s in steps} == {"recorded"}
    assert steps[0]["model"] == "claude-haiku-5-5"
    assert steps[0]["params"] == {"temperature": 0.7, "max_tokens": 512}
    assert (steps[0]["tokens_in"], steps[0]["tokens_out"]) == (11, 7)
    assert steps[0]["output"]["content"] == [{"type": "text", "text": "plan: all tickets"}]
    assert steps[1]["tool_name"] == "search_tickets"
    assert steps[1]["tool_args"] == {
        "org_id": "org_42", "statuses": ["new", "open", "pending", "hold"], "limit": 25,
    }
    assert steps[1]["side_effect"] is False
    assert steps[0]["reads"] == ["request"] and steps[0]["writes"] == ["plan"]
    assert steps[2]["reads"] == ["plan"] and steps[2]["writes"] == ["findings"]
    assert sink.runs[r.id]["status"] == "ok" and sink.runs[r.id]["workflow"] == "renewal_brief"


def test_state_after_is_only_on_the_last_step_of_each_node_run_and_is_fully_merged():
    sink = ListSink()
    r, _, _ = run(two_node_workflow(sink))
    s1, s2, s3 = sink.steps_for(r.id)

    assert s2["state_after"] is None  # researcher's tool step is not its last
    assert set(s1["state_after"]) == {"request", "plan"}
    assert set(s3["state_after"]) == {"request", "plan", "findings"}
    assert s3["state_after"]["findings"] == "found 3 open"


def test_planted_api_key_never_appears_in_anything_emitted():
    sink = ListSink()
    run(two_node_workflow(sink))
    emitted = json.dumps([sink.runs, sink.steps])
    assert PLANTED_KEY not in emitted
    assert "PLANTEDsecret" not in emitted
    assert "[REDACTED:api_key:" in emitted
    first = sink.steps[0]
    assert {"input.messages[0].content", "state_after.request"} <= {r["path"] for r in first["redactions"]}


def test_live_state_and_llm_inputs_are_not_redacted_only_the_stored_copy():
    sink = ListSink()
    _, state, client = run(two_node_workflow(sink))
    assert PLANTED_KEY in state["request"]
    assert PLANTED_KEY in client.calls[0]["messages"][0]["content"]


def test_pii_in_llm_output_is_redacted():
    sink = ListSink()
    r, _, _ = run(two_node_workflow(sink, replies=("contact jane@acme.com", "ok")))
    out = json.dumps(sink.steps_for(r.id)[0]["output"])
    assert "jane@acme.com" not in out and "[REDACTED:email:" in out


def test_node_run_idx_counts_runs_not_names():
    @node("writer", reads=["draft"], writes=["draft"])
    async def writer(state, llm, tools):
        reply = await llm.create(model="m", messages=[{"role": "user", "content": "w"}])
        return {"draft": reply.content[0].text}

    @node("critic", reads=["draft"], writes=["verdict"])
    async def critic(state, llm, tools):
        reply = await llm.create(model="m", messages=[{"role": "user", "content": "c"}])
        return {"verdict": reply.content[0].text}

    async def go(sink):
        client = FakeClient(["d1", "revise", "d2", "approve"])
        llm = TracedLLM(client, "x")
        state = {"draft": ""}
        async with trace_run("loop", sink) as r:
            for fn in (writer, critic, writer, critic):
                state |= await fn(state, llm, None)
        return r

    sink = ListSink()
    r = run(go(sink))
    steps = sink.steps_for(r.id)
    assert [s["node_run_idx"] for s in steps] == [1, 2, 3, 4]
    assert [s["reads"] for s in steps] == [["draft"]] * 4
    assert [s["writes"] for s in steps] == [["draft"], ["verdict"], ["draft"], ["verdict"]]
    assert all(s["state_after"] is not None for s in steps)  # one step per node run


def test_undeclared_write_fails_loudly_and_marks_the_run_as_error():
    @node("sloppy", reads=[], writes=["declared"])
    async def sloppy(state, llm, tools):
        return {"declared": 1, "surprise": 2}

    async def go(sink):
        async with trace_run("w", sink) as r:
            await sloppy({}, None, None)

    sink = ListSink()
    with pytest.raises(UndeclaredWriteError, match="surprise"):
        run(go(sink))
    (rec,) = sink.runs.values()
    assert rec["status"] == "error"


def test_llm_call_outside_a_node_inside_a_run_is_an_error_and_makes_no_api_call():
    client = FakeClient(["never"])

    async def go():
        async with trace_run("w", ListSink()):
            await TracedLLM(client, "a").create(model="m", messages=[])

    with pytest.raises(RuntimeError, match="@node"):
        run(go())
    assert client.calls == []


def test_everything_passes_through_untraced_outside_trace_run():
    client = FakeClient(["hello"])

    async def go():
        reply = await TracedLLM(client, "a").create(model="m", messages=[])
        found = await search_tickets("org", ["open"])
        updates = await planner({"request": "r"}, TracedLLM(FakeClient(["p"]), "planner"), None)
        return reply, found, updates

    reply, found, updates = run(go())
    assert reply.content[0].text == "hello" and found["count"] == 3 and updates == {"plan": "p"}


def test_tool_metadata_and_method_self_is_not_recorded():
    assert send_email.side_effect is True and search_tickets.side_effect is False

    class Tools:
        @tool(side_effect=False)
        async def lookup(self, account_id: str) -> str:
            return "ok"

    @node("n", reads=[], writes=["r"])
    async def n(state, llm, tools):
        return {"r": await tools.lookup("acct_1")}

    async def go(sink):
        async with trace_run("w", sink) as r:
            await n({}, None, Tools())
        return r

    sink = ListSink()
    (step,) = sink.steps_for(run(go(sink)).id)
    assert step["tool_args"] == {"account_id": "acct_1"}


def test_tool_decorator_rejects_sync_functions():
    with pytest.raises(TypeError, match="async"):
        tool(side_effect=False)(lambda x: x)


def test_content_hash_matches_for_identical_inputs_and_differs_otherwise():
    async def go(sink, text):
        client = FakeClient(["r"])

        @node("n", reads=[], writes=["o"])
        async def n(state, llm, tools):
            await llm.create(model="m", messages=[{"role": "user", "content": text}])
            return {"o": 1}

        async with trace_run("w", sink) as r:
            await n({}, TracedLLM(client, "n"), None)
        return sink.steps_for(r.id)[0]["content_hash"]

    h1, h2, h3 = (run(go(ListSink(), t)) for t in ("same", "same", "different"))
    assert h1 == h2 != h3 and len(h1) == 64


def test_origin_is_stamped_on_every_step():
    async def go(sink):
        async with trace_run("w", sink, origin="live") as r:
            await planner({"request": "r"}, TracedLLM(FakeClient(["p"]), "planner"), None)
        return r

    sink = ListSink()
    assert {s["origin"] for s in sink.steps_for(run(go(sink)).id)} == {"live"}


def test_outcome_and_oracle_detail_set_inside_the_block_reach_the_sink():
    async def go(sink):
        async with trace_run("w", sink) as r:
            await planner({"request": "r"}, TracedLLM(FakeClient(["p"]), "planner"), None)
            r.outcome, r.oracle_detail = "fail", {"why": "wrong count"}
        return r

    sink = ListSink()
    rec = sink.runs[run(go(sink)).id]
    assert (rec["outcome"], rec["oracle_detail"], rec["status"]) == ("fail", {"why": "wrong count"}, "ok")


def test_a_crashed_run_gets_outcome_error():
    @node("boom", reads=[], writes=["x"])
    async def boom(state, llm, tools):
        raise ValueError("x")

    async def go(sink):
        async with trace_run("w", sink):
            await boom({}, None, None)

    sink = ListSink()
    with pytest.raises(ValueError):
        run(go(sink))
    assert next(iter(sink.runs.values()))["outcome"] == "error"


# --- fork support: start offsets and the side-effect guard ---------------------------------

def test_a_fork_continues_step_and_node_run_numbering_from_the_given_offsets():
    async def go(sink):
        async with trace_run("w", sink, origin="live", start_idx=5, start_node_run_idx=2) as r:
            await planner({"request": "r"}, TracedLLM(FakeClient(["p"]), "planner"), None)
        return r

    sink = ListSink()
    (s,) = sink.steps_for(run(go(sink)).id)
    assert (s["idx"], s["node_run_idx"], s["origin"]) == (6, 3, "live")


def _email_node():
    @node("mailer", reads=[], writes=["sent"])
    async def mailer(state, llm, tools):
        return {"sent": await send_email("a@b.io")}

    return mailer


def test_side_effecting_tool_is_blocked_in_a_live_run_without_a_mock():
    from agenttrace_sdk import SideEffectBlocked

    async def go(mocks=None):
        async with trace_run("w", ListSink(), origin="live", mocks=mocks):
            return await _email_node()({}, None, None)

    with pytest.raises(SideEffectBlocked, match="send_email"):
        run(go())

    async def fake_send(to):
        return f"mock-sent-to-{to}"

    assert run(go({"send_email": fake_send})) == {"sent": "mock-sent-to-a@b.io"}


def test_side_effecting_tool_still_runs_in_a_normal_recording():
    async def go(sink):
        async with trace_run("w", sink) as r:
            await _email_node()({}, None, None)
        return r

    sink = ListSink()
    (s,) = sink.steps_for(run(go(sink)).id)
    assert s["tool_result"] == "sent" and s["side_effect"] is True
