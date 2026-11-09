from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import probatio
import pytest
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.core import Context
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import intent, llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.antigravity.api.client import Finish, TextDelta, ThoughtDelta, ToolCall, Usage
from custom_components.antigravity.api.errors import QuotaExhaustedError
from custom_components.antigravity.api.search import SearchResult, Source
from custom_components.antigravity.api.turn import THOUGHT_SIGNATURE_SENTINEL
from custom_components.antigravity.const import (
    CONF_CHAT_MODEL,
    CONF_REASONING_EFFORT,
    CONF_WEB_SEARCH,
    DOMAIN,
)

from .conftest import EMAIL

AGENT = "conversation.antigravity_conversation"


class EchoTool(llm.Tool):
    name = "echo"
    description = "Echo the input"
    parameters = probatio.Schema({probatio.Required("text"): str})

    async def async_call(self, hass, tool_input, llm_context):
        return llm.ToolResult(data={"echo": tool_input.tool_args["text"]})


class EchoAPI(llm.API):
    async def async_get_api_instance(self, llm_context):
        return llm.APIInstance(self, "Use echo.", llm_context, [EchoTool()])


class FakeStream:
    """Scripted replies per stream_generate call; records (model, request)."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = []

    async def __call__(self, model, request, *, tool_names=None, timeout=120):
        self.calls.append((model, request))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        for event in turn:
            yield event


@pytest.fixture
async def setup_agent(hass, entry_data, mock_client):
    async def _setup(**options):
        llm.async_register_api(hass, EchoAPI(hass=hass, id="echo-api", name="Echo"))
        data = {CONF_CHAT_MODEL: "gemini-3.8-flash", CONF_REASONING_EFFORT: "low", CONF_WEB_SEARCH: True}
        data.update(options)
        entry = MockConfigEntry(
            domain=DOMAIN,
            title=EMAIL,
            unique_id=EMAIL,
            data=entry_data,
            subentries_data=[
                ConfigSubentryData(
                    data=data, subentry_type="conversation", title="Antigravity conversation", unique_id=None
                )
            ],
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup


async def converse(hass, text="hi", conversation_id=None):
    return await conversation.async_converse(hass, text, conversation_id, Context(), agent_id=AGENT)


async def test_text_reply(hass, setup_agent):
    await setup_agent()
    fake = FakeStream([ThoughtDelta("hmm"), TextDelta("Hello"), TextDelta(" there"), Usage(5, 2, 1, 0), Finish("STOP")])
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        result = await converse(hass)
    assert result.response.response_type is intent.IntentResponseType.ACTION_DONE
    assert result.response.speech["plain"]["speech"] == "Hello there"
    model, request = fake.calls[0]
    assert model == "gemini-3.8-flash-low"
    assert request["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]
    assert request["systemInstruction"]["parts"][0]["text"]
    names = [d["name"] for d in request["tools"][0]["functionDeclarations"]]
    assert names == ["web_search"]
    assert request["generationConfig"]["thinkingConfig"] == {"includeThoughts": True}


async def test_tool_call_and_signature_replay(hass, setup_agent):
    await setup_agent(**{CONF_LLM_HASS_API: ["echo-api"]})
    fake = FakeStream(
        [ToolCall("call_1", "echo", {"text": "ping"}, "SIG"), Finish("STOP")],
        [TextDelta("It said ping"), Finish("STOP")],
    )
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        result = await converse(hass)
    assert result.response.speech["plain"]["speech"] == "It said ping"
    assert len(fake.calls) == 2
    first = fake.calls[0][1]
    assert sorted(d["name"] for d in first["tools"][0]["functionDeclarations"]) == ["echo", "web_search"]
    second = fake.calls[1][1]["contents"]
    assert second[1] == {
        "role": "model",
        "parts": [
            {"functionCall": {"id": "call_1", "name": "echo", "args": {"text": "ping"}}, "thoughtSignature": "SIG"}
        ],
    }
    assert second[2] == {
        "role": "user",
        "parts": [{"functionResponse": {"id": "call_1", "name": "echo", "response": {"output": {"echo": "ping"}}}}],
    }


async def test_signature_from_other_model_uses_sentinel(hass, setup_agent):
    entry = await setup_agent(**{CONF_LLM_HASS_API: ["echo-api"]})
    fake = FakeStream(
        [ToolCall("call_1", "echo", {"text": "a"}, "SIG"), Finish("STOP")],
        [TextDelta("ok"), Finish("STOP")],
    )
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        result = await converse(hass)
    subentry = next(iter(entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_CHAT_MODEL: "gemini-4-argon"}
    )
    await hass.async_block_till_done()
    fake = FakeStream([TextDelta("again"), Finish("STOP")])
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        await converse(hass, "more", result.conversation_id)
    model, request = fake.calls[0]
    assert model == "gemini-4-argon-low"
    assert request["contents"][1]["parts"][0]["thoughtSignature"] == THOUGHT_SIGNATURE_SENTINEL


async def test_claude_replay_has_no_signature(hass, setup_agent):
    await setup_agent(
        **{CONF_LLM_HASS_API: ["echo-api"], CONF_CHAT_MODEL: "claude-sonnet-5-5", CONF_REASONING_EFFORT: "high"}
    )
    fake = FakeStream(
        [ToolCall("toolu_1", "echo", {"text": "a"}), Finish("STOP")],
        [TextDelta("ok"), Finish("STOP")],
    )
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        await converse(hass)
    assert fake.calls[0][0] == "claude-sonnet-5-5-high"
    assert fake.calls[1][1]["contents"][1]["parts"] == [
        {"functionCall": {"id": "toolu_1", "name": "echo", "args": {"text": "a"}}}
    ]


async def test_web_search_runs_as_separate_request(hass, setup_agent):
    await setup_agent()
    fake = FakeStream(
        [TextDelta("Let me check. "), ToolCall("call_s", "web_search", {"query": "f1 winner"}, "S"), Finish("STOP")],
        [TextDelta("Max won."), Finish("STOP")],
    )
    found = SearchResult("Max Verstappen won.", (Source("F1", "https://f1.example"),), ("f1 winner",))
    with (
        patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake),
        patch("custom_components.antigravity.llm_entity.web_search", new=AsyncMock(return_value=found)) as search,
    ):
        result = await converse(hass, "who won f1?")
    assert result.response.speech["plain"]["speech"] == "Max won."
    assert search.await_args.args[1] == "f1 winner"
    assert search.await_args.kwargs["model"] == "gemini-3.5-flash-lite"
    response = fake.calls[1][1]["contents"][2]["parts"][0]["functionResponse"]
    assert response["name"] == "web_search"
    assert response["response"]["output"]["sources"] == [{"title": "F1", "url": "https://f1.example"}]


async def test_web_search_disabled_sends_no_tools(hass, setup_agent):
    await setup_agent(**{CONF_WEB_SEARCH: False})
    fake = FakeStream([TextDelta("hi"), Finish("STOP")])
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        await converse(hass)
    assert "tools" not in fake.calls[0][1]


async def test_quota_exhausted_message(hass, setup_agent):
    await setup_agent()
    reset = datetime.now(UTC) + timedelta(hours=2, minutes=5)
    fake = FakeStream(QuotaExhaustedError("RESOURCE_EXHAUSTED: quota", reset))
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        result = await converse(hass)
    assert result.response.response_type is intent.IntentResponseType.ERROR
    speech = result.response.speech["plain"]["speech"]
    assert "quota" in speech
    assert "(in 2h" in speech


async def test_blocked_response(hass, setup_agent):
    await setup_agent()
    fake = FakeStream([Finish("SAFETY")])
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        result = await converse(hass)
    assert result.response.response_type is intent.IntentResponseType.ERROR
    assert "SAFETY" in result.response.speech["plain"]["speech"]


async def test_new_agent_subentry_and_reconfigure(hass, setup_agent):
    entry = await setup_agent()
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "conversation"), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    models = result["data_schema"].schema[CONF_CHAT_MODEL].config["options"]
    assert [m["value"] for m in models][:2] == ["gemini-4-argon", "gemini-3.8-flash"]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Claude agent",
            CONF_CHAT_MODEL: "claude-opus-5-5",
            CONF_REASONING_EFFORT: "high",
            CONF_WEB_SEARCH: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("conversation.claude_agent") is not None

    subentry = next(s for s in entry.subentries.values() if s.title == "Antigravity conversation")
    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_CHAT_MODEL: "gemini-4-argon", CONF_REASONING_EFFORT: "medium", CONF_WEB_SEARCH: True}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[subentry.subentry_id].data[CONF_CHAT_MODEL] == "gemini-4-argon"
