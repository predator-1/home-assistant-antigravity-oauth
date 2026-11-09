"""Chat log ⇄ `v1internal` translation shared by conversation and AI Task entities."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp
import probatio
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.entity import Entity
from homeassistant.util import dt as dt_util

from .api.catalog import ChatModel
from .api.client import Finish, TextDelta, ThoughtDelta, ToolCall, Usage
from .api.errors import (
    AntigravityError,
    AuthError,
    NativeToolRefusedError,
    QuotaExhaustedError,
    RateLimitError,
    UnknownModelError,
)
from .api.media import check_inline_size, inline_part
from .api.schema import ToolNameMapper, has_free_form_object
from .api.search import web_search
from .api.turn import ToolSpec, build_request, build_tools, function_call_part, function_response_part
from .const import (
    CONF_CHAT_MODEL,
    CONF_REASONING_EFFORT,
    CONF_WEB_SEARCH,
    DOMAIN,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_REASONING_EFFORT,
    WEB_SEARCH_TOOL,
)

if TYPE_CHECKING:
    from . import AntigravityConfigEntry

_LOGGER = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10
ACCEPTED_FINISH_REASONS = {"STOP", "MAX_TOKENS"}

WEB_SEARCH_SPEC = ToolSpec(
    name=WEB_SEARCH_TOOL,
    description=(
        "Search the web with Google for current or external information (news, facts, prices, events). "
        "Do not use it for the state of this home; use the home tools for that."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "freshness": {
                "type": "string",
                "enum": ["day", "week", "month", "year"],
                "description": "Prefer results from this recent period.",
            },
        },
        "required": ["query"],
    },
)


@dataclass
class AntigravityNative:
    """Kept on AssistantContent.native: Gemini thought signatures per tool call id."""

    model: str
    signatures: dict[str, str] = field(default_factory=dict)


def _tool_spec(tool: llm.Tool, custom_serializer: Any) -> ToolSpec:
    parameters = (
        probatio.to_openapi(tool.parameters, custom_serializer=custom_serializer) if tool.parameters.schema else {}
    )
    return ToolSpec(tool.name, tool.description, parameters)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _format_reset(reset_at: datetime | None) -> str:
    if reset_at is None:
        return "later"
    local = dt_util.as_local(reset_at)
    minutes = max(0, int((reset_at - dt_util.utcnow()).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    relative = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    return f"{local.strftime('%a %H:%M')} (in {relative})"


def raise_as_home_assistant_error(err: Exception) -> None:
    """Re-raise upstream errors as user-facing HomeAssistantError."""
    match err:
        case QuotaExhaustedError():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="quota_exhausted",
                translation_placeholders={"reset": _format_reset(err.reset_at)},
            ) from err
        case AuthError():
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="sign_in_required") from err
        case RateLimitError() | UnknownModelError() | NativeToolRefusedError() | AntigravityError():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="upstream_error",
                translation_placeholders={"error": str(err)},
            ) from err
        case aiohttp.ClientError() | TimeoutError():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="upstream_error",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err
    raise err


class AntigravityLLMEntity(Entity):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: AntigravityConfigEntry, subentry: ConfigSubentry) -> None:
        self.entry = entry
        self.subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        model = self._model()
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Google",
            model=model.name if model else subentry.data.get(CONF_CHAT_MODEL),
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    def _model(self) -> ChatModel | None:
        catalog = self.entry.runtime_data.catalog.data
        wanted = self.subentry.data.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL)
        return (
            catalog.get(wanted)
            or catalog.get(RECOMMENDED_CHAT_MODEL)
            or (catalog.get(catalog.default_model) if catalog.default_model else None)
        )

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        structure: probatio.Schema | None = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> None:
        """Run turns until the model stops calling tools; results go into the chat log."""
        model = self._model()
        if model is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="model_unavailable")
        options = self.subentry.data
        effort = options.get(CONF_REASONING_EFFORT, RECOMMENDED_REASONING_EFFORT)
        search_enabled = bool(options.get(CONF_WEB_SEARCH))

        specs: list[ToolSpec] = []
        if chat_log.llm_api:
            specs = [_tool_spec(tool, chat_log.llm_api.custom_serializer) for tool in chat_log.llm_api.tools]
        if search_enabled and all(spec.name != WEB_SEARCH_TOOL for spec in specs):
            specs.append(WEB_SEARCH_SPEC)
        tools, mapper = build_tools(specs)

        response_schema = None
        system_instruction = chat_log.content[0].content or ""
        if structure is not None:
            serializer = chat_log.llm_api.custom_serializer if chat_log.llm_api else llm.selector_serializer
            schema = probatio.to_openapi(structure, custom_serializer=serializer)
            if model.supports_structured_output and not has_free_form_object(schema):
                response_schema = schema
            else:
                # Claude and GPT-OSS have no responseSchema upstream, and Gemini's schema cannot express
                # objects without properties (they come back empty): ask for JSON in the prompt instead.
                system_instruction += (
                    "\n\nRespond with only a JSON value (no prose, no code fence) matching this JSON Schema:\n"
                    + json.dumps(schema)
                )

        client = self.entry.runtime_data.client
        try:
            for _ in range(max_iterations):
                contents = await self._async_contents(chat_log, model, mapper)
                request = build_request(
                    model,
                    contents,
                    system_instruction=system_instruction or None,
                    tools=tools,
                    response_schema=response_schema,
                    json_output=structure is not None,
                )
                stream = client.stream_generate(model.upstream_id(effort), request, tool_names=mapper)
                async for _content in chat_log.async_add_delta_content_stream(
                    self.entity_id, self._transform(chat_log, model, stream, search_enabled)
                ):
                    pass
                if not chat_log.unresponded_tool_results:
                    break
        except HomeAssistantError:
            raise
        except Exception as err:
            raise_as_home_assistant_error(err)
        finally:
            await self.entry.runtime_data.quota.async_request_refresh()

    async def _async_contents(
        self, chat_log: conversation.ChatLog, model: ChatModel, mapper: ToolNameMapper
    ) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []

        def flush_results() -> None:
            if results:
                contents.append({"role": "user", "parts": list(results)})
                results.clear()

        for content in chat_log.content[1:]:
            if isinstance(content, conversation.ToolResultContent):
                output = _jsonable(content.result.data)
                if content.result.error:
                    output = {"error": True, **(output if isinstance(output, dict) else {"data": output})}
                results.append(function_response_part(mapper, content.tool_call_id, content.tool_name, output))
                continue
            flush_results()
            if isinstance(content, conversation.UserContent):
                parts: list[dict[str, Any]] = [{"text": content.content or " "}]
                for attachment in content.attachments or []:
                    parts.append(await self._async_inline(attachment.path, attachment.mime_type))
                contents.append({"role": "user", "parts": parts})
            elif isinstance(content, conversation.AssistantContent):
                parts = []
                if content.content:
                    parts.append({"text": content.content})
                native = content.native if isinstance(content.native, AntigravityNative) else None
                for call in content.tool_calls or []:
                    signature = native.signatures.get(call.id) if native and native.model == model.id else None
                    parts.append(function_call_part(model, mapper, call.id, call.tool_name, call.tool_args, signature))
                contents.append({"role": "model", "parts": parts or [{"text": " "}]})
        flush_results()
        if contents and contents[0]["role"] != "user":
            # start_conversation can begin with an assistant message; upstream wants a user turn first.
            contents.insert(0, {"role": "user", "parts": [{"text": " "}]})
        return contents

    async def _async_inline(self, path: Path, mime_type: str) -> dict[str, Any]:
        data = await self.hass.async_add_executor_job(path.read_bytes)
        check_inline_size(len(data))
        return inline_part(mime_type, data)

    async def _transform(
        self,
        chat_log: conversation.ChatLog,
        model: ChatModel,
        stream: AsyncIterator[Any],
        search_enabled: bool,
    ) -> AsyncGenerator[conversation.AssistantContentDeltaDict | conversation.ToolResultContentDeltaDict]:
        yield {"role": "assistant"}
        native = AntigravityNative(model=model.id)
        searches: list[llm.ToolInput] = []
        async for event in stream:
            match event:
                case TextDelta(text):
                    yield {"content": text}
                case ThoughtDelta(text):
                    yield {"thinking_content": text}
                case ToolCall():
                    external = search_enabled and event.name == WEB_SEARCH_TOOL
                    tool_input = llm.ToolInput(
                        tool_name=event.name, tool_args=event.args, id=event.id, external=external
                    )
                    if external:
                        searches.append(tool_input)
                    if event.thought_signature:
                        native.signatures[event.id] = event.thought_signature
                    yield {"tool_calls": [tool_input]}
                case Usage():
                    chat_log.async_trace(
                        {
                            "stats": {
                                "input_tokens": event.input_tokens,
                                "cached_input_tokens": event.cached_tokens,
                                "output_tokens": event.output_tokens,
                                "thought_tokens": event.thought_tokens,
                            }
                        }
                    )
                case Finish(reason) if reason not in ACCEPTED_FINISH_REASONS:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="response_blocked",
                        translation_placeholders={"reason": reason},
                    )
        if native.signatures:
            yield {"native": native}
        for tool_input in searches:
            yield {
                "role": "tool_result",
                "tool_call_id": tool_input.id,
                "tool_name": tool_input.tool_name,
                "result": await self._async_web_search(tool_input),
            }

    async def _async_web_search(self, tool_input: llm.ToolInput) -> llm.ToolResult:
        query = str(tool_input.tool_args.get("query") or "")
        try:
            result = await web_search(
                self.entry.runtime_data.client,
                query,
                freshness=tool_input.tool_args.get("freshness"),
                model=self.entry.runtime_data.catalog.data.search_model,
            )
        except (AntigravityError, aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Web search failed: %s", err)
            return llm.ToolResult(data={"error": "SearchFailed", "error_text": str(err)}, error=True)
        return llm.ToolResult(
            data={
                "answer": result.answer,
                "sources": [{"title": s.title, "url": s.url} for s in result.sources],
            }
        )
