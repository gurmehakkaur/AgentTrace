# Video script, 4:00: three slides (1:00) then the live demo (3:00)

**Story in one line:** *Your agents already run somewhere. AgentTrace sits on top, tells you when a run is wrong, tests which step broke it, and proves whether the fix works.*

Everything here is real and in the repo. Anything sped up says "sped up" on screen. Nobody says "deterministic", "any harness" or "everything".

## Screens to set up before you record

| Screen | What it is |
| --- | --- |
| **S. Slides** | `https://agenttrace-web.onrender.com/demo/pitch` (or `http://localhost:3100/demo/pitch`). Press **F** for full screen, **→** for the next slide, **N** for speaker notes (leave notes off while recording). |
| **A. Browser, tab 1** | `/demo` (public, signed out). Zoom 110%, 1440×900. |
| **B. Browser, tab 2** | `/runs` **signed in**, in your organisation: the Gantt with both workflows. |
| **C. Terminal** | In `api/`, large font, one tab, command ready: `.venv/bin/python scripts/record_demo.py` |
| **D. Slack** | The alerts channel, scrolled to the bottom, notifications off. |
| **E. Browser, tab 3** | `/demo` → **Examples** dropdown, ready on *Forking your own agents*. |

## Part 1: the slides (0:00 – 1:00)

| Time | Slide | What to say | Notes |
| --- | --- | --- | --- |
| 0:00 – 0:12 | **1. AgentTrace** | "Hi, I'm *[your name]*. This is AgentTrace. It finds the step that broke your AI agents, and proves whether the fix works." | Stay on the slide, don't read the tagline aloud. |
| 0:12 – 0:38 | **2. Meet Maya** | "Meet Maya, an AI engineer. Her renewal-brief agents just told a customer there were zero open tickets. There were five. Her traces show what happened, not why. Re-running is noisy and costs tokens, so one lucky run proves nothing. And she can't move her whole team to a new framework." | Pause after "There were five." |
| 0:38 – 1:00 | **3. Our solution** | "AgentTrace records the run, follows the data back to the step that caused it, then tests the fix: fork that step, rerun everything after it live, with and without the change. Zero of eight becomes eight of eight. It sits on top of the harness she already uses, and tells her in Slack when something breaks." | The dots draw themselves in. Let the green row finish before you move on. |

Maya is a **composite persona**; the slide says so. Don't present her as a real customer.

## Part 2: the demo (1:00 – 4:00)

