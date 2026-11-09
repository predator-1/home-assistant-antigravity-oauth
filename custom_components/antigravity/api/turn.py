"""Request building for chat turns: tools, thinking, structured output, replayed tool calls.

Behavior verified live in docs/protocol.md#chat-turns.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .catalog import ChatModel
from .schema import ToolNameMapper, clean_response_schema, clean_tool_parameters

THOUGHT_SIGNATURE_SENTINEL = "skip_thought_signature_validator"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str | None
    parameters: Mapping[str, Any]
    """JSON Schema; sanitized here."""


def build_tools(specs: Iterable[ToolSpec]) -> tuple[list[dict[str, Any]], ToolNameMapper]:
    """`functionDeclarations` with upstream-safe names, and the mapper to read calls back."""
    mapper = ToolNameMapper()
    declarations = []
    for spec in specs:
        declaration: dict[str, Any] = {
            "name": mapper.to_safe(spec.name),
            "parameters": clean_tool_parameters(spec.parameters),
        }
        if spec.description:
            declaration["description"] = spec.description
        declarations.append(declaration)
    return ([{"functionDeclarations": declarations}] if declarations else []), mapper


def function_call_part(
    model: ChatModel,
    mapper: ToolNameMapper,
    call_id: str,
    name: str,
    args: Mapping[str, Any],
    thought_signature: str | None,
) -> dict[str, Any]:
    """A historical `functionCall` part.

    Gemini rejects a replayed call without a signature (HTTP 400); a missing signature is
    replaced by the sentinel, which upstream accepts. Claude and GPT-OSS get no signature field.
    """
    part: dict[str, Any] = {"functionCall": {"id": call_id, "name": mapper.to_safe(name), "args": dict(args)}}
    if model.uses_thought_signatures:
        part["thoughtSignature"] = thought_signature or THOUGHT_SIGNATURE_SENTINEL
    return part


def function_response_part(mapper: ToolNameMapper, call_id: str, name: str, output: Any) -> dict[str, Any]:
    return {
        "functionResponse": {
            "id": call_id,
            "name": mapper.to_safe(name),
            "response": {"output": output},
        }
    }


def build_request(
    model: ChatModel,
    contents: list[dict[str, Any]],
    *,
    system_instruction: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    response_schema: Mapping[str, Any] | None = None,
    json_output: bool = False,
    max_output_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Inner `request` object.

    Effort is chosen by the upstream id (`ChatModel.upstream_id`), never `thinkingLevel`.
    Structured output is Gemini-only and omitted with function tools (upstream 400).
    """
    request: dict[str, Any] = {"contents": contents}
    if system_instruction:
        request["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if tools:
        request["tools"] = tools
    config: dict[str, Any] = {"thinkingConfig": {"includeThoughts": True}}
    if max_output_tokens:
        config["maxOutputTokens"] = max_output_tokens
    if temperature is not None:
        config["temperature"] = temperature
    if model.supports_structured_output and not tools and (json_output or response_schema):
        config["responseMimeType"] = "application/json"
        if response_schema:
            config["responseSchema"] = clean_response_schema(response_schema)
    request["generationConfig"] = config
    return request
