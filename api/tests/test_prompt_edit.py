"""Forking with new instructions instead of a new output. Offline: a fake model answers from the
instructions it is shown, so the recorded (buggy) planner instructions fail and the fixed ones pass,
and the tests can see which instructions each arm really ran with."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from agenttrace_sdk import trace_run
from pydantic import ValidationError

from app.experiments import runner
from app.models import ExperimentCreate
from app.replay.fork import prepare_fork, run_fork
from app.runner.run import run_to_end
from app.runner.sink import DbSink
from app.workflows.renewal_brief.graph import next_node
from app.workflows.renewal_brief.nodes import build_nodes
from app.workflows.renewal_brief.prompts import BUG_LINE, PLANNER_SYSTEM_BUGGY, PLANNER_SYSTEM_GOOD
from app.workflows.renewal_brief.tools import FixtureTools
from test_experiments import FakeLLM
from test_fork import WS, steps_of
from test_renewal_brief import APPROVE, BUGGY_PLAN, GOOD_PLAN, REQUEST, draft


class PromptAwareLLM(FakeLLM):
    """Like FakeLLM, but the planner follows the instructions it is given, and every system prompt is kept."""

    def __init__(self) -> None:
        super().__init__()
        self.systems: list[str] = []
        self.messages = SimpleNamespace(create=self._ask)

    async def _ask(self, **kw):
        self.systems.append(kw["system"])
        if kw["system"].startswith("You are the planning agent"):
            plan = BUGGY_PLAN if BUG_LINE in kw["system"] else GOOD_PLAN
            text = json.dumps(plan)
            block = SimpleNamespace(type="text", text=text, model_dump=lambda mode="python": {"type": "text", "text": text})
            return SimpleNamespace(content=[block], stop_reason="end_turn",
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5))
        return await self._create(**kw)


@pytest.fixture
def parent(store):
    """A run recorded with the planted-bug planner instructions: it says 0 open tickets and fails."""
    async def go():
        async with trace_run("renewal_brief", DbSink(WS)) as r:
            await run_to_end(build_nodes(PLANNER_SYSTEM_BUGGY), next_node, {"request": REQUEST},
                             PromptAwareLLM(), FixtureTools())
        return r.id

    return asyncio.run(go())


def fork(parent, k, prompt, arm, client=None):
    return asyncio.run(run_fork(WS, parent, k, None, arm, client=client or PromptAwareLLM(),
                                tools=FixtureTools(), prompt=prompt))


def test_the_agent_runs_again_in_both_arms_with_its_own_instructions(store, parent):
    client = PromptAwareLLM()
    treated = fork(parent, 1, PLANNER_SYSTEM_GOOD, "treatment", client)
    control = fork(parent, 1, PLANNER_SYSTEM_GOOD, "control", client)

    assert store.runs[treated]["outcome"] == "pass"
    assert store.runs[control]["outcome"] == "fail"  # the control arm kept the recorded, buggy instructions
    assert client.systems[0] == PLANNER_SYSTEM_GOOD and client.systems[len(client.systems) // 2] == PLANNER_SYSTEM_BUGGY


def test_node_run_k_is_not_copied_or_edited_it_runs_live_and_numbering_continues(store, parent):
    steps = steps_of(store, fork(parent, 1, PLANNER_SYSTEM_GOOD, "treatment"))
    assert [s["origin"] for s in steps] == ["live"] * 6  # nothing to copy before the first agent
    assert [s["node_run_idx"] for s in steps] == [1, 2, 2, 2, 3, 4]
    assert [s["idx"] for s in steps] == [1, 2, 3, 4, 5, 6]
    assert steps[0]["input"]["system"] == PLANNER_SYSTEM_GOOD and steps[0]["tokens_in"] > 0


def test_forking_a_later_agent_replays_everything_before_it_exactly(store, parent):
    steps = steps_of(store, fork(parent, 3, "You are the writing agent. Say 4 tickets.", "treatment"))
    assert [s["origin"] for s in steps] == ["replayed"] * 4 + ["live"] * 2
    assert [s["node_run_idx"] for s in steps] == [1, 2, 2, 2, 3, 4]
    assert [s["idx"] for s in steps] == [1, 2, 3, 4, 5, 6]
    assert all(s["tokens_in"] == 0 for s in steps[:4])
    assert steps[4]["input"]["system"].startswith("You are the writing agent. Say 4")


def test_one_change_at_a_time(store, parent):
    with pytest.raises(ValueError, match="either what the agent produced or its instructions"):
        asyncio.run(prepare_fork(WS, parent, 1, {"plan": GOOD_PLAN}, FixtureTools(), prompt="x"))
    with pytest.raises(ValidationError):
        ExperimentCreate(run_id="r", fork_node_run_idx=1, n=3, edit={"plan": {}}, prompt="x")
    with pytest.raises(ValidationError):
        ExperimentCreate(run_id="r", fork_node_run_idx=1, n=3)
    with pytest.raises(ValidationError):
        ExperimentCreate(run_id="r", fork_node_run_idx=1, n=3, prompt="")
    with pytest.raises(ValidationError):
        ExperimentCreate(run_id="r", fork_node_run_idx=1, n=3, prompt="x" * 8001)


def test_an_agent_without_plain_text_instructions_cannot_be_edited(store, parent):
    store.steps[(parent, 1)]["input"] = {"system": [{"type": "text", "text": "blocks"}]}
    with pytest.raises(ValueError, match="no plain-text instructions"):
        asyncio.run(prepare_fork(WS, parent, 1, None, FixtureTools(), prompt="x"))


def test_an_experiment_tests_new_instructions_against_the_recorded_ones(store, parent):
    client = PromptAwareLLM()

    async def go():
        exp_id = await runner.create_experiment(
            WS, parent, 1, {}, 3, client=client, tools=FixtureTools(), created_by="t", prompt=PLANNER_SYSTEM_GOOD,
        )
        await runner._TASKS[exp_id]
        return exp_id

    exp_id = asyncio.run(go())
    doc = runner.view(store.experiments[exp_id])
    assert doc["status"] == "done" and doc["edit_mode"] == "prompt"
    assert doc["control"] == {"pass": 0, "total": 3} and doc["treatment"] == {"pass": 3, "total": 3}
    assert doc["edit_patch"] == {"prompt": PLANNER_SYSTEM_GOOD}
    assert doc["stats"]["label"].startswith("directional")


def test_the_stored_instructions_are_redacted(store, parent):
    async def go():
        exp_id = await runner.create_experiment(
            WS, parent, 1, {}, 1, client=PromptAwareLLM(), tools=FixtureTools(), created_by="t",
            prompt=PLANNER_SYSTEM_GOOD + "\nEscalate to a@b.io",
        )
        await runner._TASKS[exp_id]
        return exp_id

    assert "a@b.io" not in str(store.experiments[asyncio.run(go())]["edit_patch"])


def test_a_workflow_this_server_does_not_run_cannot_take_new_instructions(store):
    async def go():
        async with trace_run("outside_flow", DbSink(WS)) as r:
            pass
        with pytest.raises(ValueError, match="registered on this server"):
            await runner.create_experiment(
                WS, r.id, 1, {}, 3, client=PromptAwareLLM(), tools=FixtureTools(), created_by="t", prompt="x",
            )

    asyncio.run(go())


def test_the_api_takes_new_instructions_and_reports_the_result(store, parent, login):
    import time

    from fastapi.testclient import TestClient

    from app.main import app
    from app.runtime import get_runtime

    login(WS)
    app.dependency_overrides[get_runtime] = lambda: (PromptAwareLLM(), FixtureTools())
    try:
        with TestClient(app) as api:
            resp = api.post("/v1/experiments", json={"run_id": parent, "fork_node_run_idx": 1, "prompt": PLANNER_SYSTEM_GOOD, "n": 2})
            assert resp.status_code == 202
            deadline = time.time() + 5
            while time.time() < deadline:
                body = api.get(f"/v1/experiments/{resp.json()['id']}").json()
                if body["status"] == "done":
                    break
                time.sleep(0.02)
            assert body["edit_mode"] == "prompt" and body["treatment"] == {"pass": 2, "total": 2}
            both = api.post("/v1/experiments", json={"run_id": parent, "fork_node_run_idx": 1, "prompt": "x", "edit": {"plan": {}}, "n": 2})
            assert both.status_code == 422
    finally:
        app.dependency_overrides.pop(get_runtime, None)
