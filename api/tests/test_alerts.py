"""P5: tell people when a run fails. Offline: no real network, no real model."""

import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import alerts
from app.main import app
from app.runtime import get_runtime
from test_agent_api import judged_run, keys_for
from test_rca import FakeModel, cand, failing_run, tool_use  # noqa: F401 (failing_run is a fixture)
from test_worker import ApiSink, FLOW, drain, make_worker, record, start
from test_worker import world as worker_world  # noqa: F401 (a fixture, under another name)

from agenttrace_sdk import RunRecorder

SLACK = "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXX"
PUBLIC = "https://alerts.example.com/agenttrace"
ADDRESSES = {"alerts.example.com": "93.184.216.34", "internal.example.com": "10.0.0.5", "hooks.slack.com": "34.200.0.1"}


@pytest.fixture
def net(monkeypatch):
    """No real network: names resolve from ADDRESSES, and a post is recorded instead of sent."""
    sent = []

    def resolve(host, port, **kw):
        if host not in ADDRESSES:
            raise OSError("no such host")
        return [(2, 1, 6, "", (ADDRESSES[host], port))]

    def post(url, body, headers):
        sent.append({"url": url, "body": json.loads(body), "raw": body, "headers": headers})
        return 200
    monkeypatch.setattr(alerts.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(alerts, "_post_sync", post)
    return sent


@pytest.fixture
def world(store, login, net, monkeypatch):
    login("ws-a", role="admin")
    holder = {"model": FakeModel([tool_use({"candidates": [cand(), cand(2, 3, 0.4, patch={})]})])}
    app.dependency_overrides[get_runtime] = lambda: (holder["model"], None)
    # An alert builds its own model client, outside any request: replace that too, so no test can reach the real API.
    monkeypatch.setattr("app.runtime.get_runtime", lambda: (holder["model"], None))
    with TestClient(app) as client:
        client.holder = holder
        yield client
    app.dependency_overrides.pop(get_runtime, None)


def add(client, url=SLACK, kind="slack", suspect=False):
    return client.post("/v1/webhooks", json={"url": url, "kind": kind, "include_suspect": suspect})


def notify(run_id, ws="ws-a"):
    asyncio.run(alerts.notify_failure(ws, run_id))


# --- the Done-when line: a failing run posts an alert with the suspect and a link -----------------

def test_a_failing_run_posts_an_alert_with_the_most_likely_cause_and_a_link(world, store, net, failing_run):
    assert add(world, suspect=True).status_code == 201
    notify(failing_run)
    [post] = net
    text = post["body"]["text"]
    assert post["url"] == SLACK
    assert "gave a wrong answer" in text and "Most likely cause: the *planner*" in text and "80%" in text
    assert f"<http://localhost:3000/runs/{failing_run}|Open the run>" in text
    # the cause was worked out on this webhook's account, and the delivery is on the record
    assert [a["actor"] for a in store.audit if a["action"] == "rca.run"] == ["webhook:w1"]
    assert [(a["actor"], a["action"]) for a in store.audit if a["action"].startswith("alert")] == [("webhook:w1", "alert.sent")]


def test_a_run_alerts_once_however_often_it_is_reported_and_a_removed_webhook_is_silent(world, net, failing_run):
    ingest = keys_for(world, "ingest")
    hook = add(world).json()
    notify(failing_run)
    notify(failing_run)
    assert len(net) == 1
    assert world.delete(f"/v1/webhooks/{hook['id']}").status_code == 200
    judged_run(world, {"ingest": ingest}, "fail")  # a new failure, with nobody left to tell
    assert len(net) == 1 and world.get("/v1/webhooks").json()[0]["revoked_at"]


def test_without_asking_for_a_suspect_no_tokens_are_spent(world, net, failing_run):
    add(world, suspect=False)
    notify(failing_run)
    assert world.holder["model"].calls == [] and "Most likely cause" not in net[0]["body"]["text"]


# --- a stranger's run: the alert carries their check's reason --------------------------------

def test_a_run_sent_by_a_harness_alerts_through_the_ingest_route_with_its_checks_reason(world, net):
    ingest = keys_for(world, "ingest")
    add(world, suspect=True)

    async def go():
        async with RunRecorder(ApiSink(world, ingest), FLOW, oracle=lambda s: (False, "the run said 0 open tickets")) as rec:
            await rec.turn("writer", output="0 open tickets", state_after={"answer": "0"}, writes=["answer"])
    asyncio.run(go())  # the run's finish is the trigger: no one calls notify
    [post] = net
    text = post["body"]["text"]
    assert "Check says_five" not in text and "the run said 0 open tickets" in text
    assert "only worked out for runs of workflows registered" in text  # says why there is no suspect
    assert world.holder["model"].calls == []


def test_a_run_that_came_out_right_alerts_nobody(world, net):
    ingest = keys_for(world, "ingest")
    add(world)
    judged_run(world, {"ingest": ingest}, "pass")
    assert net == []


# --- the message cannot be turned against its readers ----------------------------------------

def test_text_from_a_run_cannot_ping_a_channel_or_plant_a_link_in_slack(world, net):
    ingest = keys_for(world, "ingest")
    add(world)
    evil = "<!channel> <https://evil.example|Click to fix> & more"

    async def go():
        async with RunRecorder(ApiSink(world, ingest), "<@U123> flow", oracle=lambda s: (False, evil)) as rec:
            await rec.turn("a", output="x", state_after={"x": 1}, writes=["x"])
    asyncio.run(go())
    text = net[0]["body"]["text"]
    assert "<!channel>" not in text and "<https://evil.example" not in text and "<@U123>" not in text
    assert "&lt;!channel&gt;" in text and "&amp; more" in text
    assert text.count("<http") == 1  # the only link is the one to the run


# --- addresses --------------------------------------------------------------------------------

@pytest.mark.parametrize("url,kind,why", [
    ("http://alerts.example.com/x", "generic", "https"),
    ("https://user:pw@alerts.example.com/x", "generic", "user name"),
    ("https://alerts.example.com:8443/x", "generic", "port"),
    ("https://internal.example.com/x", "generic", "private network"),
    ("https://127.0.0.1/x", "generic", "private network"),
    ("https://169.254.169.254/latest/meta-data", "generic", "private network"),
    ("https://[::1]/x", "generic", "private network"),
    ("https://nowhere.example.com/x", "generic", "cannot be found"),
    ("https://alerts.example.com/services/x", "slack", "hooks.slack.com"),
    ("https://hooks.slack.com/other/x", "slack", "hooks.slack.com"),
])
def test_an_address_that_could_reach_something_internal_is_refused_with_the_reason(world, url, kind, why):
    resp = add(world, url=url, kind=kind)
    assert resp.status_code == 422 and why in resp.json()["detail"]


def test_an_address_that_turns_private_after_it_was_saved_is_not_posted_to(world, net, failing_run):
    add(world, url=PUBLIC, kind="generic")
    ADDRESSES["alerts.example.com"] = "10.9.9.9"  # the name now points inside the network
    try:
        notify(failing_run)
    finally:
        ADDRESSES["alerts.example.com"] = "93.184.216.34"
    assert net == []


# --- webhooks ---------------------------------------------------------------------------------

def test_a_listed_webhook_shows_its_host_and_end_never_the_address_and_members_cannot_manage_them(world, login):
    made = add(world).json()
    listed = world.get("/v1/webhooks").json()
    assert listed == [{"id": made["id"], "kind": "slack", "host": "hooks.slack.com", "ends": "XXXX", "include_suspect": False, "on_forks": True,
                       "created_at": listed[0]["created_at"], "revoked_at": None}]
    assert SLACK not in json.dumps(listed) and SLACK not in json.dumps(made)
    login("ws-a", role="member")
    assert world.get("/v1/webhooks").status_code == 403 and add(world).status_code == 403
    assert world.delete(f"/v1/webhooks/{made['id']}").status_code == 403


def test_a_generic_webhook_is_signed_so_the_receiver_can_tell_it_came_from_us(world, net, failing_run):
    made = add(world, url=PUBLIC, kind="generic").json()
    notify(failing_run)
    [post] = net
    expected = "sha256=" + hmac.new(made["secret"].encode(), post["raw"], hashlib.sha256).hexdigest()
    assert post["headers"]["X-AgentTrace-Signature"] == expected
    assert post["body"]["event"] == "run.failed" and post["body"]["run"]["id"] == failing_run
    assert "secret" not in world.get("/v1/webhooks").json()[0]  # shown once


def test_a_failed_delivery_is_recorded_and_never_breaks_anything(world, store, monkeypatch, failing_run):
    monkeypatch.setattr(alerts, "_post_sync", lambda *a: 500)
    add(world)
    notify(failing_run)  # does not raise
    assert [(a["action"], a["detail"]) for a in store.audit if a["action"].startswith("alert")] == [("alert.failed", {"status": 500})]


def test_a_burst_of_failures_sends_ten_alerts_a_minute_not_all_of_them(world, net, store):
    ingest = keys_for(world, "ingest")
    add(world)
    ids = [judged_run(world, {"ingest": ingest}, "fail") for _ in range(13)]  # each finish already alerted: count those
    assert len(net) == 10
    assert len(ids) == 13


def test_the_test_button_sends_a_sample_and_at_most_five_webhooks_can_exist(world, net):
    hook = add(world).json()
    assert world.post(f"/v1/webhooks/{hook['id']}/test").json() == {"delivered": True, "status": 200}
    assert "A sample alert" in net[0]["body"]["text"] and "sample" in net[0]["body"]["text"]
    for _ in range(4):
        assert add(world).status_code == 201
    assert add(world).status_code == 409


# --- the connection goes where the check said ------------------------------------------------

def test_the_post_connects_to_the_address_that_passed_the_check_not_to_whatever_the_name_means_later(monkeypatch):
    real = alerts._post_sync  # the fixture is not used here: this is the real function
    seen = []
    answers = iter([[(2, 1, 6, "", ("93.184.216.34", 443))], [(2, 1, 6, "", ("10.0.0.5", 443))]])  # a name that changes its mind
    monkeypatch.setattr(alerts.socket, "getaddrinfo", lambda *a, **k: next(answers))

    def connect(address, timeout=None):
        seen.append(address)
        raise OSError("stop here: nothing is listening")
    monkeypatch.setattr(alerts.socket, "create_connection", connect)
    with pytest.raises(OSError):
        real("https://alerts.example.com/hook", b"{}", {})
    assert seen == [("93.184.216.34", 443)]  # the address that was checked: the second lookup is never made
    assert len(list(answers)) == 1


def test_a_name_that_now_resolves_inside_the_network_is_refused_before_any_connection(monkeypatch):
    monkeypatch.setattr(alerts.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 443))])
    monkeypatch.setattr(alerts.socket, "create_connection", lambda *a, **k: pytest.fail("connected to a private address"))
    with pytest.raises(ValueError, match="private network"):
        alerts._post_sync("https://alerts.example.com/hook", b"{}", {})


