from typing import Any

from app.runner.run import END

MAX_DRAFTS = 3  # the first draft plus 2 revision rounds


def next_node(state: dict[str, Any]) -> str:
    """Pick the next node from the state alone, so a fork can resume from any restored state.

    planner -> researcher -> writer -> critic -> (approve: END | revise: writer ...).
    The counters are node-run counts: `drafts` is written by the writer, `reviews` by the critic.
    """
    if "plan" not in state:
        return "planner"
    if "findings" not in state:
        return "researcher"
    drafts, reviews = state.get("drafts", 0), state.get("reviews", 0)
    if drafts == 0:
        return "writer"
    if reviews < drafts:
        return "critic"
    if state.get("verdict") == "approve" or drafts >= MAX_DRAFTS:
        return END
    return "writer"
