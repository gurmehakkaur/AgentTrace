"""Redaction: replace secrets and PII in a COPY of a payload before it leaves the process.

Two layers, applied in `redact()`:
  1. Key-name denylist: a dict key like `authorization` or `x-api-key` redacts its whole value.
  2. Regexes over every string: API-key shapes, bearer tokens, emails, card-like numbers, phones.

Each hit becomes `[REDACTED:<type>:<first 8 hex of sha256 of the original>]`, so two equal
secrets get the same marker and a diff still shows they matched.

Only the stored copy is redacted. The live state passed between nodes is never touched, and
the structure of a payload (keys, lists, non-secret values like a `status` filter) is kept.

The patterns are heuristics: `123-456-7890` looks like a phone number even if it is a part
code, and a key-name hit redacts the whole value.
"""

import hashlib
import json
import re
from typing import Any

# Matched against the normalised key: exact, or as a trailing `_<word>` ("access_token").
# Not a substring match, so `max_tokens` and `token_count` are NOT redacted.
KEY_DENYLIST = ("authorization", "api_key", "password", "token", "secret", "cookie")

MARKER_PREFIX = "[REDACTED:"

_PATTERNS = (
    ("api_key", re.compile(
        r"\b(?:sk-ant-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{20,}|at_live_[A-Za-z0-9]{8,}"
        r"|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"
    )),
    # Needs a digit in the token so prose like "bearer authorization" is left alone.
    ("bearer", re.compile(r"(?i)\bBearer\s+(?=[A-Za-z0-9._~+/=-]*\d)[A-Za-z0-9._~+/=-]{10,}")),
    # The lookbehind makes a match start only at the beginning of a run of address characters.
    # Without it a long run with no "@" is rescanned from every position: quadratic time, which
    # a hostile or buggy sender could use to pin the server (40,000 chars took 1.8 s, 100 KB 11 s).
    ("email", re.compile(
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
    )),
    ("card", re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")),
    # Needs separators ("415-555-0123"), so bare 10-digit ids are not treated as phones.
    ("phone", re.compile(
        r"(?<!\w)(?:\+?\d{1,3}[\s.-])?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?!\d)"
    )),
)


def _marker(kind: str, original: str) -> str:
    return f"{MARKER_PREFIX}{kind}:{hashlib.sha256(original.encode()).hexdigest()[:8]}]"


def _is_secret_key(key: str) -> bool:
    key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)  # apiKey -> api_Key
    norm = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return any(norm == w or norm.endswith("_" + w) for w in KEY_DENYLIST)


def _is_sensitive_value(value: Any) -> bool:
    if value is None or isinstance(value, bool) or value == "":
        return False
    return not (isinstance(value, str) and value.startswith(MARKER_PREFIX))


def _redact_string(text: str, path: str, found: list[dict[str, str]]) -> str:
    for kind, pattern in _PATTERNS:

        def repl(m: re.Match[str], kind: str = kind) -> str:
            found.append({"path": path, "type": kind})
            return _marker(kind, m.group(0))

        text = pattern.sub(repl, text)
    return text


def _walk(value: Any, path: str, found: list[dict[str, str]]) -> Any:
    if isinstance(value, str):
        return _redact_string(value, path, found)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(key, str) and _is_secret_key(key) and _is_sensitive_value(item):
                found.append({"path": child, "type": "secret"})
                original = item if isinstance(item, str) else json.dumps(item, sort_keys=True)
                out[key] = _marker("secret", original)
            else:
                out[key] = _walk(item, child, found)
        return out
    if isinstance(value, (list, tuple)):
        return [_walk(item, f"{path}[{i}]", found) for i, item in enumerate(value)]
    return value


def redact(obj: Any) -> tuple[Any, list[dict[str, str]]]:
    """Return (redacted copy of obj, redactions). Never mutates obj.

    Each redaction is {"path": "messages[0].content", "type": "email"}. Idempotent, so the API
    can run it again on ingest.
    """
    found: list[dict[str, str]] = []
    return _walk(obj, "", found), found
