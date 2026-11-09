"""Tool schema sanitizing and upstream-safe tool names.

Port of openclaw-antigravity-oauth src/turn.ts (`cleanJsonSchema`, `cleanResponseJsonSchema`,
`ToolNameMapper`); rules in its docs/protocol.md#request-sanitization. Upstream parses schemas
into protobuf and rejects type arrays and unions.
"""

from __future__ import annotations

import re
from typing import Any

_VALID_TOOL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


def _is_null_branch(branch: Any) -> bool:
    if not isinstance(branch, dict):
        return False
    kind = branch.get("type")
    return kind == "null" or branch.get("nullable") is True or (isinstance(kind, list) and "null" in kind)


def _is_value_branch(branch: Any) -> bool:
    if not isinstance(branch, dict):
        return False
    kind = branch.get("type")
    if isinstance(kind, list):
        return any(t != "null" for t in kind)
    return kind != "null"


def clean_schema_node(raw: Any) -> dict[str, Any]:
    """Sanitize one JSON Schema node into the subset upstream accepts."""
    if not isinstance(raw, dict):
        return {"type": "string"}
    node = dict(raw)
    nullable = node.get("nullable") is True

    branches = node.get("anyOf") or node.get("oneOf")
    if isinstance(branches, list):
        if any(_is_null_branch(b) for b in branches):
            nullable = True
        chosen = next((b for b in branches if _is_value_branch(b)), None) or next(
            (b for b in branches if isinstance(b, dict)), None
        )
        if chosen:
            description = node.get("description")
            node.update(chosen)
            if description and not chosen.get("description"):
                node["description"] = description
        node.pop("anyOf", None)
        node.pop("oneOf", None)

    kind = node.get("type")
    if isinstance(kind, list):
        types = [t.lower().strip() for t in kind if isinstance(t, str) and t.strip()]
        if "null" in types:
            nullable = True
        resolved = next((t for t in types if t != "null"), "string")
    elif isinstance(kind, str):
        resolved = kind.lower().strip()
        if resolved == "null":
            resolved, nullable = "string", True
    elif node.get("properties"):
        resolved = "object"
    elif node.get("items"):
        resolved = "array"
    else:
        resolved = "string"

    cleaned: dict[str, Any] = {"type": resolved}
    if nullable:
        cleaned["nullable"] = True
    if isinstance(node.get("description"), str) and node["description"]:
        cleaned["description"] = node["description"]
    if isinstance(node.get("enum"), list):
        values = list(dict.fromkeys(str(v) for v in node["enum"] if v is not None))
        if values:
            cleaned["enum"] = values
    if isinstance(node.get("required"), list):
        cleaned["required"] = [r for r in node["required"] if isinstance(r, str)]
    if isinstance(node.get("format"), str):
        cleaned["format"] = node["format"]
    if isinstance(node.get("properties"), dict):
        cleaned["properties"] = {k: clean_schema_node(v) for k, v in node["properties"].items()}
    if isinstance(node.get("items"), dict):
        cleaned["items"] = clean_schema_node(node["items"])
    return cleaned


def clean_tool_parameters(schema: Any) -> dict[str, Any]:
    """Function parameters: always an object with `properties`."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    root = clean_schema_node(schema)
    root["type"] = "object"
    root.setdefault("properties", {})
    return root


def clean_response_schema(schema: Any) -> dict[str, Any]:
    """Structured-output schema: the root type is kept (arrays and strings stay)."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    root = clean_schema_node(schema)
    if root["type"] == "object":
        root.setdefault("properties", {})
    return root


class ToolNameMapper:
    """Map host tool names to `^[a-zA-Z_][a-zA-Z0-9_]{0,63}$` and back."""

    def __init__(self) -> None:
        self._to_safe: dict[str, str] = {}
        self._to_original: dict[str, str] = {}

    def to_safe(self, original: str) -> str:
        if not original:
            return "tool"
        if existing := self._to_safe.get(original):
            return existing
        if _VALID_TOOL_NAME.match(original) and self._to_original.get(original, original) == original:
            candidate = original
        else:
            base = re.sub(r"[^a-zA-Z0-9_]", "_", original)
            if not re.match(r"[a-zA-Z_]", base):
                base = f"_{base}"
            base = base[:64]
            candidate, counter = base, 1
            while self._to_original.get(candidate, original) != original:
                suffix = f"_{counter}"
                counter += 1
                candidate = f"{base[: 64 - len(suffix)]}{suffix}"
        self._to_safe[original] = candidate
        self._to_original[candidate] = original
        return candidate

    def to_original(self, safe: str) -> str:
        return self._to_original.get(safe, safe)

    def __contains__(self, safe: str) -> bool:
        return safe in self._to_original
