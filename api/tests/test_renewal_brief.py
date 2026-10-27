"""Phase 3 tests with a scripted LLM and the fixtures backend (no network, no cost).
The live 'Done when' checks (good >= 4/5, buggy 0/3) are run with scripts/run_demo.py."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from agenttrace_sdk import ListSink, trace_run

from app.runner.run import END, run_to_end
from app.workflows.renewal_brief.graph import next_node
from app.workflows.renewal_brief.nodes import build_nodes, parse_json
from app.workflows.renewal_brief.oracle import check, ground_truth, parse_footer
from app.workflows.renewal_brief.prompts import (
    BUG_LINE,
    PLANNER_SYSTEM_BUGGY,
    PLANNER_SYSTEM_GOOD,
)
from app.workflows.renewal_brief.tools import FixtureTools

ACCOUNT = "acct-1"  # fixtures: 4 open-ish tickets, 2 solved; open pipeline 150500.5
REQUEST = f"Write a renewal risk brief for account {ACCOUNT}."
GOOD_PLAN = {"account_id": ACCOUNT, "ticket_filter": {"status": ["new", "open", "pending", "hold"]}}
BUGGY_PLAN = {"account_id": ACCOUNT, "ticket_filter": {"status": ["solved"]}}


def run(coro):
    return asyncio.run(coro)


def draft(open_tickets, pipeline=150500.5):
    footer = {"open_tickets": open_tickets, "open_pipeline_usd": pipeline, "risk": "medium"}
    return f"## Support load\n...\n```json\n{json.dumps(footer)}\n```"


APPROVE = json.dumps({"verdict": "approve", "feedback": ""})
REVISE = json.dumps({"verdict": "revise", "feedback": "cite ticket ids"})


class ScriptedClient:
    """Replies in order: planner, researcher summary, writer, critic, [writer, critic ...]."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        text = self._replies.pop(0)
        block = SimpleNamespace(type="text", text=text, model_dump=lambda mode="python": {"type": "text", "text": text})
        return SimpleNamespace(
            content=[block], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


async def execute(client, planner_system=PLANNER_SYSTEM_GOOD):
    tools, sink = FixtureTools(), ListSink()
    async with trace_run("renewal_brief", sink) as r:
        final = await run_to_end(
            build_nodes(planner_system), next_node, {"request": REQUEST}, client, tools
        )
    truth = await ground_truth(tools, ACCOUNT)
    return final, sink.steps_for(r.id), truth


# --- tools ---------------------------------------------------------------------------------

def test_fixture_tools_filter_by_requested_statuses_and_sum_pipeline_in_code():
    tools = FixtureTools()
    open_ = run(tools.zendesk_search_tickets(ACCOUNT, ["new", "open", "pending", "hold"]))
    assert open_["total"] == 4 and open_["by_status"] == {"new": 1, "open": 2, "pending": 1}
    solved = run(tools.zendesk_search_tickets(ACCOUNT, ["solved"]))
    assert solved["total"] == 2 and solved["by_status"] == {"solved": 2}
    pipeline = run(tools.salesforce_list_open_opportunities(ACCOUNT))
    assert pipeline["open_count"] == 2 and pipeline["open_pipeline_usd"] == 150500.5


@pytest.mark.parametrize("bad", ["acct-1' OR Id != '", "acct 1", "", "x" * 100])
def test_account_id_from_the_llm_is_validated_before_it_reaches_a_query(bad):
    with pytest.raises(ValueError, match="invalid account id"):
        run(FixtureTools().zendesk_search_tickets(bad, ["open"]))


# --- graph ---------------------------------------------------------------------------------

def test_next_node_follows_planner_researcher_writer_critic_then_ends_on_approve():
    state = {}
    assert next_node(state) == "planner"
    state["plan"] = {}
    assert next_node(state) == "researcher"
    state["findings"] = {}
    assert next_node(state) == "writer"
    state |= {"drafts": 1}
    assert next_node(state) == "critic"
    state |= {"reviews": 1, "verdict": "approve"}
    assert next_node(state) == END


def test_revise_loops_back_to_writer_until_the_revision_cap_then_ends():
    base = {"plan": {}, "findings": {}}
    assert next_node(base | {"drafts": 1, "reviews": 1, "verdict": "revise"}) == "writer"
    assert next_node(base | {"drafts": 2, "reviews": 2, "verdict": "revise"}) == "writer"
    assert next_node(base | {"drafts": 3, "reviews": 3, "verdict": "revise"}) == END


# --- oracle --------------------------------------------------------------------------------

def test_ground_truth_counts_new_open_pending_hold_and_open_pipeline():
    assert run(ground_truth(FixtureTools(), ACCOUNT)) == {
        "open_tickets": 4, "open_pipeline_usd": 150500.5,
    }


def test_oracle_passes_a_correct_approved_brief():
    truth = {"open_tickets": 4, "open_pipeline_usd": 150500.5}
    ok, detail = check({"draft": draft(4), "verdict": "approve", "drafts": 1}, truth)
    assert ok and detail["footer"]["open_tickets"] == 4


@pytest.mark.parametrize(
    ("state", "why"),
    [
        ({"draft": draft(0), "verdict": "approve", "drafts": 1}, "wrong ticket count"),
        ({"draft": draft(4, 99999), "verdict": "approve", "drafts": 1}, "pipeline off by >1%"),
        ({"draft": draft(4), "verdict": "revise", "drafts": 3}, "critic loop overran"),
        ({"draft": "no footer here", "verdict": "approve", "drafts": 1}, "no footer"),
        ({"draft": '```json\n{"open_tickets": "4"}\n```', "verdict": "approve", "drafts": 1}, "string"),
    ],
)
def test_oracle_fails_each_way_a_run_can_be_wrong(state, why):
    ok, _ = check(state, {"open_tickets": 4, "open_pipeline_usd": 150500.5})
    assert not ok, why


def test_oracle_allows_pipeline_within_one_percent():
    truth = {"open_tickets": 4, "open_pipeline_usd": 150500.5}
    ok, _ = check({"draft": draft(4, 150000), "verdict": "approve", "drafts": 1}, truth)
    assert ok


def test_footer_parser_takes_the_last_fenced_block():
    text = '```json\n{"open_tickets": 1}\n```\ntext\n```json\n{"open_tickets": 2}\n```'
    assert parse_footer(text) == {"open_tickets": 2}
    assert parse_footer("```json\n{broken\n```") is None


# --- prompts -------------------------------------------------------------------------------

def test_buggy_prompt_is_the_good_prompt_plus_the_planted_line():
    assert PLANNER_SYSTEM_BUGGY.startswith(PLANNER_SYSTEM_GOOD)
    assert BUG_LINE == "Only count tickets with status solved when judging support load."
    assert BUG_LINE in PLANNER_SYSTEM_BUGGY and BUG_LINE not in PLANNER_SYSTEM_GOOD


def test_parse_json_handles_prose_and_fences():
    assert parse_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json("no json")


# --- end to end with a scripted LLM --------------------------------------------------------

def test_good_plan_passes_the_oracle_and_records_the_expected_steps():
    client = ScriptedClient(json.dumps(GOOD_PLAN), "4 open tickets.", draft(4), APPROVE)
    final, steps, truth = run(execute(client))

    assert check(final, truth)[0]
    assert [(s["node_run_idx"], s["kind"]) for s in steps] == [
        (1, "llm"), (2, "tool"), (2, "tool"), (2, "llm"), (3, "llm"), (4, "llm"),
    ]
    assert [s["tool_name"] for s in steps if s["kind"] == "tool"] == [
        "zendesk_search_tickets", "salesforce_list_open_opportunities",
    ]
    assert all(s["side_effect"] is False for s in steps if s["kind"] == "tool")
    assert steps[0]["state_after"]["plan"] == GOOD_PLAN


def test_planted_bug_fails_the_oracle_and_the_cause_is_visible_in_the_planner_output():
    client = ScriptedClient(json.dumps(BUGGY_PLAN), "No open tickets.", draft(0), APPROVE)
    final, steps, truth = run(execute(client, PLANNER_SYSTEM_BUGGY))

    ok, detail = check(final, truth)
    assert not ok and detail["open_tickets_ok"] is False and detail["pipeline_ok"] is True
    assert steps[0]["state_after"]["plan"]["ticket_filter"]["status"] == ["solved"]
    assert steps[1]["tool_args"]["statuses"] == ["solved"]  # the researcher followed the plan


def test_critic_loop_revises_then_approves():
    client = ScriptedClient(
        json.dumps(GOOD_PLAN), "s", draft(3), REVISE, draft(4), APPROVE
    )
    final, steps, truth = run(execute(client))
    assert final["drafts"] == 2 and final["reviews"] == 2 and check(final, truth)[0]
    assert [s["node_run_idx"] for s in steps][-2:] == [5, 6]  # node runs, not node names


def test_critic_that_never_approves_overruns_and_fails():
    client = ScriptedClient(
        json.dumps(GOOD_PLAN), "s", draft(4), REVISE, draft(4), REVISE, draft(4), REVISE
    )
    final, _, truth = run(execute(client))
    assert final["drafts"] == 3 and not check(final, truth)[0]
