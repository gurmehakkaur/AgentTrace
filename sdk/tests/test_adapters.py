"""Record a run from a harness the SDK does not wrap (P1) and give it a verdict from your own check (P2)."""

import asyncio
import operator

import pytest

from agenttrace_sdk import ListSink, RunRecorder, Verdict, run_oracle, submit_verdict
from agenttrace_sdk.adapters.langgraph import record_langgraph

PLANTED_KEY = "sk-ant-api03-PLANTEDsecret0123456789_abcDEF"


def run(coro):
    return asyncio.run(coro)


def right_answer(state):
    return state.get("answer") == "5 open tickets"


# --- P2: the code oracle ---------------------------------------------------------------------

def test_a_check_gives_pass_or_fail_with_its_reason_and_is_labelled_a_code_check():
    assert run(run_oracle(right_answer, {"answer": "5 open tickets"}))[0] == "pass"
    outcome, detail = run(run_oracle(lambda s: (False, "said 0, the data says 5"), {}))
    assert outcome == "fail"
    assert detail == {"verdict": {"kind": "code", "name": "<lambda>", "passed": False, "reason": "said 0, the data says 5"}}


def test_every_shape_of_answer_a_check_may_give_is_understood_and_async_checks_work():
    async def later(state):
        return Verdict(True, "fine")
    assert run(run_oracle(later, {}))[0] == "pass"
    assert run(run_oracle(lambda s: (True, "ok"), {}))[0] == "pass"


def test_a_check_that_raises_or_answers_with_nonsense_is_an_error_never_a_pass_or_fail():
    def broken(state):
        raise KeyError("answer")  # the message must not be copied: it may hold data
    outcome, detail = run(run_oracle(broken, {}))
    assert outcome == "error" and detail["verdict"]["passed"] is None
    assert "KeyError" in detail["verdict"]["reason"] and "answer" not in detail["verdict"]["reason"].replace("The check itself failed", "")
    assert run(run_oracle(lambda s: "yes", {}))[0] == "error"  # a string is not a verdict
    assert run(run_oracle(lambda s: None, {}))[0] == "error"


def test_a_secret_in_a_reason_is_redacted_and_the_reason_is_clamped():
    outcome, detail = run(run_oracle(lambda s: (False, f"key {PLANTED_KEY} " + "x" * 1000), {}))
    assert PLANTED_KEY not in str(detail) and len(detail["verdict"]["reason"]) <= 300


def test_a_stored_run_can_be_given_its_verdict_later():
    sink = ListSink()
    run(sink.start_run({"id": "trace0001", "workflow": "wf", "started_at": "2026-01-01T00:00:00+00:00"}))
    assert run(submit_verdict(sink, "trace0001", right_answer, {"answer": "0 open tickets"})) == "fail"
    assert sink.runs["trace0001"]["outcome"] == "fail" and sink.runs["trace0001"]["status"] == "ok"


# --- P1: the recorder for any loop -----------------------------------------------------------

def test_a_hand_rolled_loop_is_recorded_as_turns_with_state_on_each_turns_last_step():
    sink = ListSink()

    async def go():
        async with RunRecorder(sink, "my loop", oracle=right_answer) as rec:
            await rec.turn("planner", input={"request": "brief"}, output={"plan": "filter"}, state_after={"plan": "filter"})
            await rec.turn(
                "writer", output="draft", tool_calls=[{"name": "search", "args": {"q": "tickets"}, "result": [1, 2, 3]}],
                state_after={"plan": "filter", "answer": "5 open tickets"},
            )
        return rec
    rec = run(go())
    steps = sink.steps_for(rec.id)
    assert [(s["idx"], s["node_run_idx"], s["agent"], s["kind"]) for s in steps] == [
        (1, 1, "planner", "llm"), (2, 2, "writer", "llm"), (3, 2, "writer", "tool"),
    ]
    assert [s["state_after"] is not None for s in steps] == [True, False, True]  # only the last step of a turn
    assert steps[2]["tool_name"] == "search" and steps[2]["tool_args"] == {"q": "tickets"}
    assert sink.runs[rec.id]["status"] == "ok" and sink.runs[rec.id]["outcome"] == "pass"  # the last state was checked
    assert all(s["origin"] == "recorded" for s in steps)


