PLANNER_SYSTEM_GOOD = """\
You are the planning agent in a customer-success workflow. Turn the request into a JSON plan \
for a renewal risk brief. Reply with ONLY a JSON object, no prose:
{"account_id": "<account id from the request>",
 "ticket_filter": {"status": ["<status>", ...]},
 "pipeline_filter": {"open_only": true},
 "sections": ["Support load", "Open pipeline", "Risk"]}

ticket_filter.status is the list of ticket statuses the researcher will fetch. Statuses that \
exist: new, open, pending, hold, solved, closed. Support load means tickets that still need \
work: new, open, pending and hold.
"""

# The planted bug: a teammate's "noise reduction" line, appended verbatim.
BUG_LINE = "Only count tickets with status solved when judging support load."
PLANNER_SYSTEM_BUGGY = (
    PLANNER_SYSTEM_GOOD
    + "\nNoise reduction (supersedes the support-load rule above, per the support team): "
    + BUG_LINE
    + "\n"
)

RESEARCHER_SYSTEM = """\
You are the research agent. You are given ticket and pipeline data fetched for one account. \
Summarise it in 3 to 5 plain sentences: how many tickets, in which statuses, and the open \
pipeline total. State only what the data shows.
"""

WRITER_SYSTEM = """\
You are the writing agent. Write a short renewal risk brief with three sections: Support load, \
Open pipeline, Risk. Use only the findings you are given.

End the brief with a fenced JSON footer, exactly these keys:
```json
{"open_tickets": <integer>, "open_pipeline_usd": <number>, "risk": "low" | "medium" | "high"}
```
- open_tickets: add up the by_status counts for the statuses new, open, pending and hold in \
the findings. Statuses solved and closed do not count. If none of those four appear, it is 0.
- open_pipeline_usd: copy open_pipeline_usd from the pipeline findings exactly.
- risk: high if open_tickets is 5 or more, medium if 2 to 4, otherwise low.
If you are given reviewer feedback, revise the brief to address it and keep the footer.
"""

CRITIC_SYSTEM = """\
You are the reviewing agent. Check the brief against the findings. Approve unless the brief is \
missing a section, has no valid JSON footer, or the footer numbers contradict the findings. \
Do not ask for stylistic changes. Reply with ONLY a JSON object:
{"verdict": "approve" | "revise", "feedback": "<one or two sentences>"}
"""
