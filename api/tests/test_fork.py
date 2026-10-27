"""Phase 5: forking a recorded run. Offline: the parent is recorded with a scripted LLM into an
in-memory store, then forked. The live check (a real planner fork passing the oracle) is
test_fork_live.py and scripts/fork_demo.py."""

import asyncio
import copy
import json

import pytest
from agenttrace_sdk import SideEffectBlocked, tool, trace_run

from app.replay.fork import ModelPinError, run_fork
from app.runner.run import run_to_end
from app.runner.sink import DbSink
from app.workflows.renewal_brief.graph import next_node
from app.workflows.renewal_brief.nodes import build_nodes
from app.workflows.renewal_brief.prompts import PLANNER_SYSTEM_GOOD
from app.workflows.renewal_brief.tools import FixtureTools
from test_renewal_brief import (
    APPROVE, BUGGY_PLAN, GOOD_PLAN, REQUEST, REVISE, ScriptedClient, draft,
)

WS = "ws-a"
FIXED_PLAN = {"plan": GOOD_PLAN}


def run(coro):
    return asyncio.run(coro)


def record(plan, *replies, ws: str = WS) -> str:
    """Record a parent run (origin 'recorded') through DbSink into the fake store."""
    async def go():
        client = ScriptedClient(json.dumps(plan), *replies)
        async with trace_run("renewal_brief", DbSink(ws)) as r:
            await run_to_end(
                build_nodes(PLANNER_SYSTEM_GOOD), next_node, {"request": REQUEST}, client, FixtureTools()
            )
        return r.id

    return run(go())


def fork(parent, k, edit, arm="treatment", client=None, tools=None, **kw):
    return run(run_fork(WS, parent, k, edit, arm, client=client or ScriptedClient(),
                        tools=tools or FixtureTools(), **kw))


def steps_of(store, run_id):
    return run(store.get_run_with_steps(WS, run_id))["steps"]


@pytest.fixture
def buggy_parent(store):
    """The planted-bug run: planner filter ['solved'], writer says 0 open tickets. 6 steps."""
    return record(BUGGY_PLAN, "No open tickets.", draft(0), APPROVE)


class NoNetworkTools(FixtureTools):
    """Data for the oracle, but the tools the nodes call must never run."""

    async def zendesk_search_tickets(self, *a, **k):
        raise AssertionError("tool called during replay")

    async def salesforce_list_open_opportunities(self, *a, **k):
        raise AssertionError("tool called during replay")


class NoNetworkClient:
    class messages:
        @staticmethod
        async def create(**kw):
            raise AssertionError("LLM called during replay")


# --- the core guarantees ---------------------------------------------------------------------

def test_replaying_recorded_steps_makes_zero_network_calls(store):
    parent = record(GOOD_PLAN, "4 open.", draft(4), APPROVE)  # parent passes the oracle
    fork_id = fork(parent, 4, None, "control", client=NoNetworkClient(), tools=NoNetworkTools())

    steps = steps_of(store, fork_id)
    assert [s["origin"] for s in steps] == ["replayed"] * 6
    assert [s["idx"] for s in steps] == [1, 2, 3, 4, 5, 6]
    assert all(s["tokens_in"] == s["tokens_out"] == 0 for s in steps)
    assert store.runs[fork_id]["outcome"] == "pass"  # the copied final state is judged by the oracle


def test_planner_fork_with_the_fixed_filter_passes_and_marks_each_steps_origin(store, buggy_parent):
    client = ScriptedClient("4 open tickets.", draft(4), APPROVE)
    fork_id = fork(buggy_parent, 1, FIXED_PLAN, client=client)

    assert store.runs[fork_id]["outcome"] == "pass" and store.runs[fork_id]["kind"] == "fork"
    steps = steps_of(store, fork_id)
    assert [s["origin"] for s in steps] == ["edited"] + ["live"] * 5
    assert [s["node_run_idx"] for s in steps] == [1, 2, 2, 2, 3, 4]
    assert [s["idx"] for s in steps] == [1, 2, 3, 4, 5, 6]
    edited = steps[0]
    assert edited["output"] == {"edited_updates": FIXED_PLAN}
    assert edited["state_after"]["plan"] == GOOD_PLAN and edited["tokens_in"] == 0
    # the researcher really re-ran against the new plan, with the corrected statuses
    assert steps[1]["tool_args"]["statuses"] == ["new", "open", "pending", "hold"]
    assert all(s["tokens_in"] > 0 for s in steps if s["kind"] == "llm" and s["origin"] == "live")


def test_control_arm_reruns_the_suffix_live_without_the_edit_and_still_fails(store, buggy_parent):
    fork_id = fork(buggy_parent, 1, None, "control", client=ScriptedClient("No open.", draft(0), APPROVE))

    steps = steps_of(store, fork_id)
    assert [s["origin"] for s in steps] == ["replayed"] + ["live"] * 5
    assert steps[1]["tool_args"]["statuses"] == ["solved"]  # the recorded (buggy) plan is kept
    assert store.runs[fork_id]["outcome"] == "fail"