| Time | Screen | What to say | On-screen text | Real or edited |
| --- | --- | --- | --- | --- |
| 1:00 – 1:20 | **A.** `/demo` top: the headline and the line of four agents. Click **Planner**. Point to **"Likely cause 80%"** and the downstream nodes marked **"Affected by it"**. | "Back to Maya's problem. This is the real run, recorded. The writer says zero open tickets, but the writer is innocent. The planner filtered the tickets to 'solved', so everything after it worked from nothing. A root-cause agent marks it at eighty percent, and a small test supports that." | "Supported by a small test" | real |
| 1:20 – 1:55 | **C.** Run `record_demo.py` until it prints `FAIL`. **Cut to B.** The new row appears on the Gantt in its own colour. **Cut to D.** The Slack failure message arrives. | "Now a live run from our own pipeline. It lands on the sheet as it finishes. That's every run in the workspace by time, each in its own colour, with forks hanging under the run they came from. A check I wrote in code judged it wrong, and the failure goes straight to Slack with the reason and a link. That's the observability layer: it records any run it can reach, whether or not you can fork it." | "live" while the terminal runs | real (cut the waiting) |
| 1:55 – 2:35 | **A.** The decoy (0/5 → 0/5) for 5 s. Then the hero experiment: the squares fill (if you forked live, label it **sped up**), then the result card. | "Hypotheses are cheap, so we test them. Making the critic stricter changes nothing: zero of five, either way. Now the planner. Same fork point twice: a control with no change, a treatment with the fix. Steps before the fork replay exactly from the recording. Everything after runs live, so each side is repeated. Zero of eight becomes eight of eight, a Fisher p-value of 0.00016. Directional, not proof." | "0/8 → 8/8 · p = 0.00016 · directional" | stored results; if you fork live, "sped up" |
| 2:35 – 2:55 | **D.** The Slack **"Fork finished"** message. | "When a fork finishes, Slack gets one message: what changed, how many runs came out right with and without it, and the p-value, marked directional. Maya doesn't have to watch a dashboard." | none | real *(test it before recording)* |
| 2:55 – 3:35 | **E.** *Forking your own agents* (the worker code, then the result). Then *Keys, alerts and agents* (make a key for a worker, show the scopes). Then *From your terminal and CI* (the gate: exit 0, then exit 1). | "Maya's agents don't run on our server, so there's a worker. It runs next to her code, connects out only, and reruns her own agents from the fork point; AgentTrace counts the results. LangGraph and plain Python loops connect in a few lines, and anything that emits OpenTelemetry works through a collector. Keys say exactly what each caller may do. In CI, a gate reruns a proven fix against new code: exit zero when it holds, one when it doesn't. Adapters for more harnesses are in progress." | "LangGraph · Python loops · OpenTelemetry" | real |
| 3:35 – 3:50 | **A.** The benchmark card (0/15 vs 13/15), then back to `/demo/overview` for one second. | "What's real: the renewal brief, its experiments, and this whole flow, tested against a real database. What's sample: the support-triage workflow. And with small N, every result is directional." | "sample data" on the triage rows | real |
| 3:50 – 4:00 | **S.** Slide 1 again, or the partner names. | "Zero of fifteen to thirteen of fifteen across five other accounts. Built on Claude, SurrealDB, Clerk, Era and Render. This is AgentTrace." | "AgentTrace" | real |

About 540 spoken words in all. If you run long, shorten the 2:55 part first, then drop the decoy.

## Recording order (shortest path)

1. Warm both Render services and wait for a reply (open the site once).
2. Slides first, one take per slide.
3. Record **C → B → D** in one go (1:20 – 1:55): it needs the live run.
4. Record the browser shots (1:00, 1:55, 2:55, 3:35).
5. Fork once for real (N=3) if you want it live on camera. Label "sped up" when you cut.
6. After that fork finishes, record the Slack **"Fork finished"** message.
7. Voice-over last, one take per section.

## Slack messages the viewer should see

**Failed run**
```
Renewal brief gave a wrong answer.
Check <your check's name>: <the reason your check gave>
Open the run
```

**Fork finished**
```
Fork finished on renewal_brief: changing the planner.
Without the change 0 of 5 right, with it 5 of 5. The change fixed it.
Directional only (p = 0.008): live steps are sampled.
Open it
```
Record both from your real channel. If one doesn't arrive, don't edit one in: show the **Send a test** result on the Connect page.

## Before you export

- [ ] No notifications, no secrets on screen (never show `.env` or a key).
- [ ] Every sped-up part says "sped up". Maya is called a composite persona.
- [ ] 4:00 or less. Upload **unlisted**, then open the link **logged out**.

## If something goes wrong

| Problem | Do this |
| --- | --- |
| The live API is slow | Skip "live" in 1:20 – 1:55; use the saved results and say nothing about live. |
| Slack doesn't show the message | Show the Send-a-test result; don't fake the message. |
| `/runs` looks empty | You're in the wrong organisation. The workspace is your Clerk organisation. |
| A live fork takes too long | Use the stored hero experiment (0/8 → 8/8). |
| Over time | Drop the decoy, then trim the 2:55 part. |

## Answers if someone asks

- *Does it work with any harness?* "It's built to sit on top of whichever one you run. LangGraph and any Python loop work today, anything that emits OpenTelemetry works through a collector, and adapters for more harnesses are in progress."
- *Is it deterministic?* "No. Recorded steps replay exactly; forked steps run live and are sampled, which is why we repeat them and say directional."
- *Why trust N = 8?* "You shouldn't treat it as proof. It shows direction, with a p-value, and we say so everywhere."
