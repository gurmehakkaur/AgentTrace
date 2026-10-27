# Bring your own harness

AgentTrace records runs from agents it did not build, and lets you say whether each run is right. Three ways in, from least to most code. All of them need an ingest key (Connect your agents, then Make a key) and send it as a Bearer token.

| Your setup | How it connects | Recorded | Verdict | Forked (with a worker) | Root cause |
| --- | --- | --- | --- | --- | --- |
| LangGraph | `record_langgraph` reads its update stream | Yes (checked against langgraph 1.2.17) | Yes | Yes | No |
| A loop you wrote | `RunRecorder` | Yes | Yes | Yes | No |
| Anything that emits OpenTelemetry GenAI spans | `POST /v1/traces`, JSON only | Yes (checked against the specification, not a real exporter) | Yes, with `submit_verdict` | No: it carries no state | No |
| CrewAI, OpenAI Agents SDK, Claude Agent SDK | No adapter yet. Use `RunRecorder` inside your code, or their OpenTelemetry output if they emit GenAI spans (not verified) | Through those | Yes | Only through `RunRecorder` | No |
| Past logs | JSON import | Yes | If you send `outcome` | Only if the steps carry `state_after` and `writes` | No |
| The saved renewal example | Built in | Yes | Yes | Yes, run on our server | Yes |

"Root cause" means the ranked list of suspect steps. It needs the workflow's own checks and prompts on our server, so it exists only for workflows registered there. Everything else gets your check's reason instead.

There is no PyPI release yet. Install the SDK with `pip install "git+https://github.com/AjayMaan13/AgentTrace.git#subdirectory=sdk"`; it has no dependencies. Running AgentTrace yourself is in `docs/self-host.md`.

What you get: the run drawn as a line of agents, what went in and out of each step, redaction before storage, a right or wrong verdict from a check you write, and (with a worker, section 4) forking and k/N experiments on your own agents. Root cause (section 5) still only works for workflows registered on our server.

A key can do only what its scopes say: `ingest` sends runs (the default; keys made before scopes can only do this), `worker` takes fork jobs, `read` reads runs and experiments, `spend` may also start root-cause analyses and experiments, which cost tokens. An admin picks them when making the key.

## 1. OpenTelemetry (no code in your agents)

If your harness already emits GenAI spans, point its exporter at AgentTrace.

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://<your-api>"          # the exporter adds /v1/traces
export OTEL_EXPORTER_OTLP_PROTOCOL="http/json"
export OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer at_live_..."
```

- JSON only. An exporter that can only send protobuf can go through an OpenTelemetry Collector with an `otlphttp` exporter set to `encoding: json`. Protobuf direct is refused with that explanation; accepting it needs a decoder this API does not have yet.
- One trace is one run, and its **run id is the trace id**. Send a whole trace in one request (flush your span processor at the end of the workflow). A second delivery of a trace you already sent is ignored, so retries are safe.
- Read: `invoke_agent` spans as agents; `chat`, `text_completion` and `generate_content` spans as model calls; `execute_tool` spans as tool calls. Other spans are skipped. A trace with none of those is rejected and counted in `partialSuccess.rejectedSpans`.
- The GenAI attribute names (`gen_ai.agent.name`, `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.tool.call.arguments`, and so on) are marked Development in the OpenTelemetry conventions, and message content is opt-in at the exporter. If your exporter does not record content, the run shows the agents and timings but empty prompts. Checked against the OTLP JSON specification, not yet against a real exporter.
- Optional: an `agenttrace.state_after` attribute (a JSON object) on an `invoke_agent` span stores the shared state when that turn ended.
- Limits: 5 MB per request (after gzip), 50 traces per request, 300 steps per trace. A trace id already used in another workspace is rejected.

## 2. LangGraph (a few lines, no LangGraph import in the SDK)

```python
from agenttrace_sdk import HttpSink
from agenttrace_sdk.adapters.langgraph import record_langgraph

sink = HttpSink("https://<your-api>", "at_live_...")
run_id = await record_langgraph(
    app.astream(inputs, stream_mode="updates"),   # also works with a list of modes, and version="v2"
    sink, "renewal-brief", input=inputs,
    oracle=check,                                  # optional, see below
    reducers={"notes": operator.add},              # optional: keys whose updates append rather than replace
)
```

It reads the update stream LangGraph already produces: one turn per node, with the state before it as the agent's input and the rebuilt state after it. Probed against langgraph 1.2.17 in all three stream shapes, and the rebuilt state matched LangGraph's own final state when the reducers were given. Without a reducer for a key that has one, the rebuilt value is only the last update, so give the reducers if you want the state to be exact.

For any other loop, use `RunRecorder` the same way: `async with RunRecorder(sink, "name", oracle=check) as rec:` then `await rec.turn("agent", input=..., output=..., tool_calls=[...], state_after=...)`.

## 3. A verdict from your own check

AgentTrace cannot know what "right" means for your workflow. You write it as a function of the run's final state:

```python
def check(state):
    return state["answer"] == "5 open tickets", f"the run said {state['answer']!r}"
