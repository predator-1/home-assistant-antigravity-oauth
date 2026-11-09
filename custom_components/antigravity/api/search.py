"""Google Search grounding as a separate request.

Port of openclaw-antigravity-oauth src/search.ts. The chat turn never gets `googleSearch`;
the agent calls a search tool, which runs this one grounded request on upstream's search
model (`webSearchModelIds`: flash-lite, ~1.5 s vs ~8.5 s on flash; docs/protocol.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .client import AntigravityClient
from .errors import UpstreamError

DEFAULT_SEARCH_MODEL = "gemini-3.8-flash-tiered"

_FRESHNESS = {
    "day": "Prioritize web sources published in the last 24 hours. If no matching recent "
    "sources are available, state that limitation and use the most relevant available sources.",
    "week": "Prioritize web sources published in the past week.",
    "month": "Prioritize web sources published in the past month.",
    "year": "Prioritize web sources published in the past year.",
}


@dataclass(frozen=True)
class Source:
    title: str
    url: str


@dataclass(frozen=True)
class SearchResult:
    answer: str
    sources: tuple[Source, ...]
    queries: tuple[str, ...]


def _sources(grounding: Mapping[str, Any] | None) -> tuple[Source, ...]:
    found: dict[str, Source] = {}
    for chunk in (grounding or {}).get("groundingChunks") or []:
        web = (chunk or {}).get("web") or {}
        if url := web.get("uri"):
            found.setdefault(url, Source(str(web.get("title") or url), url))
    return tuple(found.values())


async def web_search(
    client: AntigravityClient,
    query: str,
    *,
    freshness: str | None = None,
    model: str | None = None,
    timeout: float = 60,
) -> SearchResult:
    text = query.strip()
    if not text:
        raise UpstreamError("Search query must not be empty")
    if hint := _FRESHNESS.get((freshness or "").lower()):
        text += f"\n\nSearch recency instruction: {hint}"
    result = await client.generate(
        model or DEFAULT_SEARCH_MODEL,
        {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "tools": [{"googleSearch": {}}],
        },
        timeout=timeout,
    )
    grounding = result.grounding or {}
    return SearchResult(
        answer=result.text.strip(),
        sources=_sources(grounding),
        queries=tuple(q for q in grounding.get("webSearchQueries") or [] if isinstance(q, str)),
    )
