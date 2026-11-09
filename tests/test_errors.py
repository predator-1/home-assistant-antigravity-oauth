"""Vectors ported from openclaw-antigravity-oauth test/quota-reset-delay.test.ts and acceptance 429 cases."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.antigravity.api.errors import (
    RateLimitKind,
    classify_429,
    error_summary,
    parse_reset_delay,
)

NOW = datetime(2026, 11, 7, 20, 0, 0, tzinfo=UTC)


def quota_error(delay, metadata=None, reason="QUOTA_EXHAUSTED", domain="cloudcode.googleapis.com"):
    return json.dumps(
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota fixture",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": reason,
                        "domain": domain,
                        "metadata": {"quotaResetDelay": delay, **(metadata or {})},
                    }
                ],
            }
        }
    )


@pytest.mark.parametrize(
    ("delay", "ms"),
    [
        ("1h", 3_600_000),
        ("2m", 120_000),
        ("3s", 3_000),
        ("1h2m3.5s", 3_723_500),
        ("123.456ms", 123.456),
        ("1.5s", 1_500),
        ("1ms", 1),
        ("1h2m3s4.5ms", 3_723_004.5),
        ("1.5h", 5_400_000),
        (".5m", 30_000),
        ("1.s", 1_000),
        ("1s250ms", 1_250),
    ],
)
def test_valid_reset_delay(delay, ms):
    info = classify_429(quota_error(delay), now=NOW)
    assert info.kind is RateLimitKind.TERMINAL_QUOTA
    assert info.reason == "QUOTA_EXHAUSTED"
    assert info.domain == "cloudcode.googleapis.com"
    assert info.reset_at == NOW + timedelta(milliseconds=ms)
    assert info.retry_delay is None


@pytest.mark.parametrize(
    "delay",
    [
        "",
        " ",
        "garbage",
        "garbage1h",
        "1hgarbage",
        "1h2",
        "1e3s",
        "1.2.3s",
        "1h 2m",
        "123.456mss",
        "3us",
        "-1s",
        "+1s",
        "NaNs",
        "Infinitys",
        "0s",
        None,
        1234,
        {},
        True,
        "999999999999999999h",
        "9" * 400 + "s",
    ],
)
def test_invalid_reset_delay_omits_reset(delay):
    info = classify_429(quota_error(delay), now=NOW)
    assert info.kind is RateLimitKind.TERMINAL_QUOTA
    assert info.reset_at is None


def test_timestamp_wins_over_delay():
    stamp = "2026-11-08T01:02:03Z"
    for delay in ("1.5s", "garbage1h"):
        info = classify_429(quota_error(delay, {"quotaResetTimeStamp": stamp}), now=NOW)
        assert info.reset_at == datetime(2026, 11, 8, 1, 2, 3, tzinfo=UTC)


def test_transient_uses_retry_after_header():
    info = classify_429(quota_error("1h", reason="RATE_LIMIT_EXCEEDED"), {"retry-after": "2"})
    assert info.kind is RateLimitKind.TRANSIENT
    assert info.reset_at is None
    assert info.retry_delay == 2


def test_other_domain_ignored():
    info = classify_429(quota_error("1h", domain="storage.googleapis.com"))
    assert info.kind is RateLimitKind.UNCLASSIFIED
    assert info.reset_at is None


def test_capacity_with_retry_info():
    body = json.dumps(
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "busy",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "MODEL_CAPACITY_EXHAUSTED",
                        "domain": "cloudaicompanion.googleapis.com",
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3.5s"},
                ],
            }
        }
    )
    info = classify_429(body)
    assert info.kind is RateLimitKind.TRANSIENT
    assert info.reason == "MODEL_CAPACITY_EXHAUSTED"
    assert info.retry_delay == 3.5


def test_plain_text_retry_in():
    info = classify_429("Too many requests. Please retry in 4s")
    assert info.kind is RateLimitKind.UNCLASSIFIED
    assert info.retry_delay == 4


def test_parse_reset_delay_direct():
    assert parse_reset_delay("1m30s") == 90
    assert parse_reset_delay("0s") is None


def test_error_summary():
    assert error_summary('{"error":{"status":"NOT_FOUND","message":"gone"}}') == "NOT_FOUND: gone"
    assert error_summary("<html>oops</html>") == "<html>oops</html>"
