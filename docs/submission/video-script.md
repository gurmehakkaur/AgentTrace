# Video script: AgentTrace (1:56 version)

*A 4-minute version with three slides first is in `video-script-4min.md`.*

**Story in one line:** *Your agents already run somewhere. AgentTrace sits on top, tells you when a run is wrong, tests which step broke it, and proves whether the fix works.*

Everything in this script is real and in the repo. Anything sped up is labelled "sped up" on screen. Nobody says "deterministic".

## Screens you need open (set these up before you record)

| Screen | What it is |
| --- | --- |
| **A. Browser, tab 1** | `https://agenttrace-web.onrender.com/demo` (public, signed out). Zoom 110%, 1440×900. |
| **B. Browser, tab 2** | `/runs` **signed in** as yourself, in your organisation (the Gantt with both workflows). |
| **C. Terminal** | In `api/`, font large, one tab, nothing else visible. Command ready: `.venv/bin/python scripts/record_demo.py` |
| **D. Slack** | The alerts channel, scrolled to the bottom, notifications off. |
| **E. Browser, tab 3** | `/demo/worker` and `/demo/terminal` (from the Examples dropdown). |

## Timeline

| # | Time | Screen to show | What to say (voice-over) | On-screen text | Real or edited |
| --- | --- | --- | --- | --- | --- |
| 1 | 0:00 – 0:09 | **A.** `/demo` top: the headline *"The brief says 0 open tickets, not 5."* and the line of four agents. | "Four AI agents wrote a renewal brief that says zero open tickets. The real number is five. It's wrong, and nothing in the trace says why." | none | real |
| 2 | 0:09 – 0:22 | **A.** Click the **Planner** node: show what went in and out. Point to **"Likely cause 80%"** and the downstream nodes marked **"Affected by it"**. | "A tracer would blame the writer. AgentTrace follows the data upstream. The planner filtered the tickets to 'solved', so everything after it was built on nothing. A root-cause agent marks it, and a small test supports it." | "Supported by a small test" | real |
| 3 | 0:22 – 0:44 | **C.** Run `record_demo.py`; the line `run …: FAIL` prints. **Cut to B.** The new row appears on the Gantt in its own colour. **Cut to D.** The Slack failure message arrives. | "This is a live run from our own pipeline. It lands on the sheet as it finishes, judged by a check I wrote in code, and the failure goes straight to Slack with the reason and a link. Every run has its own colour, and forks hang under the run they came from." | "live" in the corner during the terminal part | real (cut the waiting) |
| 4 | 0:44 – 1:08 | **A.** The decoy experiment (0/5 → 0/5) for 4 seconds, then the hero experiment: the 8 + 8 squares, then the result card. | "Hypotheses are cheap, so we test them. Making the critic stricter changes nothing: zero of five, either way. Now the planner. Same fork point twice: one run without the fix, one with it. Steps before the fork replay exactly; everything after runs live, so we repeat it. Zero of eight becomes eight of eight." | "0/8 → 8/8 · Fisher p = 0.00016 · directional" | stored results; say "saved" if asked |
| 5 | 1:08 – 1:20 | **D.** The Slack **"Fork finished"** message. | "When a fork finishes, Slack gets one message: what changed, how many runs came out right, and a p-value, marked directional. Small N shows direction, not proof." | none | real *(test it before recording)* |
| 6 | 1:20 – 1:42 | **E.** `/demo` → **Examples** dropdown → *Forking your own agents* (show the worker code, then the result). Then *From your terminal and CI* (the gate: exit 0, then exit 1). | "It sits on top of the agents you already run. LangGraph and plain Python loops connect in a few lines, anything that emits OpenTelemetry works through a collector, and a worker next to your code lets you fork your own agents. In CI, a gate re-runs a proven fix and fails the build if it stops working. More adapters are on the way." | "LangGraph · Python loops · OpenTelemetry" | real |
| 7 | 1:42 – 1:56 | **A.** The benchmark line (0/15 vs 13/15), then the partner names. | "Zero of fifteen to thirteen of fifteen across five other accounts. Directional, but measured. Built on Claude, SurrealDB with Agent Memory, Clerk, Era and Render. This is AgentTrace." | "AgentTrace" and the partner names | stored results |

About 290 spoken words. If you run long, cut shot 4's decoy first, then shorten shot 2.

## The Slack messages (what the viewer should see)

**Failed run:**
```
Renewal brief gave a wrong answer.
Check <your check's name>: <the reason your check gave>
Open the run
```

**Fork finished:**
```
Fork finished on renewal_brief: changing the planner.
Without the change 0 of 5 right, with it 5 of 5. The change fixed it.
Directional only (p = 0.008): live steps are sampled.
Open it
```
Record both from your real channel. If a message doesn't arrive, don't fake it: show the **Send a test** result on the Connect page instead.

## Recording order (shortest path)

1. Warm both Render services and wait for a reply.
2. Record **C → B → D** in one go (shot 3), because it needs the live run.
3. Record shots 1, 2, 4, 6 and 7 in the browser.
4. Fork once for real (N=3, sped up) if you want a live fork on camera. Say "sped up" on screen when you cut.
5. Record shot 5 after a fork finishes, from the same Slack channel.
6. Voice-over last, in one take per shot.

## Checks before you export

- [ ] No notification pop-ups, no secrets on screen (never show `.env` or a key).
- [ ] Every sped-up part says "sped up".
- [ ] Nobody says "deterministic", "any harness" or "everything".
- [ ] 1:56 or less. Upload **unlisted**, then open the link **logged out**.

## If something goes wrong

| Problem | Do this |
| --- | --- |
| The live API is slow | Record shot 3 without the live part and say nothing about "live". Use the saved results. |
| Slack doesn't show the message | Show the Send-a-test result instead; don't edit one in. |
| `/runs` looks empty | You're in the wrong organisation. The workspace is your Clerk organisation. |
| You run over time | Drop the decoy in shot 4, then trim shot 2. |

## Answers if someone asks

- *Does it work with any harness?* "It's built to sit on top of whichever one you run. LangGraph and any Python loop work today, anything that emits OpenTelemetry works through a collector, and adapters for more harnesses are in progress."
- *Is it deterministic?* "No. Recorded steps replay exactly; forked steps run live and are sampled, which is why we repeat them and say directional."
- *Why trust N = 8?* "You shouldn't treat it as proof. It shows direction with a p-value, and we say so everywhere."
