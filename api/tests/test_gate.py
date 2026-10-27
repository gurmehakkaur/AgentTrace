"""P5: the CI gate. A fix that was proven once is run again against the code about to ship, and the command's exit
status says whether it held. Offline: the real routes, the real worker and the real command, over the in-memory store."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.runtime import get_runtime
from agenttrace_sdk import cli, gate
from test_agent_api import keys_for
from test_mcp import Shim
from test_worker import drain, make_worker, record, resume


@pytest.fixture
def world(store, login):
    login("ws-a", role="admin")
    app.dependency_overrides[get_runtime] = lambda: (None, None)
    with TestClient(app) as client:
        yield client, {"ingest": keys_for(client, "ingest"), "worker": keys_for(client, "worker"),
                       "read": keys_for(client, "read"), "spend": keys_for(client, "read", "spend")}
    app.dependency_overrides.pop(get_runtime, None)


async def regressed(state, rec):
    """The same code after a bad change: the writer no longer reads the filter."""
    state = {**state, "answer": "0 open tickets"}
    await rec.turn("writer", input={"filter": state["filter"]}, output={"answer": state["answer"]}, state_after=state, writes=["answer"], tokens_in=10, tokens_out=5)
    return state


def proven_fix(client, keys, n=4):
    """A fix that worked: an experiment on a failing run, run to the end by good code, with the change right every time."""
    run_id = record(client, keys)
    exp_id = client.post("/v1/agent/experiments", json={"run_id": run_id, "fork_node_run_idx": 1, "edit": {"filter": "open"}, "n": n},
                         headers={"Authorization": f"Bearer {keys['spend']}"}).json()["id"]
    drain(make_worker(client, keys))
    done = client.get(f"/v1/experiments/{exp_id}").json()
    assert done["treatment"] == {"pass": n, "total": n} and done["control"] == {"pass": 0, "total": n}
    return exp_id


@pytest.fixture
def ci(world, monkeypatch, capsys):
    """Run `agenttrace gate` as a pipeline would, with a worker standing by that runs `code` when the gate waits."""
    client, keys = world
    state = {"code": resume}

    def command(key, *argv, code=None):
        state["code"] = code or resume
        monkeypatch.setenv("AGENTTRACE_URL", "http://api.test")
        monkeypatch.setenv("AGENTTRACE_KEY", keys[key])
        monkeypatch.setattr(cli, "ApiClient", lambda url, k: Shim(client, k))
        worker = make_worker(client, keys, fn=state["code"], name="ci")
        monkeypatch.setattr(cli, "run_gate", lambda *a, **kw: gate.run_gate(*a, **kw, sleep=lambda s: drain(worker), poll=0))
        status = cli.main(list(argv))
        out = capsys.readouterr()
        return status, out.out, out.err
    return client, keys, command


def test_the_gate_passes_when_the_fix_still_works_and_exits_non_zero_when_the_code_regressed(ci):
    client, keys, command = ci
    exp_id = proven_fix(client, keys)

    status, out, _ = command("spend", "gate", exp_id)
    assert status == 0 and "The fix held" in out and "4 of 4 right" in out and "directional" in out

    status, out, _ = command("spend", "gate", exp_id, code=regressed)
    assert status == 1 and "The fix regressed" in out and "with the change 0 of 4 right" in out  # the pipeline stops here


def test_each_gate_run_is_a_new_experiment_and_the_old_result_is_left_alone(ci, store):
    client, keys, command = ci
    exp_id = proven_fix(client, keys)
    before = json.dumps(client.get(f"/v1/experiments/{exp_id}").json(), sort_keys=True)
    command("spend", "gate", exp_id, code=regressed)
    assert len(store.experiments) == 2
    assert json.dumps(client.get(f"/v1/experiments/{exp_id}").json(), sort_keys=True) == before
    new = next(e for i, e in store.experiments.items() if i != exp_id)
    assert (new["parent_run"], new["fork_idx"], new["n"], new["edit_patch"]) == (store.experiments[exp_id]["parent_run"], 1, 4, {"filter": "open"})


def test_the_bar_is_the_callers_to_set_and_one_flaky_run_decides_a_result_on_the_line(ci):
    client, keys, command = ci
    exp_id = proven_fix(client, keys)

    def one_flaky_run():
        """Jobs go control 1, with 1, control 2, with 2 ...: the eighth is the fourth run with the change."""
        calls = {"n": 0}

        async def code(state, rec):
            calls["n"] += 1
            return await (regressed if calls["n"] == 8 else resume)(state, rec)
        return code
    status, out, _ = command("spend", "gate", exp_id, "--min-pass", "0.75", code=one_flaky_run())
    assert status == 0 and "with the change 3 of 4 right" in out  # 75% is exactly the bar: it holds
    status, out, _ = command("spend", "gate", exp_id, "--min-pass", "0.76", code=one_flaky_run())
    assert status == 1 and "at least 76%" in out  # the same result, a slightly higher bar: it fails
    status, out, _ = command("spend", "gate", exp_id, "--min-pass", "1.0", code=regressed)
    assert status == 1 and "at least 100%" in out


def test_a_gate_that_cannot_finish_or_cannot_ask_is_a_failure_never_a_pass(ci, store, monkeypatch, capsys):
    client, keys, command = ci
    exp_id = proven_fix(client, keys)
    # a read key may not start an experiment: the pipeline must stop, not wave the deploy through
    status, _, err = command("read", "gate", exp_id)
    assert status == 2 and "spend" in err
    # no worker takes the jobs, so it never finishes
    monkeypatch.setenv("AGENTTRACE_KEY", keys["spend"])
    monkeypatch.setattr(cli, "ApiClient", lambda url, k: Shim(client, k))
    monkeypatch.setattr(cli, "run_gate", lambda *a, **kw: gate.run_gate(*a, **kw, sleep=lambda s: None, poll=0))
    assert cli.main(["gate", exp_id, "--timeout", "0"]) == 2
    assert "A worker is connected but has not taken a job" in capsys.readouterr().out  # one asked a moment ago
    for k in store.api_keys:  # now every worker has been quiet for two minutes
        k["last_seen_at"] = "2020-01-01T00:00:00+00:00"
    assert cli.main(["gate", exp_id, "--timeout", "0"]) == 2
    assert "No worker has asked for a job lately. Is your worker running?" in capsys.readouterr().out
    assert cli.main(["gate", exp_id, "--min-pass", "2"]) == 2
    assert cli.main(["gate", "nosuchexperiment"]) == 2


def test_no_rerun_judges_the_experiment_as_it_stands(ci, store):
    client, keys, command = ci
    exp_id = proven_fix(client, keys)
    status, out, _ = command("read", "gate", exp_id, "--no-rerun")  # looking costs nothing, so a read key will do
    assert status == 0 and "The fix held" in out and len(store.experiments) == 1


# --- the verdict itself ----------------------------------------------------------------------

def exp(status="done", c=(0, 4), t=(4, 4), p=0.0286, **extra):
    return {"status": status, "control": {"pass": c[0], "total": c[1]}, "treatment": {"pass": t[0], "total": t[1]},
            "stats": {"fisher_p": p}, **extra}


def test_the_verdict_is_decided_by_the_runs_with_the_change_and_always_says_directional():
    assert gate.judge(exp(t=(3, 4)), 0.75).code == 0  # exactly at the bar holds
    assert gate.judge(exp(t=(2, 4)), 0.75).code == 1
    assert "directional" in gate.judge(exp(), 0.75).message and "directional" in gate.judge(exp(p=None), 0.75).message
    assert gate.judge(exp(c=(4, 4), t=(4, 4)), 0.75).code == 0  # it does not ask whether the old way still fails


def test_an_experiment_that_did_not_finish_properly_is_unknown_not_passed():
    assert gate.judge(exp("capped"), 0.75).code == 2 and "token ceiling" in gate.judge(exp("capped"), 0.75).message
    assert gate.judge(exp("error", error="RuntimeError"), 0.75).code == 2
    assert gate.judge(exp(t=(0, 0)), 0.75).code == 2