```

- It may return `True`/`False`, `(bool, reason)` or a `Verdict`, and may be `async`.
- Pass it as `oracle=` to `record_langgraph` or `RunRecorder`, or judge a run that is already stored (for example one that arrived over OpenTelemetry): `await submit_verdict(sink, trace_id, check, final_state)`.
- The result is stored as `outcome` (pass, fail, or error) with a `verdict` of kind `code`: the check's name and its reason. The Runs page shows the run as right or wrong; the run page shows "Your check <name>" and the reason.
- A check that raises, or returns something that is not a verdict, gives `error`, never a quiet pass. Only the exception type is stored, because the message may hold data. A secret in a reason is redacted, and a reason is cut at 300 characters.
- A run with no check has **no verdict yet**. It is never shown as right.
- This is a check written in code. It is not an AI judge, and it is not more than the function you wrote.

## 4. Fork your own agents with a worker

AgentTrace cannot re-run an agent it did not build, so a fork of your run is run by a worker **you** run next to your code. It connects out to the API (nothing connects in), so no inbound firewall rule is needed. Make a key with the `worker` scope.

```python
import asyncio
from agenttrace_sdk import Worker

async def resume(state, rec):
    # state: the recording up to the fork point, with the change applied for the run that has it.
    # Run your agents from here, record each turn, and return the final state.
    state = await my_writer(state)
    await rec.turn("writer", input=..., output=state["answer"], state_after=state, writes=["answer"])
    return state