def test_a_secret_in_what_an_agent_saw_never_reaches_the_sink():
    sink = ListSink()

    async def go():
        async with RunRecorder(sink, "wf") as rec:
            await rec.turn("a", input={"headers": {"api_key": PLANTED_KEY}}, output=f"used {PLANTED_KEY}",
                           tool_calls=[{"name": "t", "args": {"token": PLANTED_KEY}, "result": PLANTED_KEY}],
                           state_after={"note": PLANTED_KEY})
    run(go())
    assert PLANTED_KEY not in str(sink.steps)
    assert any(s["redactions"] for s in sink.steps)


def test_a_loop_that_crashes_closes_the_run_as_an_error_and_the_error_still_surfaces():
    sink = ListSink()

    async def go():
        async with RunRecorder(sink, "wf", oracle=right_answer) as rec:
            await rec.turn("a", output="x")
            raise RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        run(go())
    only = next(iter(sink.runs.values()))
    assert only["status"] == "error" and only["outcome"] == "error"


def test_without_an_oracle_a_run_has_no_verdict_yet():
    sink = ListSink()

    async def go():
        async with RunRecorder(sink, "wf") as rec:
            await rec.turn("a", output="x")
    run(go())
    assert next(iter(sink.runs.values()))["outcome"] is None


# --- P1: LangGraph (stream shapes probed against langgraph 1.2.17) ---------------------------

PLANNER = {"plan": "check tickets", "notes": ["p"]}
WRITER = {"answer": "5 open tickets", "notes": ["w"]}
PLAIN = [{"planner": PLANNER}, {"writer": WRITER}]
LIST_MODE = [("updates", {"planner": PLANNER}), ("updates", {"writer": WRITER})]
V2 = [{"type": "updates", "ns": (), "data": {"planner": PLANNER}}, {"type": "updates", "ns": (), "data": {"writer": WRITER}}]


@pytest.mark.parametrize("chunks", [PLAIN, LIST_MODE, V2], ids=["updates", "list of modes", "v2"])
def test_each_node_update_is_a_turn_and_the_final_answer_gets_its_verdict(chunks):
    sink = ListSink()
    run_id = run(record_langgraph(iter(chunks), sink, "renewal", input={"request": "brief"}, oracle=right_answer))
    steps = sink.steps_for(run_id)
    assert [(s["agent"], s["node_run_idx"]) for s in steps] == [("planner", 1), ("writer", 2)]
    assert steps[1]["input"]["plan"] == "check tickets"  # what the writer was given: the state before it
    assert steps[1]["state_after"]["answer"] == "5 open tickets" and steps[1]["state_after"]["request"] == "brief"
    assert sink.runs[run_id]["outcome"] == "pass"


def test_an_async_stream_works_and_other_stream_modes_are_ignored():
    async def stream():
        yield ("values", {"request": "brief"})
        yield ("updates", {"planner": PLANNER})
        yield {"__interrupt__": ()}

    sink = ListSink()
    run_id = run(record_langgraph(stream(), sink, "renewal"))
    assert [s["agent"] for s in sink.steps_for(run_id)] == ["planner"]


def test_parallel_nodes_in_one_chunk_are_one_turn_each_and_a_silent_node_is_still_a_turn():
    sink = ListSink()
    run_id = run(record_langgraph(iter([{"a": {"x": 1}, "b": {"y": 2}}, {"c": None}]), sink, "wf"))
    steps = sink.steps_for(run_id)
    assert [(s["agent"], s["node_run_idx"]) for s in steps] == [("a", 1), ("b", 2), ("c", 3)]
    assert steps[1]["state_after"] == {"x": 1, "y": 2}


def test_a_key_with_a_reducer_is_rebuilt_exactly_when_the_reducer_is_given_and_by_last_write_otherwise():
    sink = ListSink()
    first = {"notes": ["a"]}
    chunks = [{"planner": {"notes": ["p"]}}, {"writer": {"notes": ["w"]}}]
    without = run(record_langgraph(iter(chunks), sink, "wf", input=first))
    assert sink.steps_for(without)[-1]["state_after"]["notes"] == ["w"]
    with_reducer = run(record_langgraph(iter(chunks), sink, "wf", input=first, reducers={"notes": operator.add}))
    assert sink.steps_for(with_reducer)[-1]["state_after"]["notes"] == ["a", "p", "w"]


def test_a_graph_that_fails_midway_keeps_the_turns_so_far_and_closes_the_run_as_an_error():
    def stream():
        yield {"planner": PLANNER}
        raise ValueError("graph blew up")

    sink = ListSink()
    with pytest.raises(ValueError):
        run(record_langgraph(stream(), sink, "wf", oracle=right_answer))
    only = next(iter(sink.runs.values()))
    assert only["status"] == "error" and len(sink.steps) == 1
