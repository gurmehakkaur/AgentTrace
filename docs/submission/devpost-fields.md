# Devpost fields: copy each block into its field

Lines in *[brackets]* are for you to fill or confirm before submitting.

## Elevator pitch (200 characters max; this one is 195)

```
AgentTrace finds the step that broke your agent run, then proves the fix: fork it, rerun live with and without the change (0 of 8 becomes 8 of 8), with Slack alerts. Works on top of your harness.
```

## Project story (paste this into "About the project"; it is Markdown)

```markdown
## Inspiration

An AI engineer ships a research → write → critique workflow. It fails nine agent steps deep with a confident, wrong answer: *"0 open tickets"* when the real number is five. Traces show **what happened**. They don't show **what caused it**, and re-running the workflow is noisy, costs tokens, and one lucky re-run proves nothing. We wanted a debugger that treats a fix like an experiment.

## What it does

AgentTrace records a multi-agent run, then lets you **fork it at any step**, edit that step's output, and re-run everything after it **live, N times, in two arms**: a control with no edit and a treatment with your edit. It reports **k of N right per arm plus a Fisher exact p-value, always labelled "directional"**.

On our demo workflow (a four-agent renewal brief):

- **Decoy:** make the critic stricter. **0/5 → 0/5.** The obvious fix does nothing.
- **Hero:** fix the planner's ticket filter. **0/8 → 8/8** (Fisher p = 0.00016, directional).
- A **root-cause agent** ranked the planner first (80%) and a small test supported it (0/3 → 3/3, too few runs to be sure).
- **Generalization:** on five other Era accounts, 3 fresh runs each, the original planner prompt scored **0/15** and the patched one **13/15** (two patched runs crashed and count as failures).

Recorded steps replay exactly from the recording. Forked steps run live, so they are **sampled, never deterministic**. That is why every arm is repeated.

## It works on top of the harness you already run

AgentTrace is built as an observability and testing layer, not a replacement for your orchestration. Working today:

- **LangGraph** and **any Python loop**: a few lines record each agent turn, with secrets redacted before they leave your process.
- **OpenTelemetry**: anything that emits GenAI spans can post them (through an OpenTelemetry Collector for programs that only send protobuf).
- **Your own definition of "wrong"**: a check you write in code gives each run a right/wrong verdict.
- **A worker next to your code** lets you fork agents AgentTrace didn't build. It only connects out, and you state `safe_to_rerun=True` because a fork runs your agents live.
- **Slack or any webhook** tells you when a run fails and when a fork finishes, with what changed and the result.
- **A CI gate** re-runs a fix you already proved against the code you're about to ship and exits non-zero if it stopped working.
- **MCP server and command line** so an assistant or a terminal can list failed runs, rank suspects and start experiments, under keys that say exactly what the caller may do.

Adapters for more harnesses (CrewAI, the OpenAI Agents SDK, the Claude Agent SDK) are **in progress and not part of this submission**.

## How we built it

- **SDK (Python, stdlib only):** records, redacts, and ships the worker, the MCP server and the CLI.
- **API (FastAPI, Pydantic v2):** ingest, forks, experiments, root cause, alerts, workers.
- **SurrealDB Cloud:** runs, steps and the fork graph (`has_step`, `next`, `forked_from`, `tested` edges) plus **Agent Memory** for verified failure patterns.
- **Claude Haiku 5.5:** the demo agents and the root-cause agent (a forced tool call, schema-validated, with evidence quotes checked word for word against the trace).
- **Clerk:** organizations are workspaces; the workspace comes only from the verified identity or key, never from a request body.
- **Era by Eon:** a simulated Zendesk + Salesforce company gives the workflow its tools **and** exact ground truth, so a pass or fail is a fact.
- **Next.js + Tailwind** on **Render**.

## Challenges

- **Honest statistics from small samples.** N is 3 to 8, so we show k/N, a Fisher p-value and the word *directional* everywhere, and the code never calls live steps deterministic.
- **A debugger that can't trust its own measurements.** We ran the whole add-on end to end with nothing faked (real API, real database, real SDK over HTTP). It found that every worker job took 21 seconds, because closing a database connection takes about a second. Reusing connections took a job to 1.5 seconds and the health check from 1.55 s to 0.05 s.
- **Reality vs the spec.** The real Python OpenTelemetry exporter ignores `http/json` and always sends protobuf, so we say so and document the Collector route instead of pretending.
- **Safe re-runs.** A fork runs agents again. Side-effecting tools need a mock, workers must state `safe_to_rerun=True`, and every experiment has per-key, per-user and per-minute limits.

## Accomplishments we're proud of

- A causal claim from a handful of runs, with the uncertainty on screen.
- Every addition is covered by tests (over 300 API tests, 90 SDK tests and over 65 web tests) and the full flow was run for real.
- Security by default: redaction before storage, key scopes, escaped Slack messages, webhook addresses checked against private networks, workspace isolation proven by a test.

## What we learned

A trace tells you where to look; an experiment tells you whether you were right. The decoy result (0/5 → 0/5) taught us the most: the obvious suspect was innocent, and only a controlled re-run could say so.

## What's next

Adapters for CrewAI, the OpenAI Agents SDK and the Claude Agent SDK; OpenTelemetry protobuf directly; per-step start times so parallel agents can be drawn; editing an agent's instructions and re-running it; a clearly labelled lower-trust LLM judge.

*[Prior work: say what existed before Oct 16, if anything. Team: list everyone and who built what.]*
```

## Built with (up to 25 tags)

```
python, fastapi, pydantic, next.js, typescript, react, tailwindcss, surrealdb, surrealdb-agent-memory, claude, anthropic-api, clerk, render, era-by-eon, opentelemetry, langgraph, model-context-protocol, slack, pytest, node.js
```

## "Try it out" links

| Label | Link |
| --- | --- |
| Live demo (no sign-in), with the Examples dropdown | https://agenttrace-web.onrender.com/demo |
| All your runs by time (the Gantt) | https://agenttrace-web.onrender.com/demo/overview |
| Source code | https://github.com/AjayMaan13/AgentTrace |
| API health | https://agenttrace-api-apaa.onrender.com/health |

*[Open each link logged out before you submit. If you upgrade Render, they won't sleep; if not, open them once right before judging.]*

## Project media (JPG/PNG/GIF, 5 MB max, 3:2 ratio, up to 15)

Capture at 1440×900 and crop to 3:2 (1350×900). In this order:

1. **The headline run page**: "The brief says 0 open tickets, not 5." with the line of four agents. `/demo`
2. **The line diagram with the cause marked**: planner "Likely cause 80%", next nodes "Affected by it".
3. **The fork result**: 0/8 → 8/8 with the p-value and "directional".
4. **The decoy**: 0/5 → 0/5 (shows honesty).
5. **All runs by time (Gantt)**: `/demo/overview`, both workflows, forks as diamonds.
6. **The Slack failure message**: *[a real screenshot from your channel]*.
7. **The Slack "Fork finished" message**: *[a real screenshot; test it first]*.
8. **Forking your own agents**: `/demo/worker` (the worker code and the result).
9. **Keys and alerts**: `/demo/connect` with the key picker.
10. **Terminal: the CI gate** passing (exit 0) and failing (exit 1).
11. **The Examples dropdown** open, showing all five examples.
12. **Architecture diagram** from the README.
