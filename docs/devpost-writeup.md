# Devpost write-up

Paste each section into the matching Devpost field. Numbers are the stored results shown on `/demo`; re-check them against the page before submitting. Lines in *[brackets]* are for you to fill or confirm.

## Tagline

A debugger for multi-agent systems: it tests which step broke your run, measures whether the fix works, and sits on top of the harness you already use.

## The problem

An AI engineer ships a research → write → critique workflow and it fails nine agent steps deep with a confident, wrong answer. Traces show what happened, not what caused it. Re-running the workflow is noisy and costs tokens, and one lucky re-run proves nothing. And most teams already run their agents on some harness, so a debugger that asks them to move everything is a debugger they will not use.

## What it does

Record a run, inspect every prompt, tool payload and state change, then fork at any step and edit its output. AgentTrace re-runs the rest live N times in a **control arm** (no edit) and a **treatment arm** (your edit), checks each run with a check you define in code, and reports k/N per arm with a Fisher exact p-value, labelled directional. A root-cause agent ranks the suspect steps and proposes a small edit for each; "Verify" tests the top two by experiment and re-ranks them by measured effect. Verified causes go into shared failure memory and are recalled on the next failure.

On the demo workflow (a renewal brief that wrongly reports 0 open tickets):

- Decoy, make the critic stricter: **0/5 → 0/5** (p = 1.0). The obvious fix does nothing.
- Hero, fix the planner's ticket filter: **0/8 → 8/8** (Fisher p = 0.00016, directional).
- Root-cause agent ranked the planner first (80%); a small test supported it, 0/3 → 3/3 (too few runs to be sure).
- Generalization: original vs patched planner prompt on five other Era accounts, 3 fresh runs each: **0/15 vs 13/15**. Two patched runs crashed and count as failures.

## Works on top of the harness you already run

AgentTrace is built as an observability and testing layer, not a replacement for your orchestration. What is in this submission and working today:

- **LangGraph:** a few lines record every node as an agent turn, with the state after it. Checked against LangGraph 1.2.17 in all three of its stream formats.
- **Any Python loop:** a small recorder (`RunRecorder`) records turn by turn, with secrets redacted before anything leaves your process.
- **OpenTelemetry:** anything that emits GenAI spans can post them (OTLP as JSON, through an OpenTelemetry Collector for programs that only send protobuf). Read correctly from spans produced by the real OpenTelemetry Python SDK.
- **Your own definition of "wrong":** a check you write in code gives every run a right or wrong verdict. Runs with no check say "no verdict yet", never "right".
- **A worker next to your code** lets you fork agents AgentTrace did not build. It connects out only, runs your agents again from the fork point, and reports back; the server counts k/N and the p-value. You state `safe_to_rerun=True` explicitly, because a fork runs your agents live.
- **Slack or any webhook** tells you when a run fails and when a fork finishes, with what changed and the result.
- **A CI gate** (`agenttrace gate`) re-runs a fix you already proved against the code you are about to ship, and exits non-zero if it no longer holds.
- **An MCP server and command line** let an assistant or a terminal list failed runs, rank suspects and start experiments, under keys that say exactly what the caller may do (read, or also spend tokens).

