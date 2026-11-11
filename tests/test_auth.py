import base64
import hashlib

import pytest

from custom_components.antigravity.api import auth
from custom_components.antigravity.api.errors import AuthError


def test_pkce_session():
    pkce = auth.new_pkce_session()
    digest = hashlib.sha256(pkce.verifier.encode()).digest()
    assert pkce.challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert 43 <= len(pkce.verifier) <= 128
    url = pkce.authorize_url
    assert "code_challenge_method=S256" in url
    assert f"state={pkce.state}" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A51121%2Foauth-callback" in url


def test_parse_callback_input():
    url = "http://localhost:51121/oauth-callback?state=s1&iss=https://accounts.google.com&code=4/abc&scope=x"
    assert auth.parse_callback_input(f"  {url}\n", "s1") == "4/abc"
    assert auth.parse_callback_input("4/raw-code", "s1") == "4/raw-code"
    assert auth.parse_callback_input("code=4/q&state=s1", "s1") == "4/q"
    with pytest.raises(AuthError, match="state mismatch"):
        auth.parse_callback_input(url, "other")
    with pytest.raises(AuthError, match="denied"):
        auth.parse_callback_input("http://localhost:51121/oauth-callback?error=access_denied", "s1")
    with pytest.raises(AuthError):
        auth.parse_callback_input("   ", "s1")


def test_plan_name_prefers_paid_tier():
    # Trimmed loadCodeAssist response of a Google AI Pro account (2026-11-11).
    data = {
        "currentTier": {"id": "free-tier", "name": "Antigravity"},
        "paidTier": {"id": "g1-pro-tier", "name": "Google AI Pro"},
        "allowedTiers": [{"id": "free-tier"}, {"id": "standard-tier"}],
    }
    assert auth.plan_name(data) == "Google AI Pro"
    assert auth.plan_name({**data, "paidTier": {"id": "g1-ultra-tier"}}) == "g1-ultra-tier"
    assert auth.plan_name({"currentTier": data["currentTier"]}) == "Antigravity"
    assert auth.plan_name({"currentTier": {"id": "free-tier", "name": " "}}) == "free-tier"
    assert auth.plan_name({}) is None
