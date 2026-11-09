"""Subscription chat models from `fetchAvailableModels`.

Unlike the OpenClaw plugin's heuristic filters, this uses upstream's own routing lists
(docs/protocol.md#model-catalog): the agent picker (`agentModelSorts`) plus the cheap
flash-lite tier. Effort variants (`<family>-low|medium|high`) collapse into one model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

_EFFORT_SUFFIX = re.compile(r"^(?P<family>.+)-(?P<effort>low|medium|high)$")
_DISPLAY_EFFORT = re.compile(r"\s*\((?:low|medium|high|tiered)\)\s*$", re.IGNORECASE)
EFFORT_ORDER = ("low", "medium", "high")
DEFAULT_EFFORT = "medium"


@dataclass(frozen=True)
class ChatModel:
    id: str
    """Family id without the effort suffix, e.g. `claude-sonnet-5-5`."""
    name: str
    variants: Mapping[str, str]
    """Effort -> upstream id. Empty when the model has one upstream id (`id`)."""
    context_window: int
    max_output_tokens: int
    mime_types: frozenset[str] = field(default_factory=frozenset)
    supports_images: bool = False

    @property
    def efforts(self) -> tuple[str, ...]:
        return tuple(e for e in EFFORT_ORDER if e in self.variants)

    @property
    def is_gemini(self) -> bool:
        return self.id.startswith("gemini-")

    @property
    def uses_thought_signatures(self) -> bool:
        """Gemini tool calls carry signatures that must be replayed (docs/protocol.md)."""
        return self.is_gemini

    @property
    def supports_structured_output(self) -> bool:
        return self.is_gemini

    def accepts(self, mime_type: str) -> bool:
        return mime_type.lower() in self.mime_types

    def upstream_id(self, effort: str | None = None) -> str:
        """Upstream model id for an effort; unknown or missing effort uses the default."""
        if not self.variants:
            return self.id
        if effort in self.variants:
            return self.variants[effort]
        if DEFAULT_EFFORT in self.variants:
            return self.variants[DEFAULT_EFFORT]
        return self.variants[self.efforts[-1]]


@dataclass(frozen=True)
class Catalog:
    models: tuple[ChatModel, ...]
    default_model: str | None = None
    image_models: tuple[str, ...] = ()
    flash_model: str | None = None
    """Upstream id for search grounding and media understanding (`tieredModelIds.flash`)."""

    def get(self, model_id: str) -> ChatModel | None:
        return next((m for m in self.models if m.id == model_id), None)


def _mime_types(raw: Any) -> frozenset[str]:
    if isinstance(raw, Mapping):
        items: Iterable[Any] = (k for k, v in raw.items() if v)
    elif isinstance(raw, list):
        items = raw
    else:
        return frozenset()
    return frozenset(m.strip().lower() for m in items if isinstance(m, str) and m.strip())


def _positive_int(*values: Any, default: int) -> int:
    for value in values:
        if isinstance(value, int) and value > 0:
            return value
    return default


def _ids(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _agent_model_ids(payload: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for sort in payload.get("agentModelSorts") or []:
        for group in (sort or {}).get("groups") or []:
            ids.extend(_ids((group or {}).get("modelIds")))
    ids.extend(_ids((payload.get("tieredModelIds") or {}).get("flashLite")))
    return list(dict.fromkeys(ids))


def _family(model_id: str) -> tuple[str, str | None]:
    if match := _EFFORT_SUFFIX.match(model_id):
        return match["family"], match["effort"]
    return model_id, None


def parse_catalog(payload: Mapping[str, Any]) -> Catalog:
    """Build the catalog; invents nothing when lists are missing or empty."""
    raw_models = payload.get("models")
    if not isinstance(raw_models, Mapping):
        raw_models = {}
    deprecated = set(_ids(payload.get("deprecatedModelIds")))

    families: dict[str, dict[str, Any]] = {}
    for upstream_id in _agent_model_ids(payload):
        raw = raw_models.get(upstream_id)
        if not isinstance(raw, Mapping) or raw.get("disabled") is True or raw.get("enabled") is False:
            continue
        family, effort = _family(upstream_id)
        if upstream_id in deprecated or family in deprecated:
            continue
        entry = families.setdefault(
            family,
            {"name": None, "variants": {}, "context": 0, "output": 0, "mime": set(), "images": False},
        )
        if effort:
            entry["variants"][effort] = upstream_id
        name = _DISPLAY_EFFORT.sub("", str(raw.get("displayName") or "")).strip()
        entry["name"] = entry["name"] or name or None
        entry["context"] = max(entry["context"], _positive_int(raw.get("maxTokens"), default=0))
        entry["output"] = max(entry["output"], _positive_int(raw.get("maxOutputTokens"), default=0))
        entry["mime"] |= _mime_types(raw.get("supportedMimeTypes"))
        entry["images"] |= raw.get("supportsImages") is True

    models = tuple(
        ChatModel(
            id=family,
            name=entry["name"] or family,
            variants=dict(sorted(entry["variants"].items(), key=lambda kv: EFFORT_ORDER.index(kv[0]))),
            context_window=entry["context"] or 128_000,
            max_output_tokens=entry["output"] or 8_192,
            mime_types=frozenset(entry["mime"]),
            supports_images=entry["images"] or any(m.startswith("image/") for m in entry["mime"]),
        )
        for family, entry in families.items()
    )
    default = payload.get("defaultAgentModelId")
    default_family = _family(default)[0] if isinstance(default, str) else None
    flash = _ids((payload.get("tieredModelIds") or {}).get("flash"))
    return Catalog(
        models=models,
        default_model=default_family if any(m.id == default_family for m in models) else None,
        image_models=tuple(_ids(payload.get("imageGenerationModelIds"))),
        flash_model=flash[0] if flash else None,
    )
