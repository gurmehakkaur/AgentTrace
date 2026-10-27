# AgentTrace — Build North Project Map

Oct 21, 2026 · @Ajay

## Summary and assumptions

Ship a narrow, honest MVP: one recorded multi-agent run that fails deep, a root-cause agent that names the culprit step, and a fork experiment with a control arm that moves success from 0/5 to 4/5. Target submission Sun Oct 25 at 18:00 ET, six hours before the deadline.

**Biggest risk is Innovation, not engineering.** [Rewind](https://github.com/agentoptics/rewind) (MIT, open source) already forks at a step, serves earlier steps from cache, re-runs only the fixed step live, diagnoses failures with an LLM (`rewind fix`) and scores forks with LLM-as-judge. [LangGraph time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel) already forks from a checkpoint with modified state. AgentTrace must win on four narrower points, stated plainly in the write-up:

1. **Experiments, not replays.** Every fork runs N live suffixes in a control arm (no edit) and a treatment arm (edit), and reports a success rate with uncertainty.
2. **Root cause ranked by measured effect.** The RCA agent's hypotheses are re-ranked by how often each edit flips the outcome.
3. **Ground-truth oracle.** Success is checked in code against Era's simulated company data, not by an LLM judge.
4. **Shared failure memory.** Verified root causes are remembered per workspace and recalled on the next failure.

| # | Assumption | If wrong |
| --- | --- | --- |
| 1 | Deadline is Oct 25, 11:59 PM ET; [Devpost](https://build-north.devpost.com/) shows Oct 26 00:00 EDT, the same instant. | None. |
| 2 | Devpost lists the video as optional, up to 4 minutes. You set under 2 minutes; this plan keeps that. | None. |
| 3 | You can attend Demo Day in person in Toronto on Oct 29; top 10 are announced Oct 26. | Confirm before submitting. |
| 4 | Hours available: \~2.5 tonight, \~9 Thu, \~9 Fri, \~12 Sat, \~10 Sun. | Classes or shifts: keep block order and done-criteria, shift clock times. |
| 5 | Era early access works and you can create a company with Zendesk and Salesforce simulators. | Use a JSON fixture company with the same schema; do not claim the Eon category. |
| 6 | You can get a SurrealDB Agent Memory API key (public page still shows a waitlist). | Store patterns in a SurrealDB table; do not claim the Agent Memory category. |
| 7 | Models: `claude-haiku-5-5` for demo agents, `claude-sonnet-5-5` for the RCA agent. | Swap to Sonnet for agents if Haiku is too erratic; costs rise. |
| 8 | Render Starter ($7/month) for the API service, since free services sleep after 15 minutes idle and take about a minute to wake. | Free tier plus a keep-warm ping, with the risk noted. |
| 9 | Product name stays AgentTrace, but PyPI already has `agent-trace` packages. | Publish the SDK as `agenttrace-sdk`, or rename before submission. |

## Architecture

One FastAPI service holds the core (ingest, workflow runner, replay engine, experiment runner, RCA agent). SurrealDB stores the trace and fork graph, Agent Memory stores verified failure patterns, and a Next.js UI behind Clerk drives it. Only forked suffixes call Claude and Era live.

&#91;embedded content: AgentTrace architecture · 2 Render services, 5 external platforms\]

The API is the only component that calls Claude or Era, and it does so only for steps after a fork point; everything before the fork is read back from SurrealDB.

### Components

| Component | Tech | Responsibility |
| --- | --- | --- |
| Recorder SDK | Python package in `sdk/` | `trace_run()` context; wraps `anthropic.messages.create` and `@tool` functions; snapshots workflow state after each node; redacts before sending. |
| Workflow runner | Python, inside the API | Executes registered workflows node by node from a state snapshot. Same code path for record and replay. |
| Ingest and query API | FastAPI | `POST /v1/runs`, `POST /v1/runs/{id}/steps` (workspace API key); `GET` endpoints (Clerk JWT); SSE at `/v1/experiments/{id}/events`. |
| Replay engine | FastAPI module | Builds a fork: recorded prefix from the DB, edit applied, suffix re-run live. |
| Experiment runner | asyncio tasks, concurrency 3 | Runs control and treatment arms N times each, scores each run with the oracle, writes results. |
| RCA agent | `claude-sonnet-5-5`, forced tool call | Ranks suspect steps, proposes edits, optionally verifies them with small experiments. |
| Trace store | SurrealDB Cloud | Runs, steps, experiments as records; steps and forks as graph edges. |
| Pattern memory | SurrealDB Agent Memory | `remember` verified root causes; `recall` similar ones into the RCA prompt; `forget` on deletion. |
| UI | Next.js + Clerk | Runs list, run view, fork panel, experiment grid, RCA panel. |
| Hosting | Render, one `render.yaml` | `web` (Next.js) and `api` (FastAPI) web services. |

### Data model

Records plus graph edges. Text fields cap at 32 KB; anything longer is stored truncated with a sha256 of the full value.

```
-- records
workspace   { clerk_org_id, name, retention_days, created_at }
api_key     { workspace, prefix, sha256, created_by, revoked_at }
workflow    { workspace, name, version, code_hash, oracle_name }
run         { workspace, workflow, kind: 'recorded'|'fork', status,
              outcome: 'pass'|'fail'|'error', oracle_detail,
              tokens_in, tokens_out, started_at, ended_at }
step        { run, idx, agent, kind: 'llm'|'tool',
              origin: 'recorded'|'replayed'|'edited'|'live',
              model, params, input, output,
              tool_name, tool_args, tool_result, side_effect,
              state_after, reads: [key], writes: [key],
              content_hash, tokens, latency_ms, redactions: [] }
experiment  { workspace, parent_run, fork_idx, edit_mode: 'output'|'input',
              edit_patch, n, control: {pass, total}, treatment: {pass, total},
              fisher_p, status, created_by }
rca_report  { run, candidates: [{ step_idx, confidence, hypothesis,
              evidence, proposed_edit }], verified_by: [experiment], verdict_idx }
audit       { workspace, actor, action, target, at }

-- graph edges (RELATE)
run  ->has_step->    step
step ->next->        step
run  ->forked_from-> run    { at_idx, experiment, arm: 'control'|'treatment' }
experiment ->tested-> run
```

### Replay and fork semantics

Recorded steps replay exactly; forked steps re-run live. AgentTrace never calls the live suffix deterministic; it measures it.

| Segment | Steps | Source | Tokens |
| --- | --- | --- | --- |
| Prefix | 1 to k−1 | Recorded outputs; tools are not re-called | 0 |
| Fork point, edit-output mode (must-have) | k | Your edited output replaces the recorded one; step not re-run | 0 |
| Fork point, edit-input mode (nice-to-have) | k | Edited prompt, params or tool args; step re-runs live | live |
| Suffix | k+1 to end | Live Claude calls and live read-only tool calls | live |

- **State contract.** Nodes are pure functions of `(state, llm, tools)`. The runner restores `state_after` from step k−1 (or the edited step k), then runs the rest. The SDK records `reads` and `writes` keys so the RCA agent can trace data lineage.
- **Control vs treatment.** Same fork point, N live suffixes each; control has no edit. Effect = treatment rate minus control rate. A control arm is what turns a replay into evidence.
- **Statistics shown.** `k/N` per arm plus a Fisher exact p-value. 0/5 vs 4/5 gives p ≈ 0.048; the Wilson 95% intervals (\[0, 0.43\] and \[0.38, 0.96\]) still overlap, so the UI labels it "directional evidence, N=5". Use N=8 for the hero experiment if budget allows.
- **Side effects.** Tools declare `side_effect`. Side-effecting tools are blocked in live suffixes unless a mock is registered. Demo tools are read-only.
- **Model pinning.** Live steps use the recorded model id and params. If that model is unavailable, the experiment refuses to run instead of silently swapping.

### Root-cause agent

The agent proposes; experiments decide.

1. **Compact.** One-line summary per step (agent, kind, tokens, key output). Full input and output only for steps on the data-lineage path to the failing oracle field, found by walking `writes` → `reads` backwards. Budget about 20k tokens.
2. **Recall.** Query Agent Memory with the oracle failure and workflow name; inject the top 3 past patterns with provenance (run id, date, measured delta).
3. **Hypothesize.** `claude-sonnet-5-5` must call `report_candidates`: up to 3 items of `{step_idx, confidence, hypothesis, evidence_quotes, proposed_edit{mode, patch}}`. Schema-validated; one retry on invalid output.
4. **Verify (nice-to-have).** For the top 2 candidates, run control and treatment at N=3. Re-rank by measured delta; verdict needs treatment ≥ 2/3 and a positive delta.
5. **Remember.** On a verified verdict, write a redacted one-paragraph pattern to Agent Memory, scoped `ws/{id}/workflow/{name}`, labelled with failure class and agent role.

## Scope

The smallest version that still demos well: one seeded failing run, a run view, one edit-output fork with N=5 control vs treatment and a live result card, an RCA panel that ranks the planner first, behind Clerk, live on Render. Everything else is earned after that works on the live URL.

### Must-have (the demoable core)

- [ ] Recorder SDK: Anthropic call wrapper, `@tool` wrapper, state snapshots, redaction before send
- [ ] Demo workflow with a planted failure and a code oracle (Section 4)
- [ ] SurrealDB trace store: runs, steps, `has_step`, `next`, `forked_from` edges
- [ ] Run view: agent-lane timeline, step inspector (prompt, tool payload, state diff)
- [ ] Edit-output fork + experiment runner: control and treatment, N ≤ 8, concurrency 3
- [ ] Live experiment grid (polling every 1.5 s is fine) and result card with k/N and Fisher p
- [ ] RCA agent v1: ranked candidates with evidence, no auto-verify
- [ ] Clerk sign-in, orgs as workspaces, workspace filter on every query
- [ ] Redaction, per-experiment token cap, per-user daily cap
- [ ] Deployed on Render; seeded public demo workspace so judges see results without spending

### Nice-to-have, in priority order

1. Agent Memory failure patterns with a "Seen before" chip (needed for the SurrealDB Agent Memory category)
2. Era generalization benchmark: original vs patched workflow on 5 Era tasks (strengthens the Eon category)
3. RCA auto-verify: top 2 hypotheses at N=3, re-ranked by measured delta
4. Decoy experiment at the critic step (the "obvious" fix) for the demo
5. Fork tree view and parent-vs-fork step diff
6. Edit-input mode (edit prompt or tool args, step re-runs live)
7. SSE instead of polling

### Cut list (not built this week)

- RAG Triage stretch module. Only start it if every must-have and nice-to-have 1–4 are live by Sat 17:00. Realistically: cut, and mention it as roadmap.
- Framework adapters (LangGraph, CrewAI, OpenAI Agents SDK) and OpenTelemetry import
- Customer-hosted replay worker (documented as the production path only)
- Streaming capture, multi-provider LLMs, local models
- Team invites and roles beyond Clerk org defaults, billing, mobile
- Anything that needs local Docker infra beyond a single API container on your 8 GB M1

## Day-by-day plan

The order is: unblock access and deploy tonight, make the engine work Thursday, make it visible and authenticated Friday, deepen sponsors and security Saturday, ship Sunday. Each day ends with a cut rule; apply it at the stated time without negotiating.

### Wed Oct 21 — access and skeleton (22:30–01:00)

| Time | Block | Done when |
| --- | --- | --- |
| 22:30–23:00 | Accounts and keys: Anthropic, Clerk app, Render, SurrealDB Cloud, Agent Memory, Era console (install CLI, create company with Zendesk + Salesforce) | All keys in `.env` (gitignored), or a written access request posted in the hackathon Discord for each one missing |
| 23:00–00:15 | Monorepo: `api/` (FastAPI + `sdk/`), `web/` (Next.js), `render.yaml`. Deploy hello-world for both | Two Render URLs return 200; `api /health` reports DB reachable |
| 00:15–01:00 | SurrealDB schema script + Pydantic models for run, step, experiment | Script creates tables, inserts a fake run with 3 steps and edges, reads it back |

**Cut rule:** if either deploy is not green by 01:00, it is the first block Thursday and the RCA block moves to Saturday.

### Thu Oct 22 — engine (09:00–21:30)

| Time | Block | Done when |
| --- | --- | --- |
| 09:00–11:00 | Recorder SDK: `trace_run()`, Anthropic wrapper, `@tool(side_effect=False)`, state snapshots with reads/writes, redaction hook | Unit test records 3 steps with inputs, outputs, tokens, and a redacted fake API key |
| 11:00–13:30 | Demo workflow (Section 4) on Era or fixtures, plus the oracle | Good prompt passes ≥ 4/5 runs; planted bug fails 3/3 |
| 14:30–16:30 | Ingest API + SurrealDB writes + `GET /runs/{id}` | Recorded failing run retrievable with all steps in order |
| 16:30–18:30 | Replay engine: load run, restore state at k, apply output edit, run suffix live | One fork from the planner step with the fix passes the oracle |
| 19:30–21:30 | Experiment runner: control + treatment, asyncio concurrency 3, 429 backoff, Fisher p | One API call returns e.g. control 0/5, treatment 4/5, all 10 runs stored with `forked_from` edges |

**Cut rule:** if the replay engine is not passing by 21:30, drop the critic loop from the workflow (3 agents, not 4) and freeze edit-input mode permanently.

### Fri Oct 23 — visible and authenticated (09:00–21:30)

| Time | Block | Done when |
| --- | --- | --- |
| 09:00–10:30 | Clerk in Next.js (sign-in, org switcher); FastAPI verifies Clerk JWT via JWKS; workspace id taken only from the token | Logged-out call gets 401; a test proves org A cannot read org B's run |
| 10:30–13:30 | Run view: agent-lane timeline, step inspector, state diff, red/green outcome | Seeded failing run renders from the deployed API |
| 14:30–17:00 | Fork panel (edit output in a JSON/text editor, choose N) + live grid + result card | From the browser, N=5 fills 10 tiles and shows the result card |
| 17:00–19:00 | RCA agent v1 + panel | On the demo run, planner ranked #1 in at least 2 of 3 tries |
| 20:00–21:30 | Full deploy: env vars, API on Starter, seeded demo workspace, smoke test | Full flow works on the live URL from a fresh browser |

**Cut rule:** if the live URL cannot complete one experiment by 21:30, Saturday 09:00–11:00 goes to deploy fixes, Era benchmark is cut, and auto-verify is cut.

### Sat Oct 24 — sponsors, security, polish (09:00–22:00)

| Time | Block | Done when |
| --- | --- | --- |
| 09:00–11:00 | Agent Memory: `remember` on verified verdicts, `recall` into the RCA prompt, "Seen before" chip with provenance | A second failing run shows the recalled pattern and its source run |
| 11:00–12:30 | RCA auto-verify (top 2 at N=3) | Auto-verdict matches the manual hero experiment |
| 13:30–15:00 | Era generalization benchmark: original vs patched workflow on 5 Era tasks | Table of pass counts stored and shown on the experiment page |
| 15:00–17:00 | Security: redaction tests, API key hashing, caps, rate limits, audit log, delete-run cascade incl. Agent Memory `forget` | Tests pass; a fake email and key in a prompt are stored as `[REDACTED:…]` |
| 17:00–19:00 | UI polish: decoy critic experiment, fork tree, diff view, empty and loading states | Walk-through from sign-in to result card has no dead ends |
| 20:00–22:00 | Feature freeze. Pre-run and store the hero experiments. Video dry run. README draft | Hero result stored; dry-run video under 2:00 |

**Cut rule:** Agent Memory not working by 11:30 → table-backed patterns, drop that category claim. More than 2 hours behind at 15:00 → cut fork tree, diff view and the Era benchmark, keep security.

### Sun Oct 25 — ship (09:00–18:00, buffer to 23:59)

| Time | Block | Done when |
| --- | --- | --- |
| 09:00–11:00 | Bug bash on the live URL with a fresh Clerk account; phone-width check | No blocking bug in the demo path |
| 11:00–13:00 | Record and edit the video (Section 5) | Final cut under 2:00, uploaded, link opens without login |
| 14:00–16:00 | Devpost write-up, README, architecture image, prior-work disclosure | Every item in the submission checklist ticked except "submitted" |
| 16:00–17:00 | Tag `v0.1.0`, secrets scan (gitleaks), repo public, final deploy | Scan clean; live URL serves the tagged commit |
| 17:00–18:00 | Submit on Devpost | Confirmation page captured |

**Cut rule:** no new features after 09:00. If the video is not done by 15:00, record one take of the hero flow with voice-over and stop editing.

## Sample workflow: Renewal Risk Brief

A 4-agent workflow (planner → researcher → writer ⇄ critic) writes a renewal-risk brief for one customer account from Era's simulated Zendesk and Salesforce. The bug is planted at step 1 but only shows up at step 6, and the oracle fails at the end, so the demo shows a failure that surfaces far from its cause.

**User story.** A customer-success team asks: "Before the renewal call, how risky is account X?" The brief must report open support tickets, open pipeline and a risk level.

**The planted bug.** A teammate "reduced noise" in the planner's system prompt and added: *Only count tickets with status solved when judging support load.* The recorded planner output therefore contains `"ticket_filter": {"status": ["solved"]}`. Every downstream agent behaves sensibly given that plan, and the brief reports 0 open tickets.

| Step | Agent | Kind | What it does | In the failing run |
| --- | --- | --- | --- | --- |
| 1 | Planner | llm | Turns the request into a JSON plan: account, ticket filter, pipeline filter, sections | **Root cause:** filter is `["solved"]` |
| 2 | Researcher | llm | Chooses tool calls from the plan | Follows the plan faithfully |
| 3 | Researcher | tool | `zendesk.search_tickets(org, status)` | Returns only solved tickets |
| 4 | Researcher | tool | `salesforce.list_opportunities(account, open_only=True)` | Correct |
| 5 | Researcher | llm | Summarizes findings into state | "No open support issues" |
| 6 | Writer | llm | Drafts the brief with a JSON footer `{open_tickets, open_pipeline_usd, risk}` | **Symptom:** `open_tickets: 0`, `risk: low` |
| 7 | Critic | llm | Approves or requests one revision | Asks for ticket ids to be cited |
| 8 | Writer | llm | Revises | Same wrong numbers |
| 9 | Critic | llm | Approves (max 2 revision rounds) | Approves |

**Oracle (code, no LLM judge).** Pass if `open_tickets` equals ground truth, `open_pipeline_usd` is within 1% of ground truth, and the critic loop ends within 2 revisions. Ground truth comes from Era's answer key if your company has one for this question; otherwise a deterministic script queries Era's simulated APIs directly. Either way, the Era data is fixed, so the truth is exact.

**Three experiments for the demo.**

| Experiment | Fork at | Edit (output mode) | Expected |
| --- | --- | --- | --- |
| Decoy: "make the critic stricter" | Step 7 | Critic output becomes "Revise: verify the open-ticket count against the raw data" | \~0/5, because the data never contained open tickets |
| Control | Step 1 | None | 0/5 |
| Treatment | Step 1 | `status: ["new", "open", "pending", "hold"]` | \~4/5 to 5/5; the miss comes from writer arithmetic or a critic loop overrun |

**Making it reliable.**

- Choose the account with a script: at least 3 open tickets and at least 1 open opportunity, so the wrong answer is visibly wrong.
- Pin `claude-haiku-5-5`, temperature 0.7 for all agents, and record params on every step.
- Record the failing run 3 times and keep the cleanest trace as the seeded demo run.
- Run the hero experiments 3 times on Saturday. If treatment drops below 3/5 in any run, tighten the writer's footer instructions before recording; never edit the numbers shown.
- If Era is unavailable, swap in `fixtures/company.json` with the same Zendesk and Salesforce shapes; the workflow code does not change.

## Demo script (1:55)

Seven shots, one idea each: the failure is deep, the obvious fix fails, the real fix is proven with a control arm. Pre-run the experiments Saturday night and show the stored results; speed-ups are labelled on screen.

| Shot | Time | On screen | Voice-over |
| --- | --- | --- | --- |
| 1 | 0:00–0:08 | Seeded run page: 9 steps in agent lanes, red FAIL badge, oracle detail | "This four-agent workflow wrote a renewal brief that says zero open tickets. It's wrong, and it failed nine steps deep." |
| 2 | 0:08–0:20 | Click step 6 (writer); footer `open_tickets: 0` highlighted next to the oracle's expected value | "The obvious suspect is the writer. A tracer lets you see this. It doesn't let you test it." |
| 3 | 0:20–0:38 | Click Find root cause. RCA panel: #1 step 1 planner (ticket filter), #2 step 7 critic. "Seen before" chip with source run | "The root-cause agent, running on Claude, follows the data back to the planner's ticket filter, and recalls a similar verified failure from this workspace's memory in SurrealDB." |
| 4 | 0:38–0:55 | Decoy fork at step 7, stricter critic, N=5. Tiles fill (label: sped up 4×). Result 0/5 | "Hypotheses are cheap, so we test them. Make the critic stricter and rerun five times: zero of five." |
| 5 | 0:55–1:10 | Overlay: recorded prefix vs live suffix. Then a redaction badge on a step and the Clerk workspace switcher | "Steps before the fork replay exactly from the recording. Everything after reruns live against Era's simulated company, so we measure outcomes instead of claiming determinism. Workspaces are isolated, and secrets are redacted before a trace leaves your process." |
| 6 | 1:10–1:35 | Fork at step 1, edit the filter (diff visible), launch control and treatment, N=5 each. 10 tiles fill (sped up 4×) | "Now the planner. Same fork point twice: a control arm with no edit, a treatment arm with the fixed filter. Each brief is checked in code against Era's ground truth, not an LLM's opinion." |
| 7 | 1:35–1:55 | Result card: Control 0/5 → Treatment 4/5, Fisher p ≈ 0.05, "directional, N=5". Hold | "Zero of five to four of five. That's causal evidence the planner broke this run, and the fix is now remembered for the next one. AgentTrace." |

**Production notes.**

- Record at 1440×900, browser zoom 110%, light theme, notifications off.
- Record voice-over separately and cut video to it; total under 1:58.
- The numbers on screen are the stored results. If the hero run came out 5/5, the script says 5/5.
- Upload unlisted to YouTube; test the link in a logged-out window.

## Sponsor integration checklist

Four sponsors do real work; Render hosts. Devpost says category judges look for evidence that the platform materially shaped the build, so every row names a screenshot or file a judge can check. Google Cloud and Expo are deliberately unused (no mobile app, hosting is on Render).

| Sponsor | What you build with it | Evidence in the write-up | Category prize |
| --- | --- | --- | --- |
| Anthropic | Demo agents on `claude-haiku-5-5`; RCA agent on `claude-sonnet-5-5` with a forced `report_candidates` tool call and schema validation | Link to `api/rca/agent.py` and the tool schema; screenshot of the RCA panel; tokens per experiment from the result card | None (Best Overall credits) |
| SurrealDB | Trace and fork graph in SurrealDB Cloud via `RELATE` edges; Agent Memory `remember` on verified verdicts, `recall` into the RCA prompt, `forget` on run deletion, scopes per workspace | `schema.surql`; the SurrealQL query that returns a fork tree; screenshot of the "Seen before" chip with provenance; one paragraph on why memory changes the RCA ranking | Best Use of SurrealDB Agent Memory |
| Clerk | Next.js sign-in, organizations as workspaces, admin vs member roles; FastAPI verifies Clerk session JWTs via JWKS; workspace id comes only from the token | `middleware.ts`, `api/auth.py`, the cross-org isolation test; screenshot of the org switcher | Best Use of Clerk |
| Eon (Era) | Simulated company (Zendesk + Salesforce) as the demo workflow's tool environment; exact ground truth for the oracle; 5-task generalization benchmark of original vs patched workflow | Era company config (industry, size, systems); benchmark table; one paragraph on why exact ground truth beats an LLM judge for causal claims | Best Use of Eon |
| Render | `web` and `api` web services from `render.yaml`, health checks, env groups, API on Starter | Live URL; `render.yaml` link; note on why Starter (no 15-minute sleep) | None (sponsor, hosting) |

**Before claiming a category, confirm:**

- [ ] Agent Memory recall visibly changes the RCA output on the second failing run
- [ ] Era supplies both the tool data and the ground truth, not just a mention
- [ ] Clerk org isolation test is in the repo and passing
- [ ] Anthropic model ids in the write-up match the code

## Risk register

The two risks most likely to cost the win are a judge saying "this already exists" and a demo number that does not reproduce; both are handled by honesty and pre-run evidence, not more features.

| # | Risk | Likelihood / impact | Mitigation | Fallback |
| --- | --- | --- | --- | --- |
| 1 | Prior art: Rewind (fork, replay, `rewind fix`, LLM-judge scoring), LangGraph time travel (fork from checkpoint), plus tracing platforms LangSmith, Langfuse and Phoenix | High / High | Name them in the write-up. Claim only the four differentiators in the summary: control-arm experiments, effect-ranked root cause, ground-truth oracle, shared failure memory. Position as complementary to tracers | If a judge pushes, show the decoy: a single replay plus a judge would not separate 0/5 from 4/5 without a control arm |
| 2 | Overclaiming determinism | Medium / High | Fixed wording everywhere: "recorded steps replay exactly; forked steps re-run live". UI labels each step's origin. Result card says "directional, N=5" | None needed; it is a copy rule |
| 3 | Hero result does not reproduce (treatment 2/5, or control 1/5) | Medium / High | Tune the writer footer by Fri; three Saturday dry runs; store the hero experiment and show it; N=8 if budget allows | Show the honest number and the decoy contrast; still a real effect |
| 4 | Anthropic cost and rate limits during N-run experiments | Medium / Medium | Haiku for agents; concurrency 3 with 429 backoff; hard cap per experiment (N ≤ 8, token ceiling) and per user per day; seeded results so judges need not spend | Disable live runs for anonymous viewers; seeded data still demos |
| 5 | Deploy failure or cold starts on Render | Medium / High | Deploy hello-world tonight; API on Starter so it never sleeps; `/health` checks DB and Anthropic key; experiments run as background tasks so requests return fast | Video plus seeded workspace; local `docker compose` instructions in README |
| 6 | Sponsor access: Era early access or Agent Memory key not ready | Medium / Medium | Request both tonight; ask in the hackathon Discord by Thu 10:00 | Fixture company and a SurrealDB patterns table; drop the affected category claim |
| 7 | Replay correctness: state not restorable, or a tool with side effects re-runs | Low / High | Pure-node contract; `side_effect` flag blocks live re-runs without a mock; demo tools are read-only; test that prefix steps make zero network calls | Restrict forks to the planner step for the demo |
| 8 | Solo scope creep and fatigue on an 8 GB M1 | High / Medium | Daily cut rules; feature freeze Sat 20:00; no local DB or models; RAG Triage on the cut list | Ship the smallest demoable version from the Scope section |

Before writing the comparison paragraph, open each tool's current docs and check claims about replay and fork; do not describe a competitor from memory.

## Security and ethics

Traces are the most sensitive data an AI team has (full prompts, tool payloads, customer records), so AgentTrace redacts before data leaves the process, isolates every workspace, and never lets the RCA agent act on its own.

### Sensitive prompts and payloads

- **Redact at the source.** The SDK redacts before sending: key-name denylist (`authorization`, `api_key`, `password`, `token`, `secret`, `cookie`), regex for API keys, bearer tokens, emails, phone numbers and card-like numbers. Each hit becomes `[REDACTED:type:hash8]`, so diffs still show when two values matched.
- **Configurable per workspace.** Extra patterns and an allowlist live in workspace settings; the API re-runs redaction on ingest as a second line.
- **Size limits.** 32 KB per field; longer values truncated with a sha256 of the original.
- **Retention.** Default 14 days; deleting a run cascades to steps, forks, experiments and the matching Agent Memory patterns via `forget`.
- **Memory holds summaries only.** Agent Memory receives a redacted one-paragraph pattern, never raw prompts or payloads.
- **Demo data is synthetic.** All customer records come from Era's generated company; no real personal data is used.

### Access control

- Clerk organizations are workspaces. The API takes `workspace_id` only from the verified JWT, never from the request body, and every SurrealDB query filters on it. A test proves cross-org reads fail.
- Roles: members view and fork; admins also delete runs, rotate ingest keys and change redaction rules.
- Ingest uses per-workspace API keys, shown once, stored as sha256, revocable.
- An audit record is written for every fork, edit, experiment launch and deletion (actor, time, target).
- Secrets live in Render env vars; the repo is scanned with gitleaks before it goes public.

### Guardrails on live replay and the RCA agent

- Forks only execute registered workflows; there is no endpoint that runs arbitrary user code.
- Side-effecting tools cannot run in a live suffix without a registered mock.
- Budget caps: N ≤ 8 per arm, a token ceiling per experiment, a daily cap per user.
- Trace content is treated as untrusted input to the RCA agent: it is wrapped in delimiters with an instruction to ignore embedded instructions, the agent has no tools that act, and its output must match a JSON schema.
- The RCA agent proposes edits; a person launches experiments. Auto-verify runs only within the budget caps and is logged.

### What AgentTrace does not do

- It does not claim deterministic replay of live steps.
- It does not apply fixes to production code or prompts.
- It does not train models on customer traces.
- It does not send traces anywhere except SurrealDB (storage) and Anthropic (RCA, which a workspace admin can turn off).
- It does not replace monitoring or alerting, and it holds no compliance certification.

## Submission

Everything goes on one Devpost project page by Oct 25, 11:59 PM ET; aim to press Submit by 18:00 and spend the buffer only on fixes.

### Checklist

- [ ] Registered on the Devpost hackathon page; project created as a draft by Saturday night
- [ ] Public GitHub repo, MIT license, README with setup, architecture image, `.env.example`
- [ ] Gitleaks scan clean; no keys in history
- [ ] Live link works in a logged-out browser; a "View demo workspace" path needs no spend
- [ ] Demo video under 2:00, unlisted link opens without login
- [ ] Write-up names each partner platform and how it was used (Section 6 evidence)
- [ ] Prior-work disclosure: the idea was chosen this week (earlier shortlist had other ideas); list any templates (create-next-app, Clerk quickstart, FastAPI template)
- [ ] Related work named: Rewind, LangGraph time travel, LangSmith, Langfuse, Phoenix
- [ ] Team: you, solo
- [ ] Category prizes selected only where Section 6 confirms are ticked
- [ ] Demo Day availability on Oct 29 confirmed
- [ ] Tagged release `v0.1.0` matches the deployed commit

### Devpost write-up outline

1. **Tagline (one line).** "A debugger for multi-agent systems that proves which step broke your run."
2. **The problem (3 sentences).** One AI engineer, a research → write → critique workflow that fails deep; traces show what happened, not what caused it; re-running is noisy and expensive.
3. **What it does.** Record, inspect, fork any step, run N live replays with a control arm, root-cause agent, failure memory. Embed the 0/5 → 4/5 result card.
4. **How it works.** Architecture diagram; replay semantics in two lines ("recorded steps replay exactly; forked steps re-run live"); why a control arm and a code oracle matter.
5. **Partner platforms.** One short paragraph each for Anthropic, SurrealDB Agent Memory, Clerk, Era by Eon, Render, with the evidence links.
6. **Security and ethics.** Redaction at source, workspace isolation, guardrails, what it does not do.
7. **Related work and what is new.** Rewind and LangGraph time travel do fork and replay; AgentTrace adds control-arm experiments, effect-ranked root cause, ground-truth oracles and shared failure memory.
8. **Path to production.** Customer-hosted replay worker so prompts and tools stay in the customer's infra; framework adapters; CI gate that blocks a deploy when a known failure pattern's experiment regresses. RAG Triage as the next module.
9. **Built this week / prior work.** What existed before Oct 16 (nothing, or name it) and what was built during Build Week.
10. **Challenges and what's next.** Honest limits: N=5 is directional; only registered workflows replay.

### Sources

As of Oct 21, 2026.

- [Build North on Devpost](https://build-north.devpost.com/): deadline, submission items, judging criteria, category rules, Demo Day
- [Build North on Luma](https://luma.com/build-north): free Era early access, virtual format, in-person Demo Day
- [Rewind (agentoptics/rewind)](https://github.com/agentoptics/rewind): prior art for fork and replay
- [LangGraph time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel): checkpoint replay and fork
- [Meet Era (Eon blog)](https://www.eon.io/blog/era-build-and-test-ai-agents): simulated companies, APIs, MCP servers, answer keys
- [SurrealDB Agent Memory Python SDK](https://surrealdb.com/docs/agent-memory/integrations/sdks/python): `remember`, `recall`, scopes
- [What is SurrealDB Agent Memory](https://surrealdb.com/docs/agent-memory/welcome/what-is-surrealdb-agent-memory): contexts, what it is not
- [Render pricing explained (third party)](https://livemy.app/blog/render-pricing): free tier sleep and Starter pricing; confirm on Render's own pricing page
