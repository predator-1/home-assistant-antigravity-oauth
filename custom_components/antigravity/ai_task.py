"""AI Task: structured data (with attachments) and image generation."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from homeassistant.components import ai_task, conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AntigravityConfigEntry
from .api.media import generate_image
from .const import DOMAIN, SUBENTRY_AI_TASK
from .llm_entity import AntigravityLLMEntity, raise_as_home_assistant_error

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
MAX_TASK_ITERATIONS = 100
_CODE_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


async def async_setup_entry(
    hass: HomeAssistant, entry: AntigravityConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_AI_TASK:
            async_add_entities([AntigravityTaskEntity(entry, subentry)], config_subentry_id=subentry.subentry_id)


def parse_json(text: str) -> Any:
    """Parse model JSON, tolerating a surrounding code fence (non-Gemini models)."""
    stripped = text.strip()
    if match := _CODE_FENCE.match(stripped):
        stripped = match[1]
    return json.loads(stripped)


class AntigravityTaskEntity(ai_task.AITaskEntity, AntigravityLLMEntity):
    def __init__(self, entry: AntigravityConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(entry, subentry)
        self._attr_supported_features = (
            ai_task.AITaskEntityFeature.GENERATE_DATA | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
        )
        if entry.runtime_data.catalog.data.image_models:
            self._attr_supported_features |= ai_task.AITaskEntityFeature.GENERATE_IMAGE

    async def _async_generate_data(
        self, task: ai_task.GenDataTask, chat_log: conversation.ChatLog
    ) -> ai_task.GenDataTaskResult:
        await self._async_handle_chat_log(chat_log, task.structure, max_iterations=MAX_TASK_ITERATIONS)
        last = chat_log.content[-1]
        if not isinstance(last, conversation.AssistantContent):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_response")
        text = last.content or ""
        if not task.structure:
            return ai_task.GenDataTaskResult(conversation_id=chat_log.conversation_id, data=text)
        try:
            data = parse_json(text)
        except ValueError as err:
            _LOGGER.debug("Model returned invalid JSON: %s", text)
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="invalid_json") from err
        return ai_task.GenDataTaskResult(conversation_id=chat_log.conversation_id, data=data)

    async def _async_generate_image(
        self, task: ai_task.GenImageTask, chat_log: conversation.ChatLog
    ) -> ai_task.GenImageTaskResult:
        user = chat_log.content[-1]
        assert isinstance(user, conversation.UserContent)
        images = [
            (a.mime_type, await self.hass.async_add_executor_job(a.path.read_bytes))
            for a in user.attachments or []
            if a.mime_type.startswith("image/")
        ]
        model = self.entry.runtime_data.catalog.data.image_models[0]
        try:
            result = await generate_image(self.entry.runtime_data.client, user.content, images, model=model)
        except Exception as err:
            raise_as_home_assistant_error(err)
        finally:
            await self.entry.runtime_data.quota.async_request_refresh()
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=self.entity_id, content=result.text)
        )
        return ai_task.GenImageTaskResult(
            image_data=result.image.data,
            conversation_id=chat_log.conversation_id,
            mime_type=result.image.mime_type,
            model=result.model,
        )