def test_decoy_fork_at_the_critic_does_not_fix_the_failure(store, buggy_parent):
    edit = {"verdict": "revise", "feedback": "verify the open-ticket count against the raw data"}
    fork_id = fork(buggy_parent, 4, edit, client=ScriptedClient(draft(0), APPROVE))

    steps = steps_of(store, fork_id)
    assert [s["origin"] for s in steps] == ["replayed"] * 5 + ["edited", "live", "live"]
    assert [(s["agent"], s["node_run_idx"], s["idx"]) for s in steps[-2:]] == [
        ("writer", 5, 7), ("critic", 6, 8),
    ]  # node runs are counted, not node names (the writer runs a second time)
    assert store.runs[fork_id]["outcome"] == "fail"


def test_a_fork_records_its_parent_and_leaves_the_parent_untouched(store, buggy_parent):
    before = copy.deepcopy(steps_of(store, buggy_parent))
    fork_id = fork(buggy_parent, 1, FIXED_PLAN, client=ScriptedClient("s", draft(4), APPROVE),
                   experiment_id="exp-1")
    assert run(store.list_forks(WS, buggy_parent)) == [
        {"fork_run": fork_id, "parent": buggy_parent, "at_idx": 1, "arm": "treatment", "experiment": "exp-1"}
    ]
    assert steps_of(store, buggy_parent) == before


def test_a_fork_can_itself_be_forked(store, buggy_parent):
    first = fork(buggy_parent, 1, FIXED_PLAN, client=ScriptedClient("s", draft(4), APPROVE))
    second = fork(first, 1, None, "control", client=ScriptedClient("s", draft(4), APPROVE))
    assert store.runs[second]["outcome"] == "pass"  # the edited step's state_after was restorable


# --- refusing bad forks (nothing is created) -------------------------------------------------

@pytest.mark.parametrize(
    ("k", "edit", "message"),
    [(9, None, "no node run 9"), (0, None, "no node run 0"),
     (1, {"findings": {}}, "not writes of node run 1")],
)
def test_bad_fork_points_and_edits_are_refused_before_a_run_exists(store, buggy_parent, k, edit, message):
    runs_before = set(store.runs)
    with pytest.raises(ValueError, match=message):
        fork(buggy_parent, k, edit)
    assert set(store.runs) == runs_before


def test_parent_must_exist_in_the_workspace_and_use_a_registered_workflow(store, buggy_parent):
    with pytest.raises(LookupError, match="not found"):
        run(run_fork("ws-other", buggy_parent, 1, None, "control", client=ScriptedClient(), tools=FixtureTools()))
    store.runs[buggy_parent]["workflow"] = "mystery"
    with pytest.raises(LookupError, match="not registered"):
        fork(buggy_parent, 1, None, "control")


def test_a_recording_made_with_other_model_settings_is_refused_not_silently_swapped(store, buggy_parent):
    store.steps[(buggy_parent, 1)]["model"] = "claude-haiku-4-5"
    with pytest.raises(ModelPinError, match="claude-haiku-4-5"):
        fork(buggy_parent, 1, None, "control")


class MailTools(FixtureTools):
    @tool(side_effect=True)
    async def send_email(self, to: str) -> str:
        raise AssertionError("a real email was sent")


def test_side_effecting_tools_need_a_mock_before_a_fork_is_allowed(store, buggy_parent):
    runs_before = set(store.runs)
    with pytest.raises(SideEffectBlocked, match="send_email"):
        fork(buggy_parent, 1, None, "control", tools=MailTools())
    assert set(store.runs) == runs_before

    async def fake_send_email(to):
        return "mock"

    fork_id = fork(buggy_parent, 4, None, "control", client=NoNetworkClient(), tools=MailTools(),
                   mocks={"send_email": fake_send_email})
    assert fork_id in store.runs


def test_a_suffix_that_crashes_is_recorded_as_an_error_not_raised(store, buggy_parent):
    fork_id = fork(buggy_parent, 1, FIXED_PLAN, client=ScriptedClient())  # LLM script runs dry
    assert store.runs[fork_id]["status"] == "error" and store.runs[fork_id]["outcome"] == "error"
    assert run(store.list_forks(WS, buggy_parent))[0]["fork_run"] == fork_id  # still linked


def test_the_critic_loop_overrun_is_a_failed_fork_not_a_hang(store):
    parent = record(GOOD_PLAN, "s", draft(4), APPROVE)
    client = ScriptedClient(draft(4), REVISE, draft(4), REVISE)
    fork_id = fork(parent, 4, {"verdict": "revise", "feedback": "again"}, client=client)
    assert store.runs[fork_id]["outcome"] == "fail"