# --- a finished fork ----------------------------------------------------------------------------

def finished_fork(store, run_id, status="done", c=(0, 5), t=(5, 5), p=0.0079):
    store.experiments["exp-1"] = {
        "id": "exp-1", "workspace": "ws-a", "status": status, "parent_run": run_id, "fork_idx": 1, "n": 5, "mode": "server",
        "control": {"pass": c[0], "total": c[1]}, "treatment": {"pass": t[0], "total": t[1]}, "created_at": "2026-10-24T10:00:00Z",
        "stats": {"fisher_p": p, "label": "directional evidence, N=5"}, "tiles": [],
    }
    return "exp-1"


def test_a_finished_fork_tells_slack_what_changed_and_what_came_out(world, store, net, failing_run):
    add(world)
    asyncio.run(alerts.notify_experiment("ws-a", finished_fork(store, failing_run)))
    [post] = net
    text = post["body"]["text"]
    assert text.startswith("*Fork finished* on *renewal_brief*: changing the *planner*.")
    assert "Without the change 0 of 5 right, with it 5 of 5. The change fixed it." in text
    assert "Directional only (p = 0.008)" in text and "<http://localhost:3000/runs/" in text and f"?fork=exp-1|Open it>" in text
    assert [(a["action"], a["detail"]["about"]) for a in store.audit if a["action"].startswith("alert")] == [("alert.sent", "fork")]