worker = Worker("https://<your-api>", "at_live_...")      # a key with the worker scope
worker.register("renewal-brief", resume, oracle=check, safe_to_rerun=True)
asyncio.run(worker.run_forever())
```

- `oracle` is your check from section 3; it decides pass or fail for every attempt, in your process.
- `safe_to_rerun` has no default and must be `True`. A fork runs your agents again, live, several times. We cannot see inside your code, so you are saying that is safe: no real emails or payments, or those tools are mocked.
- A run can be forked if it recorded the state after an agent turn **and** the keys that turn wrote (`state_after=` and `writes=`; the LangGraph adapter records both). You may change only keys the agent wrote. A run from OpenTelemetry has neither, so it stays view only.
- Start a fork from the run page as usual. The experiment waits until the worker takes its first job, and says whether a worker has asked for a job in the last minute, so you can tell a worker that is not running from one that is just slow. For N, the worker is given N jobs without the change and N with it. We record each attempt as a fork run (steps before the fork point replayed exactly from the recording, the change as one edited step, the rest live), count k of N each way and work out the Fisher p-value, labelled directional. Live steps are sampled, never deterministic.
- A job is leased for 10 minutes. If the worker goes quiet, the job goes back in the queue; after three tries it counts as an error run. A resume function that raises is an error run too, and the worker carries on. Only the exception type is kept.
- The state a worker receives is the stored copy, which is already redacted, and an edit with a secret-shaped value reaches the worker redacted. Keep secrets out of your shared state.
- The token ceiling and the per-key and daily experiment limits apply as they do for a person.

## 5. Let an agent ask AgentTrace (MCP and the command line)

Make a key with `read` (look only) or `read` and `spend` (also rank suspects and start experiments, which cost tokens).

```bash
export AGENTTRACE_URL=https://<your-api>
export AGENTTRACE_KEY=at_live_...
agenttrace failed                                        # runs that came out wrong
agenttrace show <run>                                    # its agents, steps and the verdict
agenttrace suspects <run>                                # which step probably broke it (spend; costs tokens)
agenttrace fork <run> <turn> --edit '{"filter": "open"}' -n 5    # test a change (spend; costs tokens)
agenttrace result <experiment>                           # k of n each way, p-value (directional)
agenttrace mcp                                           # the same, as MCP tools over stdio
```

For an assistant such as Claude Code or Claude Desktop, run `agenttrace-mcp` (or `python -m agenttrace_sdk.mcp`) as an MCP server with those two environment variables. Tools: `list_failed_runs`, `get_run`, `rank_suspects`, `run_experiment`, `get_experiment`. Checked with the real `mcp` Python client (2.3.0): handshake, tool list, calls, refusals and ping.

- The tools only look and propose. They change nothing in your system, and an experiment re-runs only through your own worker.
- Root cause (`rank_suspects`) works only for workflows registered on our server; for your own it says so. The proposed edit comes back with the suspect; use `run_experiment` to test it.
- What comes back from a run is data recorded from other programs. Each run response says so and long text is clipped. An agent reading it must not follow instructions found in it.
- The workspace comes from the key, never from an argument. A key cannot read another workspace.

## 6. Failure alerts (Slack or any address)

On the Connect page an admin adds an address. When a run comes out wrong (or ends in an error), each address gets one message: the workflow, the reason your check gave, and a link to the run.

- **Fork results too.** Unless you switch it off, each webhook also gets one message when a fork finishes: what changed, how many runs came out right with and without the change, and the p-value, labelled directional. One message per fork, not per run. Forks made by a worker or by our server both do it.
- **Slack:** paste a Slack incoming-webhook address (it must be `https://hooks.slack.com/services/...`). The message is escaped, so a run cannot ping a channel or put a link of its own in it.
- **Any address:** we post JSON (`event: "run.failed"`, the run, your check's name and reason) and sign the body with a secret shown once, in `X-AgentTrace-Signature: sha256=<hmac of the body>`.
- **The likely cause is opt-in.** It costs tokens and nobody approves it, so a webhook only gets it if you tick the box. It is worked out under the same limits as a person and charged to the webhook, and only for runs of workflows registered on our server. For your own workflows the message carries your check's reason, and says why there is no suspect.
- A run alerts once, however many times its finish is sent. Runs added with the "add the saved example" button, and the fork attempts a fork makes, do not alert on their own. At most 10 alerts a minute per workspace; the rest are dropped and logged. A failed delivery is recorded in the audit log and never stops a run.
- Addresses are checked when saved and again when used: https, the standard port, no user name, and the host must resolve only to public addresses (never a private network or the cloud metadata address). Redirects are not followed. Up to 5 webhooks.
- `Send a test` posts a sample so you can see it arrive.

## 7. A CI gate: does a proven fix still work?

You found a fix and proved it with an experiment (say 8 of 8 right with the change). Before a deploy, run that experiment again against the code you are about to ship:

```bash
agenttrace gate <experiment> --min-pass 0.75      # needs a key with the spend scope
```

It starts the experiment again (the same run, fork point, change and N), waits, and exits **0** if the runs with the change came out right at least `--min-pass` of the time, **1** if they did not (the fix regressed), **2** if it could not tell (not finished in `--timeout` seconds, hit the token ceiling, errored, or the key was refused). Treat 1 and 2 as a failed check. `--no-rerun` judges an experiment as it already stands, with a `read` key and no cost.

- For your own workflow the experiment runs through your worker, so start the worker in the pipeline before the gate, and run it against the code under test.
- Live steps are sampled, never deterministic, and N is small. One flaky run moves the rate: with N of 8 and `--min-pass 0.75`, up to two may fail. The result is directional. Use a larger N, or a lower bar, if your workflow is noisy.
- The gate judges only the runs with the change. It does not ask whether the runs without it still fail.
- The change it re-runs is the stored copy, which was redacted when saved.

## Checking it all against the real thing

`api/scripts/addon_smoke.py` plays a customer end to end with nothing faked: the real API in a subprocess, your SurrealDB (a throwaway `smoke-` workspace, purged at the end) and the real SDK over HTTP. It records a run through the LangGraph adapter, reads it as an agent, forks it through a worker, checks the numbers, runs the CI gate on good and on regressed code, and talks to the MCP server over stdio. It spends no tokens. Alerts to Slack need a public https address, so they are covered by tests only.

Findings from running it for real: every database call opened its own connection (about a second to SurrealDB Cloud), so a worker job took 21 seconds; a worker's claim and result now share one connection. And the Python OpenTelemetry exporter (1.45.1) ignores `OTEL_EXPORTER_OTLP_PROTOCOL=http/json` and always sends protobuf, so the OpenTelemetry endpoint, which reads JSON only, needs an OpenTelemetry Collector in front for Python programs. The spans themselves were read correctly: real spans from that SDK, converted to OTLP JSON as a Collector does, came through with their agents, model, tokens, messages and tool calls intact.

## Sample data for a presentation

`api/scripts/seed_org.py --workspace org_... ` adds runs to a workspace so its Runs page is busy: copies of the workspace's own failing renewal run at other times, and runs of a sample workflow named "support-triage (sample data)" with three experiments, run through the real worker code (a fix that works, one that does not, and a hint). Everything it makes is tagged `seed = "presentation"`, and `--remove` deletes exactly that. It spends no tokens and never writes to Agent Memory. `--dry-run` says what it would do. The public `/demo` pages (the Examples dropdown) use fixed sample data and need no sign-in.
