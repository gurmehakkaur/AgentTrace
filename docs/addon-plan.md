# Plan: AgentTrace as an add-on for any harness

Goal: someone who already runs their own agents and orchestration (LangGraph, CrewAI, OpenAI Agents SDK, Claude Agent SDK, or a hand-rolled loop) can plug AgentTrace in without moving their system. It records their runs, tells them which agent probably broke one, and tests the fix on their own code.

Status: P1 to P6 are built (2026-10-24, see `docs/integrations.md` and `docs/self-host.md`); each section lists what it does not do. What P1 and P2 do not do is listed under each. The wording rules in `CLAUDE.md` still apply: recorded steps replay exactly, forked steps re-run live and are never called deterministic, results are k/N per arm plus a Fisher p-value labelled "directional".

## 1. Where we are

| Capability | For your demo workflow | For someone else's harness |
| --- | --- | --- |
| Record runs (SDK, ingest key, JSON import) | Yes | Yes |
| View the run as a line, inspect each step | Yes | Yes, view only |
| Fork and re-run the rest live, k/N and p-value | Yes | No |
| Root-cause agent (RCA) ranks suspects | Yes | No |
| Edit an agent's instructions and re-run it | No | No |

Why the gap: forking re-runs agents, and only workflows listed in `api/app/workflows/registry.py` can run on our server. There is no endpoint that runs arbitrary code, and there must never be one. So for anyone else we are a trace viewer.

## 2. The idea in one picture

```
 their harness ──record──▶ AgentTrace API ──stores──▶ SurrealDB
      ▲                         │  ▲
      │                         │  └── results (runs made by a fork) posted back
      │   fork job (outbound    ▼
      └── poll) ◀────── replay worker, running next to THEIR code
```

Two flows: **record** (their code sends us steps) and **fork** (our API hands a job to a worker that lives next to their code and runs it there). Their prompts, tools and data never need to reach our servers for a fork.

## 3. Work packages

Order matters: each one makes the next one useful.

### P1. Record from anywhere (observability)

Make getting a first trace take about five minutes.

- A small neutral run format: run, agent, step (input, output, tool call), and a state snapshot after each agent. Every adapter maps into it.
- OpenTelemetry (OTLP) ingest endpoint using the GenAI semantic conventions, so anything that already emits traces can point at us.
- Thin adapters, each a few dozen lines: LangGraph, CrewAI, OpenAI Agents SDK, Claude Agent SDK. A generic `step()` decorator for hand-rolled loops.
- Optional later: an HTTP proxy mode, where they point the LLM base URL at us and we record calls with no code change.
- Redaction stays in the SDK, before data leaves their process, and again on ingest.

**Built:** `POST /v1/traces` (OTLP over HTTP, JSON only, ingest key, gzip, idempotent by trace id), `RunRecorder` for any loop, and a LangGraph adapter checked against langgraph 1.2.17. **Not built:** protobuf (needs a decoder dependency, your call), the other adapters (CrewAI, OpenAI Agents SDK, Claude Agent SDK), proxy mode, and a test against a real OpenTelemetry exporter. No data model change was needed.

Done when: a script that uses a harness we did not write records a run, and it appears in the Runs page and the run page with the right agents in order. A test per adapter proves the mapping.

### P2. Let them define "wrong" (the oracle)

The k/N claim depends on a pass/fail check. For a stranger's workflow there is no ground truth we know, so they supply it.

- An oracle is a function `check(final_state) -> pass | fail (+ reason)`, given in one of three ways: a Python function registered in the SDK, a webhook we call with the final output, or an LLM judge.
- LLM judge results are labelled as a lower-trust check in the UI. Code or webhook oracles are the default and the headline.
- A run with no oracle is still recorded. It just shows "no verdict yet" and cannot be used in an experiment.

**Built:** a code check (`run_oracle`, `submit_verdict`, `oracle=` on the recorder and the adapter), stored as `outcome` plus a `verdict` of kind `code`; the run page shows the check and its reason, and a run without one is "no verdict yet", never right. **Not built:** the webhook oracle and the LLM judge.

Done when: a recorded run from P1 gets a pass/fail from a user-supplied oracle, and the Runs page shows it as right or wrong.

### P3. Customer-hosted replay worker (the key piece)

This is what turns us from a viewer into an add-on.

- A small `agenttrace-worker` package the customer runs next to their code. It connects outbound only, so no inbound firewall rule is needed.
- It polls for fork jobs. A job carries: run id, fork point (node run), the edited state, and N.
- It calls the customer's own entrypoint, `resume(state, from_agent)`, which runs the rest of their workflow live and returns the final state.
- It runs the oracle, records the new runs through the normal ingest path, and reports each attempt (control or treatment) back.
- We compute the arms, k/N and the Fisher p-value, labelled "directional".
- Tools that have side effects must be declared and mocked during a fork. A tool without a declaration is treated as side-effecting and is not run live. This is the existing rule, now enforced in the worker.
- Limits per workspace stay: runs per experiment, per user, per minute, and the token ceiling. The worker also has its own local cap.

**Built:** `Worker` in the SDK (outbound polling, `resume` entrypoint, your check as the oracle, `safe_to_rerun=True` required) and `/v1/worker/claim` and `/v1/worker/results` (compare-and-set claims, 10-minute leases, three tries, token ceiling). Data additions, all on schemaless tables: key `scopes`; experiment `mode`, `workflow`, `rev`, `base_state`, `start_idx`; tile `claim`, `claimed_at`, `attempts`. **Not built:** per-step start times, a hosted option for running a customer's code (by design there is none). Worker presence is built: a worker's job request marks its key as seen, and the app and the gate say whether a worker asked in the last minute (new field `last_seen_at` on a key).