def test_the_words_never_claim_more_than_the_numbers_support():
    words = alerts.fork_words
    assert words({"pass": 0, "total": 5}, {"pass": 5, "total": 5}, 0.008) == "The change fixed it."
    assert "too few runs" in words({"pass": 0, "total": 3}, {"pass": 3, "total": 3}, 0.1)  # 3 of 3 against 0 of 3 is only a hint
    assert words({"pass": 0, "total": 5}, {"pass": 0, "total": 5}, 1.0) == "The change made no difference."
    assert words({"pass": 4, "total": 5}, {"pass": 1, "total": 5}, 0.1) == "The change made things worse."
    assert "not every run" in words({"pass": 0, "total": 8}, {"pass": 5, "total": 8}, 0.01)


def test_a_webhook_can_leave_fork_results_out_and_an_unfinished_fork_tells_nobody(world, store, net, failing_run):
    add(world)
    world.post("/v1/webhooks", json={"url": PUBLIC, "kind": "generic", "on_forks": False})
    for status in ("running", "queued", "error"):
        asyncio.run(alerts.notify_experiment("ws-a", finished_fork(store, failing_run, status)))
    assert net == []
    asyncio.run(alerts.notify_experiment("ws-a", finished_fork(store, failing_run)))
    assert [p["url"] for p in net] == [SLACK]  # the one that asked; the generic one opted out


def test_a_fork_run_through_a_worker_posts_one_message_when_it_finishes_not_one_per_job(worker_world, net):
    client, keys = worker_world
    assert add(client).status_code == 201
    run_id = record(client, keys)
    exp_id = start(client, run_id, n=2).json()["id"]
    assert [("gave a wrong answer" in p["body"]["text"]) for p in net] == [True]  # the failed run alerted when it was recorded; the queued fork says nothing
    assert drain(make_worker(client, keys)) == 4
    texts = [p["body"]["text"] for p in net[1:]]
    assert len(texts) == 1 and "Fork finished" in texts[0] and "Without the change 0 of 2 right, with it 2 of 2" in texts[0]  # one message for four jobs
    assert f"fork={exp_id}" in texts[0]
