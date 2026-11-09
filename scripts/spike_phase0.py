"""Phase 0 spike: OAuth and streaming against the real upstream. Local only.

  python scripts/spike_phase0.py device-code      # does Google allow device code for this client?
  python scripts/spike_phase0.py login-url        # print the PKCE sign-in URL
  python scripts/spike_phase0.py login-finish URL # exchange the pasted redirect URL, check eligibility
  python scripts/spike_phase0.py refresh          # refresh the stored token
  python scripts/spike_phase0.py pong [MODEL [PROMPT [LEVEL]]]  # one streamed turn (uses quota)

State lives in .tmp/ (gitignored). Tokens are never printed.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.antigravity import const  # noqa: E402
from custom_components.antigravity.api import auth  # noqa: E402

TMP = ROOT / ".tmp"
PKCE_FILE = TMP / "spike-pkce.json"
TOKEN_FILE = TMP / "spike-token.json"


def _save(path: Path, data: dict) -> None:
    TMP.mkdir(exist_ok=True)
    path.write_text(json.dumps(data))
    path.chmod(0o600)


async def device_code(session: aiohttp.ClientSession) -> None:
    status, body = await auth.request_device_code(session)
    print(f"HTTP {status}")
    print({k: v for k, v in body.items() if k != "device_code"})


async def login_url(_: aiohttp.ClientSession) -> None:
    pkce = auth.new_pkce_session()
    _save(PKCE_FILE, pkce.__dict__)
    print(pkce.authorize_url)


async def login_finish(session: aiohttp.ClientSession, pasted: str) -> None:
    pkce = auth.PkceSession(**json.loads(PKCE_FILE.read_text()))
    code = auth.parse_callback_input(pasted, pkce.state)
    tokens = await auth.exchange_code(session, pkce, code)
    elig = await auth.check_eligibility(session, tokens.access_token)
    _save(
        TOKEN_FILE,
        {
            "access": tokens.access_token,
            "refresh": tokens.refresh_token,
            "expires": time.time() + tokens.expires_in,
            "project": elig.project_id,
        },
    )
    PKCE_FILE.unlink()
    print(
        f"signed in; tier={elig.tier} email={'yes' if elig.email else 'no'} "
        f"managed_project={elig.project_id != const.DEFAULT_PROJECT_ID} expires_in={tokens.expires_in}s"
    )


async def _access(session: aiohttp.ClientSession, force: bool = False) -> dict:
    stored = json.loads(TOKEN_FILE.read_text())
    if force or stored["expires"] - time.time() < 60:
        tokens = await auth.refresh(session, stored["refresh"])
        stored.update(access=tokens.access_token, refresh=tokens.refresh_token, expires=time.time() + tokens.expires_in)
        _save(TOKEN_FILE, stored)
        print(f"refreshed; expires_in={tokens.expires_in}s")
    return stored


async def refresh(session: aiohttp.ClientSession) -> None:
    await _access(session, force=True)


async def pong(
    session: aiohttp.ClientSession,
    model: str = "gemini-3.8-flash-tiered",
    prompt: str = "Reply with exactly: pong",
    level: str = "LOW",
) -> None:
    import uuid

    stored = await _access(session)
    body = {
        "project": stored["project"],
        "model": model,
        "request": {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"thinkingConfig": {"thinkingLevel": level, "includeThoughts": True}},
        },
        "requestType": "agent",
        "userAgent": "antigravity",
        "requestId": str(uuid.uuid4()),
    }
    headers = const.build_api_headers(stored["access"]) | {"Accept": "text/event-stream"}
    started = time.monotonic()
    async with session.post(const.STREAM_URL, json=body, headers=headers) as resp:
        print(f"HTTP {resp.status} {resp.headers.get('Content-Type')}")
        if resp.status != 200:
            print((await resp.text())[:800])
            return
        chunks = 0
        buffer = b""
        async for raw in resp.content.iter_any():
            buffer += raw
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                chunks += 1
                data = json.loads(line[5:])
                inner = data.get("response", data)
                for cand in inner.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        kind = "thought" if part.get("thought") else "text"
                        if "text" in part:
                            print(f"  +{time.monotonic() - started:5.2f}s {kind}: {part['text'][:80]!r}")
                    if cand.get("finishReason"):
                        print(f"  finishReason={cand['finishReason']}")
                if usage := inner.get("usageMetadata"):
                    print(f"  usage={usage}")
        print(f"{chunks} SSE chunks")


async def main() -> None:
    cmd, *args = sys.argv[1:] or ["help"]
    commands = {
        "device-code": device_code,
        "login-url": login_url,
        "login-finish": login_finish,
        "refresh": refresh,
        "pong": pong,
    }
    if cmd not in commands:
        print(__doc__)
        return
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        await commands[cmd](session, *args)


asyncio.run(main())
