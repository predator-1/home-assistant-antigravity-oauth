"""HTTP client for the `v1internal` endpoints.

One request per call; extra requests only for the 401 refresh retry and bounded transient
429 retries (openclaw-antigravity-oauth docs/architecture.md §4.2).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .. import const
from .catalog import Catalog, parse_catalog
from .errors import (
    AuthError,
    NativeToolRefusedError,
    QuotaExhaustedError,
    RateLimitError,
    RateLimitKind,
    UnknownModelError,
    UpstreamError,
    classify_429,
    error_summary,
)
from .quota import QuotaWindow, parse_quota_summary
from .schema import ToolNameMapper

_LOGGER = logging.getLogger(__name__)

TokenProvider = Callable[[bool], Awaitable[str]]
"""Returns a valid access token; `True` forces a refresh (after a 401)."""

MAX_RATE_LIMIT_RETRIES = 2
_NATIVE_TOOL_KEYS = ("offered_tools", "native_tools", "server_tools")


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ThoughtDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    """Host tool name (mapped back from the upstream-safe name)."""
    args: dict[str, Any]
    thought_signature: str | None = None


@dataclass(frozen=True)
class InlineData:
    mime_type: str
    data: bytes


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    cached_tokens: int = 0


@dataclass(frozen=True)
class Finish:
    reason: str
    grounding: Mapping[str, Any] | None = None


StreamEvent = TextDelta | ThoughtDelta | ToolCall | InlineData | Usage | Finish


@dataclass
class GenerateResult:
    text: str = ""
    thoughts: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    inline_data: list[InlineData] = field(default_factory=list)
    usage: Usage | None = None
    finish_reason: str | None = None
    grounding: Mapping[str, Any] | None = None


def _usage(raw: Any) -> Usage | None:
    if not isinstance(raw, Mapping):
        return None
    return Usage(
        input_tokens=int(raw.get("promptTokenCount") or 0),
        output_tokens=int(raw.get("candidatesTokenCount") or 0),
        thought_tokens=int(raw.get("thoughtsTokenCount") or 0),
        cached_tokens=int(raw.get("cachedContentTokenCount") or 0),
    )


def _check_native_tools(payload: Mapping[str, Any]) -> None:
    for source in (payload, payload.get("response") or {}):
        for key in _NATIVE_TOOL_KEYS:
            if isinstance(source, Mapping) and source.get(key):
                raise UpstreamError("native tools offered")


class AntigravityClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: TokenProvider,
        project_id: str,
        api_base: str = const.API_BASE,
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._api_base = api_base
        self.project_id = project_id

    async def _post(
        self, url: str, body: Mapping[str, Any], *, timeout: float, accept: str = "application/json"
    ) -> aiohttp.ClientResponse:
        """POST with the 401 refresh retry and transient 429 retries; returns a 200 response."""
        refreshed = False
        rate_limit_attempt = 0
        while True:
            token = await self._tokens(False)
            headers = const.build_api_headers(token) | {"Accept": accept}
            resp = await self._session.post(
                url,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=timeout),
            )
            if resp.status == 200:
                return resp
            text = await resp.text()
            resp.release()
            if resp.status == 401 and not refreshed:
                refreshed = True
                await self._tokens(True)
                continue
            if resp.status == 429:
                info = classify_429(text, resp.headers)
                if info.kind is RateLimitKind.TRANSIENT and rate_limit_attempt < MAX_RATE_LIMIT_RETRIES:
                    rate_limit_attempt += 1
                    delay = min(max(info.retry_delay or 1.0, 0.1), 10.0)
                    _LOGGER.debug("Transient rate limit (%s), retrying in %.1fs", info.reason, delay)
                    await asyncio.sleep(delay)
                    continue
                if info.kind is RateLimitKind.TRANSIENT:
                    raise RateLimitError(f"Subscription rate limit exceeded: {info.summary}")
                raise QuotaExhaustedError(info.summary, info.reset_at)
            summary = error_summary(text)
            if resp.status == 403 and any(k in text for k in ("quota", "RESOURCE_EXHAUSTED", "exhausted")):
                raise QuotaExhaustedError(summary, classify_429(text, resp.headers).reset_at)
            if resp.status in (401, 403):
                raise AuthError(f"Authentication error ({resp.status}): {summary}")
            if resp.status == 404:
                raise UnknownModelError(f"unknown model ({summary})")
            raise UpstreamError(f"HTTP {resp.status}: {summary}", resp.status)

    async def _post_json(self, url: str, body: Mapping[str, Any], timeout: float = 30) -> Any:
        resp = await self._post(url, body, timeout=timeout)
        async with resp:
            return await resp.json(content_type=None)

    async def fetch_catalog(self) -> Catalog:
        return parse_catalog(
            await self._post_json(f"{self._api_base}:fetchAvailableModels", {"project": self.project_id})
        )

    async def fetch_quota(self) -> list[QuotaWindow]:
        return parse_quota_summary(await self._post_json(f"{self._api_base}:retrieveUserQuotaSummary", {}))

    async def stream_generate(
        self,
        model: str,
        request: Mapping[str, Any],
        *,
        tool_names: ToolNameMapper | None = None,
        timeout: float = 120,
    ) -> AsyncIterator[StreamEvent]:
        """Stream one `streamGenerateContent` call.

        A function call to a name not in `tool_names` raises `NativeToolRefusedError`.
        """
        body = {
            "project": self.project_id,
            "model": model,
            "request": request,
            "requestType": "agent",
            "userAgent": "antigravity",
            "requestId": f"agent-{uuid.uuid4()}",
        }
        resp = await self._post(
            f"{self._api_base}:streamGenerateContent?alt=sse",
            body,
            timeout=timeout,
            accept="text/event-stream, application/json",
        )
        async with resp:
            if resp.headers.get("x-antigravity-native-tools") or resp.headers.get("x-offered-tools"):
                raise UpstreamError("native tools offered")
            usage: Usage | None = None
            finish_reason = ""
            grounding: Mapping[str, Any] | None = None
            call_index = 0
            async for line in resp.content:
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if not data or data == b"[DONE]":
                    continue
                chunk = json.loads(data)
                if error := chunk.get("error") or (chunk.get("response") or {}).get("error"):
                    raise UpstreamError(f"Endpoint error: {error_summary(json.dumps({'error': error}))}")
                _check_native_tools(chunk)
                inner = chunk.get("response", chunk)
                usage = _usage(inner.get("usageMetadata")) or usage
                for candidate in inner.get("candidates") or []:
                    for part in (candidate.get("content") or {}).get("parts") or []:
                        if part.get("thought") is True:
                            if part.get("text"):
                                yield ThoughtDelta(part["text"])
                            continue
                        if part.get("text"):
                            yield TextDelta(part["text"])
                        if call := part.get("functionCall"):
                            yield self._tool_call(call, part, tool_names, call_index)
                            call_index += 1
                        if inline := part.get("inlineData"):
                            yield InlineData(
                                inline.get("mimeType", "application/octet-stream"),
                                base64.b64decode(inline.get("data", "")),
                            )
                    finish_reason = candidate.get("finishReason") or finish_reason
                    grounding = candidate.get("groundingMetadata") or grounding
            if usage:
                yield usage
            if not finish_reason:
                raise UpstreamError("Stream ended without a finish reason")
            yield Finish(finish_reason, grounding)

    @staticmethod
    def _tool_call(
        call: Mapping[str, Any], part: Mapping[str, Any], tool_names: ToolNameMapper | None, index: int
    ) -> ToolCall:
        safe_name = str(call.get("name") or "").strip()
        if not safe_name or tool_names is None or safe_name not in tool_names:
            raise NativeToolRefusedError(safe_name or "<empty>")
        args = call.get("args")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"input": args}
        signature = part.get("thoughtSignature") or part.get("thought_signature")
        return ToolCall(
            id=str(call.get("id") or f"call_{index}"),
            name=tool_names.to_original(safe_name),
            args=args if isinstance(args, dict) else {},
            thought_signature=signature if isinstance(signature, str) and signature else None,
        )

    async def generate(
        self,
        model: str,
        request: Mapping[str, Any],
        *,
        tool_names: ToolNameMapper | None = None,
        timeout: float = 120,
    ) -> GenerateResult:
        """Collect a whole `stream_generate` call."""
        result = GenerateResult()
        async for event in self.stream_generate(model, request, tool_names=tool_names, timeout=timeout):
            match event:
                case TextDelta(text):
                    result.text += text
                case ThoughtDelta(text):
                    result.thoughts += text
                case ToolCall():
                    result.tool_calls.append(event)
                case InlineData():
                    result.inline_data.append(event)
                case Usage():
                    result.usage = event
                case Finish(reason, grounding):
                    result.finish_reason, result.grounding = reason, grounding
        return result
