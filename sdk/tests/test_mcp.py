"""The MCP server's protocol, without any API behind it: a stand-in client records what it was asked."""

import io
import json

from agenttrace_sdk._http import ApiError
from agenttrace_sdk.mcp import SUPPORTED, TOOLS, handle, serve


class Recorder:
    def __init__(self, reply=None, error=None):
        self.calls, self.reply, self.error = [], reply, error

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if self.error:
            raise self.error
        return self.reply


def rpc(client, method, params=None, id=1):
    return handle(client, {"jsonrpc": "2.0", "id": id, "method": method, **({"params": params} if params is not None else {})})


def test_the_handshake_agrees_a_protocol_version_it_knows_and_offers_only_tools():
    c = Recorder()
    assert rpc(c, "initialize", {"protocolVersion": "2024-11-05"})["result"]["protocolVersion"] == "2024-11-05"
    assert rpc(c, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == SUPPORTED[0]
    assert rpc(c, "initialize", {})["result"]["capabilities"] == {"tools": {}}
    assert handle(c, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None  # a notification gets no reply
    assert rpc(c, "ping")["result"] == {}


def test_every_tool_is_listed_with_a_schema_and_the_expensive_ones_say_so():
    tools = {t["name"]: t for t in rpc(Recorder(), "tools/list")["result"]["tools"]}
    assert set(tools) == {"list_failed_runs", "get_run", "rank_suspects", "run_experiment", "get_experiment"} == {t["name"] for t in TOOLS}
    assert all(t["inputSchema"]["type"] == "object" for t in tools.values())
    assert "Costs tokens" in tools["rank_suspects"]["description"] and "Costs tokens" in tools["run_experiment"]["description"]
    assert "Costs tokens" not in tools["get_run"]["description"]


def test_an_unknown_method_is_a_protocol_error_and_junk_input_does_not_stop_the_server():
    assert rpc(Recorder(), "resources/list")["error"]["code"] == -32601
    out = io.StringIO()
    serve(Recorder(reply=[]), io.StringIO('not json\n\n[1, 2]\n{"jsonrpc":"2.0","id":7,"method":"ping"}\n'), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r.get("error", {}).get("code") for r in replies] == [-32700, -32600, None] and replies[2]["id"] == 7


def test_an_id_an_agent_supplies_can_never_reach_outside_its_own_path():
    c = Recorder(reply={})
    rpc(c, "tools/call", {"name": "get_run", "arguments": {"run_id": "../../keys?x=1"}})
    method, path, _ = c.calls[0]
    assert method == "GET" and path.startswith("/v1/agent/runs/") and "/../" not in path and "?" not in path.split("/runs/")[1]


def test_the_apis_refusal_comes_back_as_a_tool_error_and_a_missing_argument_is_a_clear_one():
    refused = rpc(Recorder(error=ApiError(403, "This key cannot do that. Make a key with the 'spend' scope.")), "tools/call", {"name": "rank_suspects", "arguments": {"run_id": "r"}})
    assert refused["result"]["isError"] is True and "'spend' scope" in refused["result"]["content"][0]["text"]
    missing = rpc(Recorder(), "tools/call", {"name": "run_experiment", "arguments": {"run_id": "r"}})
    assert missing["result"]["isError"] is True and "Bad arguments" in missing["result"]["content"][0]["text"]
    assert rpc(Recorder(), "tools/call", {"name": "delete_everything", "arguments": {}})["result"]["isError"] is True


def test_an_experiment_is_started_with_exactly_the_arguments_given():
    c = Recorder(reply={"id": "e1"})
    rpc(c, "tools/call", {"name": "run_experiment", "arguments": {"run_id": "r1", "fork_node_run_idx": 2, "edit": {"k": "v"}, "n": 5, "workspace": "ws-b"}})
    assert c.calls == [("POST", "/v1/agent/experiments", {"run_id": "r1", "fork_node_run_idx": 2, "edit": {"k": "v"}, "n": 5})]  # no workspace argument is forwarded
