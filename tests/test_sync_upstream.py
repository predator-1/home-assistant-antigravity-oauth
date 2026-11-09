import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sync_upstream", ROOT / "scripts" / "sync_upstream.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

PLUGIN_TS = """
export const CLI_VERSION = "9.9.9" as const;
export const DEFAULT_ENDPOINTS = Object.freeze({
  usageUrl: "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary",
  chatCompletionsUrl:
    "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse",
  clientId: "CLIENT",
  clientSecret: "SECRET",
  loopbackRedirectUri: "http://localhost:51121/oauth-callback"
});
export const OAUTH_SCOPES = [
  "https://www.googleapis.com/auth/b",
  "https://www.googleapis.com/auth/a"
].join(" ");
"""


def test_parse_plugin_hides_secret():
    parsed = sync.parse_plugin(PLUGIN_TS)
    assert parsed["cli_version"] == "9.9.9"
    assert parsed["scopes"] == ["https://www.googleapis.com/auth/a", "https://www.googleapis.com/auth/b"]
    assert parsed["api_hosts"] == ["daily-cloudcode-pa.googleapis.com"]
    assert "SECRET" not in str(parsed)


def test_own_constants_parse_and_verdicts():
    ours = sync.parse_const(sync.CONST.read_text())
    assert ours["redirect_uri"] == "http://localhost:51121/oauth-callback"
    assert len(ours["scopes"]) == 5
    assert sync.compare(ours, ours) == (0, {})
    assert sync.compare({**ours, "cli_version": "9.9.9"}, ours)[0] == 10
    verdict, changed = sync.compare({**ours, "cli_version": "9.9.9", "client_id": "other"}, ours)
    assert verdict == 20
    assert set(changed) == {"cli_version", "client_id"}
