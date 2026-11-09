from datetime import UTC, datetime

from custom_components.antigravity.api.quota import QuotaWindow, parse_quota_summary


def test_windows(quota_payload):
    windows = parse_quota_summary(quota_payload)
    assert [(w.key, w.group, w.window, w.remaining_percent) for w in windows] == [
        ("gemini-weekly", "Gemini Models", "weekly", 68),
        ("gemini-5h", "Gemini Models", "5h", 95),
        ("3p-weekly", "Claude and GPT models", "weekly", 82),
        ("3p-5h", "Claude and GPT models", "5h", 100),
        ("gemini-argon-wtu-weekly", "Gemini 4 Argon", "weekly", 68),
    ]
    assert windows[0].reset_at == datetime(2026, 11, 14, 1, 0, 3, tzinfo=UTC)
    assert windows[0].used_percent == 32


def test_normalizes_enums_and_missing_values():
    windows = parse_quota_summary(
        {
            "groups": [
                {
                    "displayName": "G",
                    "buckets": [
                        {"window": "FIVE_HOUR"},
                        {"bucketId": "x", "window": "WEEKLY", "disabled": True, "remainingFraction": 0.5},
                    ],
                }
            ]
        }
    )
    assert windows == [
        QuotaWindow("G-5h", "G", "5h", None, None),
        QuotaWindow("x", "G", "weekly", 0.0, None),
    ]
    assert windows[0].remaining_percent is None
    assert windows[1].used_percent == 100
