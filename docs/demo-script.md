# Demo video script (under 2:00)

Rules: **the numbers on screen are the stored results.** Current stored results: decoy 0/5 → 0/5, hero 0/8 → 8/8 (p = 0.00016), auto-verify 0/3 → 3/3, benchmark 0/15 vs 13/15. Anything that is sample data (the support-triage workflow) is said to be sample data. Anything sped up is labelled on screen. Never call live steps deterministic.

## Before you record (30 minutes)

- Warm both Render services: open the site and the API health address, and wait for a response. The free plan sleeps for about a minute.
- Sign in as yourself in your organization. Open `/runs`. It should show the Gantt with both workflows. If anything looks wrong, fix that first.
- Slack: open the channel, press **Send a test** on Connect, and confirm it arrives. Then remove the notification pop-ups from your screen.
- Anthropic credits: check the balance and the spend limit. A live fork and the gate each use tokens (the headline experiment used about 63,000).
- Terminal: font large, one tab, in `api/`. Check `.env` has your key (do not show `.env` on screen).
- 1440×900, browser zoom 110%, notifications off, one browser window and one terminal side by side.
- Record in short takes, one per shot. Upload unlisted, then open the link logged out.

## The story in one line

*Your agents already run somewhere. AgentTrace sits on top, tells you when a run is wrong, tests which step broke it, and proves whether the fix works.*

## Shots

| Shot | Time | On screen | Voice-over |
| --- | --- | --- | --- |
| 1 | 0:00–0:10 | `/demo` top: "The brief says 0 open tickets, not 5." and the line of four agents | "This four-agent workflow wrote a renewal brief that says zero open tickets. The real number is five. It's wrong, and the cause is several steps upstream of the symptom." |
| 2 | 0:10–0:28 | **Live.** Terminal: `record_demo.py`. Cut to `/runs` signed in: the new row appears on the Gantt. Cut to Slack: the failure message arrives. | "Here's a run from our own system. It lands on the sheet as it finishes, judged by a check I wrote in code, and the failure goes straight to Slack. This connects to the harness you already run: a few lines for LangGraph or any Python loop, or OpenTelemetry traces through a collector." |
| 3 | 0:28–0:46 | Open the run. Planner marked "Likely cause 80%", next nodes "Affected by it"; "Supported by a small test" | "A root-cause agent follows the data back to the planner's ticket filter. A tracer would stop at the writer. It can't tell you the writer isn't the cause." |
| 4 | 0:46–0:58 | Decoy experiment: 5 + 5 tiles, 0/5 → 0/5 | "Hypotheses are cheap, so we test them. Make the critic stricter and rerun five times: zero of five, with or without the change." |
| 5 | 0:58–1:22 | Hero: select the planner, edit the filter, fork. Tiles fill in (label "sped up"). Result: 0/8 → 8/8, p = 0.00016, "directional" | "Now the planner. Same fork point twice: a control with no edit, and a treatment with the fixed filter. Steps before the fork replay exactly from the recording; everything after runs live, so we repeat it. Zero of eight to eight of eight, directional, not proof." |
| 6 | 1:22–1:42 | `/demo` Examples dropdown → "Forking your own agents", then the terminal block: `agenttrace gate` exits 0, then exits 1 | "For agents that run on your own system, a small worker next to your code runs them again, and the same numbers come back. And in CI, the gate re-runs a proven fix against new code and fails the build if it stops working. LangGraph works today; more adapters are on the way." |
| 7 | 1:42–1:56 | Result card held, then the benchmark line 0/15 vs 13/15, then the partner names | "Zero of fifteen to thirteen of fifteen across five other accounts. Directional, not proof, but measured. Built on Claude, SurrealDB with Agent Memory, Clerk, Era and Render. AgentTrace." |

Roughly 280 spoken words. If you run long, cut shot 4 first, then shorten shot 3.

## If something is slow or fails while recording

- A live fork takes a minute or two: record it once in full, then cut it and say "sped up" on screen.
- If the Slack message does not arrive: record shot 2 without it, and show the **Send a test** result instead. Do not fake the message.
- If `/runs` looks empty: check that you are signed in to the right organization (the workspace is your Clerk organization).
- Keep one clean full take as a fallback and submit it if the live API is slow on the day.

## Things to say if asked (Q&A)

- *Does it work with any harness?* "It's built to sit on top of whichever one you run. LangGraph and any Python loop work today, and anything that emits OpenTelemetry traces works through a collector. Adapters for CrewAI, the OpenAI Agents SDK and the Claude Agent SDK are in progress." (Say "works today" only for what is in the repo.)
- *Is it deterministic?* "No. Recorded steps replay exactly; forked steps run live and are sampled. That is why we repeat them and say directional."
- *Why trust the result with N = 8?* "You shouldn't treat it as proof. It shows direction, with a p-value, and we say so everywhere."
- *Where's your data?* "In SurrealDB. Secrets are redacted before they leave your process, and you can run the worker so your agents never leave your system."
- *What is sample data?* "The support-triage workflow in the examples. The renewal brief and its experiments are real runs."
