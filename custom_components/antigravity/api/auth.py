"""OAuth sign-in, refresh and eligibility for the Antigravity subscription.

Port of openclaw-antigravity-oauth src/auth.ts (docs/auth.md). No Home Assistant imports.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .. import const
from .errors import AuthError, InvalidGrantError, NotEligibleError


@dataclass(frozen=True)
class PkceSession:
    verifier: str
    challenge: str
    state: str

    @property
    def authorize_url(self) -> str:
        params = {
            "client_id": const.CLIENT_ID,
            "response_type": "code",
            "redirect_uri": const.REDIRECT_URI,
            "scope": const.OAUTH_SCOPES,
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
            "state": self.state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{const.AUTH_URL}?{urlencode(params)}"


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class Eligibility:
    project_id: str
    email: str | None
    tier: str | None


def new_pkce_session() -> PkceSession:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkceSession(verifier=verifier, challenge=challenge, state=secrets.token_urlsafe(24))


def parse_callback_input(raw: str, expected_state: str) -> str:
    """Return the authorization code from a pasted redirect URL or a bare code."""
    text = raw.strip()
    if not text:
        raise AuthError("Nothing was pasted")
    if "://" not in text and "code=" not in text:
        return text
    query = parse_qs(urlparse(text).query if "://" in text else text.lstrip("?"))
    if error := query.get("error"):
        raise AuthError(f"Authentication denied: {error[0]}")
    code = (query.get("code") or [""])[0].strip()
    if not code:
        raise AuthError("Redirect URL is missing the 'code' query parameter")
    state = (query.get("state") or [""])[0].strip()
    if state and state != expected_state:
        raise AuthError("OAuth state mismatch")
    return code


async def _token_request(session: aiohttp.ClientSession, data: dict[str, str]) -> dict[str, Any]:
    data = {"client_id": const.CLIENT_ID, "client_secret": const.CLIENT_SECRET, **data}
    async with session.post(const.TOKEN_URL, data=data, headers={"Accept": "application/json"}) as resp:
        body: dict[str, Any] = await resp.json(content_type=None)
        if resp.status >= 400 or "error" in body:
            error = body.get("error", f"HTTP {resp.status}")
            if error == "invalid_grant":
                raise InvalidGrantError("OAuth refresh token is invalid or revoked [error: invalid_grant]")
            raise AuthError(f"Token request failed: {error}")
        return body


async def exchange_code(session: aiohttp.ClientSession, pkce: PkceSession, code: str) -> Tokens:
    body = await _token_request(
        session,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": const.REDIRECT_URI,
            "code_verifier": pkce.verifier,
        },
    )
    if not body.get("access_token") or not body.get("refresh_token"):
        raise AuthError("Authentication failed: incomplete token response")
    return Tokens(body["access_token"], body["refresh_token"], int(body.get("expires_in", 3600)))


async def refresh(session: aiohttp.ClientSession, refresh_token: str) -> Tokens:
    body = await _token_request(session, {"grant_type": "refresh_token", "refresh_token": refresh_token})
    if not body.get("access_token"):
        raise AuthError("Refresh failed: incomplete token response")
    return Tokens(
        body["access_token"],
        body.get("refresh_token", refresh_token),
        int(body.get("expires_in", 3600)),
    )


async def request_device_code(session: aiohttp.ClientSession) -> tuple[int, dict[str, Any]]:
    """RFC 8628 device authorization request; returns (status, body)."""
    async with session.post(
        const.DEVICE_CODE_URL,
        data={"client_id": const.CLIENT_ID, "scope": const.OAUTH_SCOPES},
        headers={"Accept": "application/json"},
    ) as resp:
        return resp.status, await resp.json(content_type=None)


def _project_id(raw: Any) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict) and isinstance(raw.get("id"), str) and raw["id"].strip():
        return raw["id"].strip()
    return None


async def check_eligibility(session: aiohttp.ClientSession, access_token: str) -> Eligibility:
    """loadCodeAssist; raises NotEligibleError when the account has no tier."""
    async with session.post(
        const.LOAD_CODE_ASSIST_URL,
        json={"metadata": {"ideType": "ANTIGRAVITY"}},
        headers=const.build_api_headers(access_token),
    ) as resp:
        if resp.status in (401, 403):
            raise NotEligibleError
        if resp.status >= 400:
            raise AuthError(f"loadCodeAssist failed: HTTP {resp.status}")
        data: dict[str, Any] = await resp.json(content_type=None)

    if data.get("eligible") is False:
        raise NotEligibleError
    project_id = _project_id(data.get("cloudaicompanionProject"))
    tier = ((data.get("currentTier") or {}).get("id") or "").strip() or None
    if data.get("eligible") is not True and not project_id and not tier and not data.get("allowedTiers"):
        raise NotEligibleError

    email = None
    async with session.get(const.USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}) as resp:
        if resp.status == 200:
            email = ((await resp.json(content_type=None)).get("email") or "").strip() or None
    return Eligibility(project_id=project_id or const.DEFAULT_PROJECT_ID, email=email, tier=tier)
