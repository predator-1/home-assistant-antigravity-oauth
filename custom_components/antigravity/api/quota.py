"""Subscription usage windows from `retrieveUserQuotaSummary`.

Payload shape: docs/protocol.md#quota. Percent rules match openclaw-antigravity-oauth
docs/features.md#usage-and-quota.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

Window = Literal["weekly", "5h"]


@dataclass(frozen=True)
class QuotaWindow:
    key: str
    """Stable upstream `bucketId`, e.g. `gemini-weekly`."""
    group: str
    """Group display name, e.g. `Gemini Models`."""
    window: Window
    remaining_fraction: float | None
    reset_at: datetime | None

    @property
    def remaining_percent(self) -> int | None:
        """What the Antigravity app shows: `ceil(remainingFraction * 100)`."""
        if self.remaining_fraction is None:
            return None
        return max(0, min(100, math.ceil(self.remaining_fraction * 100)))

    @property
    def used_percent(self) -> int | None:
        if self.remaining_fraction is None:
            return None
        return max(0, min(100, math.floor((1 - self.remaining_fraction) * 100)))


def _window(bucket: Mapping[str, Any]) -> Window:
    for value in (bucket.get("window"), bucket.get("bucketId"), bucket.get("displayName")):
        text = str(value or "").lower()
        if any(k in text for k in ("5h", "five", "rolling")):
            return "5h"
        if "week" in text:
            return "weekly"
    return "weekly"


def _reset_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_quota_summary(payload: Mapping[str, Any]) -> list[QuotaWindow]:
    windows: list[QuotaWindow] = []
    seen: set[str] = set()
    for group in payload.get("groups") or []:
        if not isinstance(group, Mapping):
            continue
        group_name = str(group.get("displayName") or "").strip()
        for bucket in group.get("buckets") or []:
            if not isinstance(bucket, Mapping):
                continue
            window = _window(bucket)
            key = str(bucket.get("bucketId") or f"{group_name}-{window}").strip()
            if key in seen:
                continue
            seen.add(key)
            fraction = bucket.get("remainingFraction")
            if bucket.get("disabled") is True:
                fraction = 0.0
            windows.append(
                QuotaWindow(
                    key=key,
                    group=group_name or key,
                    window=window,
                    remaining_fraction=float(fraction) if isinstance(fraction, int | float) else None,
                    reset_at=_reset_at(bucket.get("resetTime")),
                )
            )
    return windows
