"""What live routes need to call Claude and the data tools. A FastAPI dependency so tests can
substitute fakes."""

from typing import Any

from anthropic import AsyncAnthropic

from app.workflows.renewal_brief.tools import make_tools


def get_runtime() -> tuple[Any, Any]:
    """(LLM client, tools). The SDK retries 429s; a higher ceiling than its default of 2 rides
    out rate limits."""
    return AsyncAnthropic(max_retries=5), make_tools()
