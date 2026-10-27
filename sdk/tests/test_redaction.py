"""Phase 2: redaction patterns. Includes the hand-written strings the guide asks you to try,
and one deliberate false positive so the limits are visible, not hidden."""

import re

import pytest

from agenttrace_sdk import redact

FAKE_ANTHROPIC_KEY = "sk-ant-api03-AbCdEf0123456789_xYz-QQQQ"
MARKER = r"\[REDACTED:{kind}:[0-9a-f]{{8}}\]"


def marker(kind: str) -> re.Pattern[str]:
    return re.compile(MARKER.format(kind=kind))


def test_api_key_shapes_are_redacted_anywhere_in_a_string():
    text = f"use key {FAKE_ANTHROPIC_KEY} and ghp_{'a1' * 12} for deploy"
    out, found = redact(text)
    assert FAKE_ANTHROPIC_KEY not in out
    assert "ghp_" not in out
    assert marker("api_key").search(out)
    assert {f["type"] for f in found} == {"api_key"}


def test_equal_secrets_get_equal_markers_and_different_secrets_differ():
    a1, _ = redact({"note": f"k={FAKE_ANTHROPIC_KEY}"})
    a2, _ = redact({"other": f"again {FAKE_ANTHROPIC_KEY}"})
    b, _ = redact({"note": "k=sk-ant-api03-DIFFERENT0123456789zz"})
    pull = lambda d: re.search(r"\[REDACTED:api_key:[0-9a-f]{8}\]", str(d)).group(0)  # noqa: E731
    assert pull(a1) == pull(a2)
    assert pull(a1) != pull(b)


@pytest.mark.parametrize(
    "key",
    ["authorization", "Authorization", "api_key", "apiKey", "x-api-key",
     "password", "db_password", "access_token", "client_secret", "Set-Cookie"],
)
def test_denylisted_key_names_redact_the_whole_value(key):
    out, found = redact({key: "hunter2-not-a-regex-shape"})
    assert marker("secret").fullmatch(out[key])
    assert found[0]["path"] == key


def test_key_hit_redacts_a_nested_value_wholesale():
    out, _ = redact({"authorization": {"scheme": "basic", "value": "dXNlcjpwYXNz"}})
    assert marker("secret").fullmatch(out["authorization"])


@pytest.mark.parametrize("key", ["max_tokens", "input_tokens", "tokens_out", "token_count", "temperature"])
def test_token_counters_and_params_are_not_mistaken_for_secrets(key):
    out, found = redact({key: 1000})
    assert out == {key: 1000}
    assert found == []


def test_empty_or_null_values_under_secret_keys_are_left_alone():
    out, found = redact({"password": "", "token": None, "secret": False})
    assert out == {"password": "", "token": None, "secret": False}
    assert found == []


def test_email_and_bearer():
    text = "mail jane.doe+x@example.co.uk; Authorization: Bearer abc123def456ghi789"
    out, found = redact(text)
    assert "jane.doe" not in out and "abc123def456" not in out
    assert {f["type"] for f in found} == {"email", "bearer"}


@pytest.mark.parametrize("phone", ["+1 415-555-0123", "(415) 555-0123", "415.555.0123", "415-555-0123"])
def test_phone_numbers_with_separators(phone):
    out, found = redact(f"call {phone} today")
    assert phone not in out
    assert found[0]["type"] == "phone"


def test_card_like_numbers_are_redacted():
    out, found = redact("card 4111 1111 1111 1111 ok")
    assert "4111" not in out and found[0]["type"] == "card"


@pytest.mark.parametrize(
    "benign",
    [
        "4155550123",  # bare 10 digits: ticket/account ids must survive
        "open_pipeline_usd: 1250000",
        "2026-10-22T09:31:00Z",
        "bearer of the bad news",
        "the bearer authorization header",
        "version 1.2.3",
    ],
)
def test_ordinary_text_and_numbers_survive(benign):
    out, found = redact(benign)
    assert out == benign and found == []


def test_known_false_positive_part_code_looks_like_a_phone_number():
    """Documented limit: separators make 123-456-7890 indistinguishable from a phone number."""
    out, found = redact("part 123-456-7890")
    assert found and found[0]["type"] == "phone"


def test_structure_and_non_secret_values_are_preserved_for_replay():
    args = {"org_id": "org_42", "statuses": ["new", "open", "pending", "hold"], "limit": 25, "flag": True}
    out, found = redact(args)
    assert out == args and found == []


def test_paths_point_at_the_exact_location():
    payload = {"messages": [{"role": "user", "content": "mail me at a@b.io"}], "n": 1}
    _, found = redact(payload)
    assert [f["path"] for f in found] == ["messages[0].content"]


def test_input_is_never_mutated():
    payload = {"messages": [{"content": f"key {FAKE_ANTHROPIC_KEY}"}], "password": "pw"}
    snapshot = {"messages": [{"content": f"key {FAKE_ANTHROPIC_KEY}"}], "password": "pw"}
    redact(payload)
    assert payload == snapshot


def test_redaction_is_idempotent_so_ingest_can_run_it_again():
    payload = {"password": "pw", "text": f"{FAKE_ANTHROPIC_KEY} jane@example.com 415-555-0123"}
    once, first = redact(payload)
    twice, second = redact(once)
    assert first and twice == once and second == []


@pytest.mark.parametrize(
    "text",
    [
        "z" * 200_000,
        "a." * 100_000,
        "1" * 200_000,
        "1 " * 100_000,
        "a@" * 100_000,
        "a@" + "b-" * 100_000,
        "sk-" + "a" * 200_000,
        "Bearer " + "a" * 200_000,
        "(" + "1" * 200_000,
        ("x" * 1000 + "@") * 200,
    ],
)
def test_redaction_time_is_linear_in_the_input_so_a_huge_field_cannot_pin_the_cpu(text):
    """Every pattern must be safe on adversarial long input. Before the email pattern got a
    lookbehind, 40,000 characters took 1.8 s and the cost quadrupled when the input doubled."""
    import time

    started = time.perf_counter()
    redact(text)
    assert time.perf_counter() - started < 1.0


def test_emails_are_still_found_after_the_performance_fix():
    for text in ("jane@acme.com", "mail: jane.doe+x@example.co.uk;", "x_jane-1@a.io", "(bob@corp.org)"):
        out, found = redact(text)
        assert found and found[0]["type"] == "email" and "@" not in out