Adapters for more harnesses, such as CrewAI, the OpenAI Agents SDK and the Claude Agent SDK, are in progress and are **not** part of this submission. The recorder and the OpenTelemetry route already work with any code that can call them; each adapter just makes that a one-liner. *[If your teammate's adapters are pushed to the repo before you submit, with a test, change this paragraph to name them. Do not name them until the code is in the repo.]*

Not everything works on every harness, and the app says so: a run with no recorded state stays view-only, and the root-cause ranking works today only for the workflow registered on our server.

## Try it yourself

Open `/demo` (no sign-in) and use the **Examples** dropdown: the saved failing run you can fork, all runs on a Gantt by time, keys and alerts, forking your own agents through a worker, and the terminal and CI. Or sign in, create an organization, and open **Connect your agents**: one button adds the saved example to your workspace, and you can make a key for exactly what you need (send runs, run forks, read, or also spend tokens).

## How it works

Recorded steps replay exactly from the recording; forked steps re-run live against Claude and the data source and are sampled, never deterministic. That is why each arm runs N times. The check is code (for the demo, code against Era's exact data), not an LLM judge. Architecture: a stdlib-only Python SDK records and redacts; a FastAPI service stores traces in SurrealDB Cloud and runs forks, experiments and the root-cause agent; a Next.js app behind Clerk shows it. See the README for the diagram. The whole add-on path was also run end to end with nothing faked (real API, real SurrealDB, real SDK over HTTP: record, read as an agent, fork through a worker, k of N and p-value, CI gate pass and regression, MCP), and that run found and fixed a real performance problem (a worker job took 21 seconds; now about 7).

## Partner platforms

- **Anthropic.** Claude Haiku 5.5 runs the demo agents and the root-cause agent (forced `report_candidates` tool call, schema-validated, evidence quotes checked verbatim against the trace). Haiku 5.5 rejects non-default temperature, so reasoning effort is the sampling control. Code: `api/app/rca/agent.py`, `api/app/config.py`.
- **SurrealDB.** Traces and the fork graph live in SurrealDB Cloud (`has_step`, `next`, `forked_from`, `tested` edges, `api/schema.surql`). **Agent Memory** stores a redacted paragraph for each verified root cause, one scope per source run so deletion is exact. The next analysis recalls it and the UI shows a "seen before" chip. Code: `api/app/rca/memory.py`.
- **Clerk.** Organizations are workspaces with admin and member roles. The API verifies the session JWT via JWKS and takes the workspace only from the token's organization; a test proves one organization cannot read another's run. Code: `api/app/auth.py`, `web/proxy.ts`, `api/tests/test_auth.py`.
- **Era by Eon.** A simulated company (Zendesk and Salesforce) is both the workflow's tool environment and the source of exact ground truth. Because the data is fixed, a pass or fail is a fact, which is what makes a causal claim from a handful of runs defensible.
- **Render.** `web` and `api` services from one `render.yaml`.

## Security and ethics

Secrets are redacted in the SDK and again on ingest; fields are capped at 32 KB; the workspace comes only from the verified identity or the key; keys carry scopes, so a key that only sends runs cannot read them and only a `spend` key can cost tokens; admins can delete a run and everything derived from it, including its Agent Memory patterns; every launch, analysis, alert and deletion is audited; experiments have per-experiment, per-user, per-key and per-minute limits. Webhook addresses are checked against private networks when saved and again when used, and the connection goes to the address that passed the check. The root-cause agent treats the trace as untrusted data, has no tool that acts, and only proposes: a person, or a key that was explicitly given the spend scope, launches experiments. Run content returned to an assistant is clipped and marked as data, not instructions. Demo data is synthetic. It does not claim deterministic replay, apply fixes to production, train on traces, or hold any compliance certification. See `SECURITY.md` for the known gaps.

## Related work and what is new

[Rewind](https://github.com/agentoptics/rewind) and [LangGraph time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel) already fork and replay a run; Rewind also diagnoses failures with an LLM and compares forks with evaluators, including an LLM judge. LangSmith, Langfuse and Phoenix trace and display runs. AgentTrace is complementary and adds: control-arm experiments with uncertainty, root cause ranked by measured effect, a code check on exact ground truth, shared memory of verified failures, and a path onto a harness you already run (a worker, a CI gate and an assistant-facing interface).

## Honest limits

N is 3 to 8, so every result is directional, and the UI says so. Root-cause ranking works only for workflows registered on our server. Forking another system's agents needs a worker you run and a harness that can resume from a step. The OpenTelemetry route reads JSON only, so Python programs need a Collector in front. Slack alerts were tested with a real webhook *[confirm you did this before submitting]*. Two patched benchmark runs crashed and the cause was not recorded.

## What's next

Adapters for CrewAI, the OpenAI Agents SDK and the Claude Agent SDK; accepting OpenTelemetry protobuf directly; per-step start times so parallel agents can be drawn; editing an agent's instructions and re-running it (needs the customer's worker); an LLM judge as a clearly labelled lower-trust check.

## Built this week / prior work

*[Fill in: what existed before Oct 16, if anything. The idea was chosen this week from an earlier shortlist.]* *[Team: list everyone who contributed. The README currently says "solo": change it to match your Devpost team, and say who built which part, including the harness adapters your teammate is working on.]* Templates used: `create-next-app` and the Clerk quickstart for the web app skeleton. Claude Code assisted with the implementation. Tests: 305 API, 90 SDK and 64 web tests offline, plus live-database checks.
