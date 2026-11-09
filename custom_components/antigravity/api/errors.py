"""Errors and Google RPC error classification.

Port of openclaw-antigravity-oauth src/turn.ts (`extractErrorSummary`, `classifyGoogleRpc429`,
`parseQuotaResetDelayMs`); rules in its docs/protocol.md#errors.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any


class AntigravityError(Exception):
    """Base error for upstream failures."""


class AuthError(AntigravityError):
    """Sign-in, refresh or an authenticated call failed; the user must sign in again."""


class NotEligibleError(AuthError):
    """The account has no Antigravity subscription tier."""

    def __init__(self) -> None:
        super().__init__("subscription not eligible")


class InvalidGrantError(AuthError):
    """The refresh token is revoked or expired."""


class UnknownModelError(AntigravityError):
    """Upstream does not know the model (HTTP 404) or it is not in the catalog."""


class QuotaExhaustedError(AntigravityError):
    """A subscription window is empty (terminal 429 QUOTA_EXHAUSTED)."""

    def __init__(self, summary: str, reset_at: datetime | None = None) -> None:
        super().__init__(f"Subscription quota exceeded: {summary}")
        self.reset_at = reset_at


class RateLimitError(AntigravityError):
    """Transient rate or capacity limit that survived the bounded retries."""


class NativeToolRefusedError(AntigravityError):
    """The model called a tool Home Assistant did not offer (docs/architecture.md §4)."""

    def __init__(self, name: str) -> None:
        super().__init__(f"native tool refused: {name}")
        self.name = name


class UpstreamError(AntigravityError):
    """Any other non-success reply."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def error_summary(body: str) -> str:
    """Reduce a Google JSON error to `<STATUS>: <message>`, else the first 200 chars."""
    try:
        error = json.loads(body).get("error")
    except ValueError, AttributeError:
        error = None
    if isinstance(error, dict) and error.get("message"):
        return f"{error.get('status', 'ERROR')}: {error['message']}"
    return body[:200].strip()


class RateLimitKind(StrEnum):
    TERMINAL_QUOTA = "terminal_quota"
    TRANSIENT = "transient_rate_limit"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class RateLimitInfo:
    kind: RateLimitKind
    summary: str
    reason: str | None = None
    domain: str | None = None
    retry_delay: float | None = None
    """Seconds."""
    reset_at: datetime | None = None


_DELAY_TOKEN = re.compile(r"(\d+(?:\.\d*)?|\.\d+)(ms|h|m|s)")
_DELAY_SCALE = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
_RETRY_IN = re.compile(r"(?:Please )?retry in\s+([0-9.]+)\s*s", re.IGNORECASE)
_QUOTA_DOMAIN = re.compile(r"cloudcode|cloudaicompanion", re.IGNORECASE)


def parse_reset_delay(value: Any) -> float | None:
    """Parse a Go-style duration (`1h2m3.5s`, `250ms`) into positive seconds, else None."""
    if not isinstance(value, str) or not value:
        return None
    total = 0.0
    pos = 0
    while pos < len(value):
        match = _DELAY_TOKEN.match(value, pos)
        if not match:
            return None
        total += float(match[1]) * _DELAY_SCALE[match[2]]
        if not math.isfinite(total):
            return None
        pos = match.end()
    return total if total > 0 else None


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _positive_seconds(value: Any) -> float | None:
    try:
        seconds = float(value)
    except TypeError, ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _retry_info_delay(value: Any) -> float | None:
    if isinstance(value, str):
        return _positive_seconds(value.removesuffix("s").removesuffix("S"))
    if isinstance(value, int | float):
        return _positive_seconds(value)
    if isinstance(value, dict):
        seconds = float(value.get("seconds") or 0) + float(value.get("nanos") or 0) / 1e9
        return seconds if seconds > 0 else None
    return None


def classify_429(body: str, headers: Mapping[str, str] | None = None, now: datetime | None = None) -> RateLimitInfo:
    """Classify a 429 body: QUOTA_EXHAUSTED is terminal, rate/capacity limits are transient.

    Only `ErrorInfo` from a cloudcode/cloudaicompanion domain counts.
    """
    summary = error_summary(body)
    header_delay = _positive_seconds((headers or {}).get("retry-after"))
    try:
        parsed = json.loads(body)
    except ValueError:
        retry = _RETRY_IN.search(body)
        delay = (_positive_seconds(retry[1]) if retry else None) or header_delay
        return RateLimitInfo(RateLimitKind.UNCLASSIFIED, summary, retry_delay=delay)

    error = parsed.get("error", parsed) if isinstance(parsed, dict) else {}
    details = error.get("details") if isinstance(error, dict) else None
    kind = RateLimitKind.UNCLASSIFIED
    reason = domain = None
    reset_at: datetime | None = None
    retry_delay: float | None = None

    for item in details if isinstance(details, list) else []:
        if not isinstance(item, dict):
            continue
        type_name = str(item.get("@type", ""))
        if type_name.endswith("google.rpc.ErrorInfo") or (item.get("reason") and item.get("domain")):
            item_domain = str(item.get("domain") or "").strip()
            if item_domain and not _QUOTA_DOMAIN.search(item_domain):
                continue
            item_reason = str(item.get("reason") or "").strip()
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if item_reason == "QUOTA_EXHAUSTED":
                kind, reason, domain = RateLimitKind.TERMINAL_QUOTA, item_reason, item_domain
                if stamp := metadata.get("quotaResetTimeStamp"):
                    reset_at = _parse_timestamp(str(stamp))
                elif (delay := parse_reset_delay(metadata.get("quotaResetDelay"))) is not None:
                    try:
                        reset_at = (now or datetime.now(UTC)) + timedelta(seconds=delay)
                    except OverflowError:
                        reset_at = None
            elif item_reason in ("RATE_LIMIT_EXCEEDED", "MODEL_CAPACITY_EXHAUSTED"):
                kind, reason, domain = RateLimitKind.TRANSIENT, item_reason, item_domain
        if "retryDelay" in item:
            retry_delay = _retry_info_delay(item["retryDelay"]) or retry_delay

    if retry_delay is None and isinstance(error, dict) and (retry := _RETRY_IN.search(str(error.get("message", "")))):
        retry_delay = _positive_seconds(retry[1])
    return RateLimitInfo(kind, summary, reason, domain, retry_delay or header_delay, reset_at)
