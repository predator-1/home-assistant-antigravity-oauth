"""Live smoke of the api/ package. Local only, uses a little quota.

Needs a login from `python scripts/spike_phase0.py login-url` / `login-finish`.

  python scripts/smoke.py [MODEL_ID]
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

from custom_components.antigravity.api import auth  # noqa: E402
from custom_components.antigravity.api.client import (  # noqa: E402
    AntigravityClient,
    TextDelta,
    ThoughtDelta,
    ToolCall,
)
from custom_components.antigravity.api.search import web_search  # noqa: E402
from custom_components.antigravity.api.turn import (  # noqa: E402
    ToolSpec,
    build_request,
    build_tools,
    function_call_part,
    function_response_part,
)

TOKEN_FILE = ROOT / ".tmp" / "spike-token.json"


async def main() -> None:
    stored = json.loads(TOKEN_FILE.read_text())
    results: list[tuple[str, str]] = []

    async with aiohttp.ClientSession() as session:

        async def tokens(force: bool) -> str:
            if force or stored["expires"] - time.time() < 60:
                fresh = await auth.refresh(session, stored["refresh"])
                stored.update(
                    access=fresh.access_token,
                    refresh=fresh.refresh_token,
                    expires=time.time() + fresh.expires_in,
                )
                TOKEN_FILE.write_text(json.dumps(stored))
            return stored["access"]

        client = AntigravityClient(session, tokens, stored["project"])

        catalog = await client.fetch_catalog()
        results.append(("catalog", ", ".join(f"{m.id}{list(m.efforts) or ''}" for m in catalog.models)))
        results.append(
            (
                "catalog defaults",
                f"default={catalog.default_model} image={catalog.image_models} flash={catalog.flash_model}",
            )
        )

        quota = await client.fetch_quota()
        results.append(("quota", "; ".join(f"{w.key}={w.remaining_percent}%" for w in quota)))

        model = catalog.get(sys.argv[1] if len(sys.argv) > 1 else "gemini-3.8-flash")
        assert model, "model not in catalog"
        tools, mapper = build_tools(
            [
                ToolSpec(
                    "HassGetWeather",
                    "Get weather for a city",
                    {
                        "type": "object",
                        "properties": {"city": {"type": ["string", "null"]}},
                        "required": ["city"],
                    },
                )
            ]
        )
        ask = {"role": "user", "parts": [{"text": "What's the weather in Paris? Use the tool."}]}
        upstream = model.upstream_id("low")
        calls: list[ToolCall] = []
        async for event in client.stream_generate(
            upstream, build_request(model, [ask], tools=tools), tool_names=mapper
        ):
            if isinstance(event, ToolCall):
                calls.append(event)
        assert calls, "no tool call"
        call = calls[0]
        results.append(
            (
                "tool call",
                f"{upstream}: {call.name}({call.args}) signature={'yes' if call.thought_signature else 'no'}",
            )
        )

        history = [
            ask,
            {
                "role": "model",
                "parts": [function_call_part(model, mapper, call.id, call.name, call.args, call.thought_signature)],
            },
            {"role": "user", "parts": [function_response_part(mapper, call.id, call.name, "Sunny, 21C")]},
        ]
        text, thoughts = "", 0
        async for event in client.stream_generate(
            upstream, build_request(model, history, tools=tools), tool_names=mapper
        ):
            if isinstance(event, TextDelta):
                text += event.text
            elif isinstance(event, ThoughtDelta):
                thoughts += 1
        results.append(("tool replay", f"{text.strip()[:70]!r} thoughts={thoughts}"))

        found = await web_search(client, "Who won the most recent Formula 1 race?")
        results.append(
            (
                "web search",
                f"{found.answer[:70]!r} sources={len(found.sources)} queries={list(found.queries)}",
            )
        )

    for name, detail in results:
        print(f"PASS {name}: {detail}")


asyncio.run(main())