Done when: a toy workflow that is not in our registry can be forked end to end through a worker running on the dev machine, with a control arm and a treatment arm, and the result card shows k/N per arm and the p-value.

### P4. Be callable by other agents (the observability-agent role)

- An MCP server and a CLI with tools: `list_failed_runs`, `get_run`, `rank_suspects`, `propose_fork`, `run_experiment`, `get_experiment`.
- Their orchestrator, or a coding agent, can call AgentTrace when something fails and get a ranked suspect with evidence.
- The RCA agent only proposes. A person, or an explicit policy the customer sets, launches the experiment. It has no tool that acts on their system.
- Workspace comes only from the API key or token, never from tool arguments.

**Built:** `/v1/agent/*` (read and spend scopes, charged to the key), an MCP server in the SDK (stdlib, stdio; checked with the real `mcp` client), and the `agenttrace` command line. Tools: `list_failed_runs`, `get_run`, `rank_suspects`, `run_experiment`, `get_experiment`. **Not built:** a separate `propose_fork` (suspects already carry a proposed edit); root cause for workflows not registered on our server.

Done when: an agent connected over MCP can list a workspace's failed runs and get a ranked suspect list for one of them, and a test shows it cannot read another workspace.

### P5. Fit into how teams already work

- Webhook and Slack alert when a run fails, with the top suspect and a link.
- A CI gate: re-run a known failure's experiment and fail the deploy if it regresses.
- Failure memory (Agent Memory) shared across the workspace's runs, as now.

**Built:** alert webhooks (Slack or any address, signed, once per run, rate limited, address checked against private networks, opt-in likely cause) and `agenttrace gate` (re-runs a proven experiment, exit 0 held, 1 regressed, 2 could not tell). Failure memory was already shared. Data additions: table `webhook`, field `alerted_at` on a run. **Not built:** alerts for runs that never report a verdict, retries beyond one, email. The connection is pinned to the address that passed the check, and every call made with a key is limited to 600 a minute.

Done when: a failing run posts an alert with the suspect, and the CI check exits non-zero on a regression in a test.

### P6. Packaging and trust

- `pip install agenttrace` with a five-line quickstart per harness.
- A compatibility table in the docs: which harnesses, how they connect, what works (record only, or record and fork).
- A self-host or bring-your-own-database option for teams that cannot send traces out.
- Update `SECURITY.md` for the worker, the oracle webhook and the MCP server.

**Built:** a compatibility table and a PyPI-less install line in `docs/integrations.md`, `docs/self-host.md` (written from the code, not yet followed on a clean machine), and `SECURITY.md` for the worker, agent routes, webhooks and the gate. **Not built:** a PyPI release (the SDK installs from git), a Docker image or compose file, adapters for CrewAI, the OpenAI Agents SDK and the Claude Agent SDK, the oracle webhook and the LLM judge.

## 4. What to build before the submission

Time is short, so build the smallest slice that proves the claim, and describe the rest as the roadmap.

1. **P1, one adapter and OTLP import.** LangGraph is the likeliest first one. Done when its test passes.
2. **P2, code oracle only.** No webhook and no LLM judge yet.
3. **P3, minimal worker.** One job type, one toy workflow outside the registry, run locally.
4. **Docs and demo.** Add one "bring your own harness" shot to the demo script and one paragraph to the write-up.

Leave P4 to P6 as "what is next" in the write-up. Do not claim them.

## 5. Decisions needed from you

These change the data model or the product's promise, so I will not start them without a yes.

1. **Per-step start times.** Needed to draw parallel agents correctly, and useful for the Gantt. Touches the SDK, ingest and the schema.
2. **Required state snapshots.** A fork needs the state after each agent. Adapters must either capture it or the run is view only. Do we refuse to fork without it, or approximate?
3. **Worker protocol.** Polling for jobs over HTTPS is the plan. Do you accept that the worker needs to be run by the customer, with no hosted option for their code?
4. **Oracle trust.** Are LLM-judge results allowed to appear in an experiment at all, or only in the run view?
5. **Scope for the deadline.** Do we do the minimal slice in section 4, or only the documentation and the demo story?

## 6. Risks

| Risk | What reduces it |
| --- | --- |
| Customers' workflows have no clean "resume from here" | The worker requires a `resume` entrypoint. If a harness cannot resume, the run stays view only and the UI says so. |
| Live re-runs cost tokens and have side effects | Declared side effects, mocks, per-experiment and per-minute caps, a local cap in the worker. |
| An oracle that is wrong makes the numbers wrong | Show which oracle was used. Keep the "directional" label. Prefer code oracles. |
| Too many adapters to maintain | Start with OTLP plus one adapter. Keep the neutral format small. |
| Trust: data leaving their network | Redact in the SDK, run forks in their network, offer self-host later. |
| Scope creep before the deadline | Only section 4 is in scope. Everything else is the roadmap, stated honestly. |

## 7. Order of work

```
P1 record anywhere ─▶ P2 oracle ─▶ P3 worker ─▶ P4 MCP/CLI ─▶ P5 alerts, CI ─▶ P6 packaging
      (before the deadline: P1, P2 and P3 in minimal form)
```
