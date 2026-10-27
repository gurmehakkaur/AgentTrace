"""The four agents. Each node is `async def node(state, llm, tools) -> state updates`: no
globals and no hidden I/O, so a run can resume from any recorded `state_after`."""

import json
from typing import Any

from agenttrace_sdk import node

from app.config import DEMO_EFFORT, DEMO_MODEL
from app.workflows.renewal_brief.prompts import CRITIC_SYSTEM, RESEARCHER_SYSTEM, WRITER_SYSTEM


def parse_json(text: str) -> dict[str, Any]:
    """The first {...} object in an LLM reply (models sometimes wrap JSON in prose or fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    return json.loads(text[start : end + 1])


async def _ask(llm: Any, system: str, user: str, max_tokens: int) -> str:
    # max_tokens includes hidden thinking tokens, so keep generous headroom or replies get cut off.
    reply = await llm.create(
        model=DEMO_MODEL,
        max_tokens=max_tokens,
        output_config={"effort": DEMO_EFFORT},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # Haiku 5.5 thinks by default, so a reply may open with a thinking block.
    return next(b.text for b in reply.content if b.type == "text")


def build_nodes(planner_system: str) -> dict[str, Any]:
    """Nodes keyed by name. The planner prompt is a parameter so the same code records the
    good run and the planted-bug run."""

    @node("planner", reads=["request"], writes=["plan"])
    async def planner(state, llm, tools):
        return {"plan": parse_json(await _ask(llm, planner_system, state["request"], 4000))}

    @node("researcher", reads=["plan"], writes=["findings"])
    async def researcher(state, llm, tools):
        plan = state["plan"]
        statuses = plan["ticket_filter"]["status"]
        if isinstance(statuses, str):
            statuses = [statuses]
        tickets = await tools.zendesk_search_tickets(plan["account_id"], statuses)
        pipeline = await tools.salesforce_list_open_opportunities(plan["account_id"])
        summary = await _ask(
            llm, RESEARCHER_SYSTEM, json.dumps({"tickets": tickets, "pipeline": pipeline}), 4000
        )
        return {"findings": {"tickets": tickets, "pipeline": pipeline, "summary": summary}}

    @node(
        "writer",
        reads=["request", "findings", "draft", "feedback", "drafts"],
        writes=["draft", "drafts"],
    )
    async def writer(state, llm, tools):
        parts = [f"Request: {state['request']}", "Findings:\n" + json.dumps(state["findings"])]
        if state.get("draft") and state.get("feedback"):
            parts += [f"Previous draft:\n{state['draft']}", f"Reviewer feedback: {state['feedback']}"]
        draft = await _ask(llm, WRITER_SYSTEM, "\n\n".join(parts), 8000)
        return {"draft": draft, "drafts": state.get("drafts", 0) + 1}

    @node(
        "critic",
        reads=["findings", "draft", "reviews"],
        writes=["verdict", "feedback", "reviews"],
    )
    async def critic(state, llm, tools):
        user = f"Findings:\n{json.dumps(state['findings'])}\n\nBrief:\n{state['draft']}"
        review = parse_json(await _ask(llm, CRITIC_SYSTEM, user, 4000))
        if review.get("verdict") not in ("approve", "revise"):
            raise ValueError(f"critic verdict must be approve or revise: {review!r}")
        return {
            "verdict": review["verdict"],
            "feedback": str(review.get("feedback", "")),
            "reviews": state.get("reviews", 0) + 1,
        }

    return {"planner": planner, "researcher": researcher, "writer": writer, "critic": critic}
