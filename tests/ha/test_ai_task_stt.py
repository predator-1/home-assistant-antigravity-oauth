import io
import wave
from unittest.mock import AsyncMock, patch

import probatio
import pytest
from homeassistant.components import ai_task, media_source, stt
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.antigravity.ai_task import parse_json
from custom_components.antigravity.api.client import Finish, InlineData, TextDelta
from custom_components.antigravity.api.errors import UpstreamError
from custom_components.antigravity.api.media import GeneratedImage
from custom_components.antigravity.const import CONF_CHAT_MODEL, CONF_REASONING_EFFORT, CONF_WEB_SEARCH, DOMAIN

from .conftest import EMAIL
from .test_conversation import FakeStream

TASK = "ai_task.antigravity_ai_task"
STT = "stt.antigravity_stt"


@pytest.fixture
async def entry(hass, entry_data, mock_client):
    assert await async_setup_component(hass, "media_source", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=EMAIL,
        data=entry_data,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gemini-3.8-flash", CONF_REASONING_EFFORT: "medium", CONF_WEB_SEARCH: False},
                subentry_type="ai_task_data",
                title="Antigravity AI Task",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gemini-3.5-flash-lite"},
                subentry_type="stt",
                title="Antigravity STT",
                unique_id=None,
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


STRUCTURE = probatio.Schema({probatio.Required("name"): str, probatio.Optional("count"): int})


async def test_features(hass, entry):
    state = hass.states.get(TASK)
    assert state.attributes["supported_features"] == (
        ai_task.AITaskEntityFeature.GENERATE_DATA
        | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
        | ai_task.AITaskEntityFeature.GENERATE_IMAGE
    )
    assert hass.states.get(STT) is not None


async def test_generate_text(hass, entry):
    fake = FakeStream([TextDelta("A haiku."), Finish("STOP")])
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        result = await ai_task.async_generate_data(hass, task_name="t", entity_id=TASK, instructions="Write a haiku")
    assert result.data == "A haiku."
    model, request = fake.calls[0]
    assert model == "gemini-3.8-flash-medium"
    assert "tools" not in request


async def test_generate_structured_gemini_uses_response_schema(hass, entry):
    fake = FakeStream([TextDelta('{"name": "lamp", '), TextDelta('"count": 2}'), Finish("STOP")])
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        result = await ai_task.async_generate_data(
            hass, task_name="t", entity_id=TASK, instructions="Name a thing", structure=STRUCTURE
        )
    assert result.data == {"name": "lamp", "count": 2}
    config = fake.calls[0][1]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["properties"]["count"] == {"type": "integer"}
    assert config["responseSchema"]["required"] == ["name"]


async def test_generate_structured_claude_uses_prompt(hass, entry):
    subentry = next(s for s in entry.subentries.values() if s.subentry_type == "ai_task_data")
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_CHAT_MODEL: "claude-opus-5-5"}
    )
    await hass.async_block_till_done()
    fake = FakeStream([TextDelta('```json\n{"name": "x"}\n```'), Finish("STOP")])
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        result = await ai_task.async_generate_data(
            hass, task_name="t", entity_id=TASK, instructions="Name a thing", structure=STRUCTURE
        )
    assert result.data == {"name": "x"}
    request = fake.calls[0][1]
    assert "responseSchema" not in request["generationConfig"]
    assert "JSON Schema" in request["systemInstruction"]["parts"][0]["text"]


async def test_generate_structured_invalid_json(hass, entry):
    fake = FakeStream([TextDelta("not json"), Finish("STOP")])
    with (
        patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake),
        pytest.raises(HomeAssistantError, match="valid JSON"),
    ):
        await ai_task.async_generate_data(hass, task_name="t", entity_id=TASK, instructions="x", structure=STRUCTURE)


async def test_attachment_sent_inline(hass, entry, tmp_path):
    image = tmp_path / "cam.jpg"
    image.write_bytes(b"\xff\xd8jpeg")
    fake = FakeStream([TextDelta("A cat."), Finish("STOP")])
    attachment = media_source.PlayMedia(url="http://x", mime_type="image/jpeg", path=image)
    with (
        patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake),
        patch("homeassistant.components.media_source.async_resolve_media", new=AsyncMock(return_value=attachment)),
    ):
        result = await ai_task.async_generate_data(
            hass,
            task_name="t",
            entity_id=TASK,
            instructions="What is this?",
            attachments=[{"media_content_id": "media-source://x/cam.jpg", "media_content_type": "image/jpeg"}],
        )
    assert result.data == "A cat."
    parts = fake.calls[0][1]["contents"][0]["parts"]
    assert parts[1] == {"inlineData": {"mimeType": "image/jpeg", "data": "/9hqcGVn"}}


async def test_generate_image(hass, entry):
    generated = GeneratedImage(InlineData("image/jpeg", b"JPEG"), "", "gemini-3.1-flash-image")
    with (
        patch("custom_components.antigravity.ai_task.generate_image", new=AsyncMock(return_value=generated)) as gen,
    ):
        result = await ai_task.async_generate_image(hass, task_name="t", entity_id=TASK, instructions="A lamp")
    assert gen.await_args.args[1] == "A lamp"
    assert gen.await_args.kwargs["model"] == "gemini-3.1-flash-image"
    assert result["mime_type"] == "image/jpeg"
    assert result["model"] == "gemini-3.1-flash-image"


async def test_generate_image_error(hass, entry):
    with (
        patch(
            "custom_components.antigravity.ai_task.generate_image", new=AsyncMock(side_effect=UpstreamError("no image"))
        ),
        pytest.raises(HomeAssistantError, match="no image"),
    ):
        await ai_task.async_generate_image(hass, task_name="t", entity_id=TASK, instructions="A lamp")


def test_parse_json():
    assert parse_json(" ```json\n[1, 2]\n``` ") == [1, 2]
    assert parse_json('{"a": 1}') == {"a": 1}


async def _stream(data: bytes):
    yield data[:10]
    yield data[10:]


async def test_stt_wraps_pcm_in_wav(hass, entry):
    pcm = b"\x01\x00" * 1600
    with patch(
        "custom_components.antigravity.stt.transcribe", new=AsyncMock(return_value="Turn on the lamp.")
    ) as transcribe:
        entity = stt.async_get_speech_to_text_entity(hass, STT)
        metadata = stt.SpeechMetadata(
            language="en-US",
            format=stt.AudioFormats.WAV,
            codec=stt.AudioCodecs.PCM,
            bit_rate=stt.AudioBitRates.BITRATE_16,
            sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
            channel=stt.AudioChannels.CHANNEL_MONO,
        )
        result = await entity.async_process_audio_stream(metadata, _stream(pcm))
    assert result == stt.SpeechResult("Turn on the lamp.", stt.SpeechResultState.SUCCESS)
    audio, mime = transcribe.await_args.args[1:3]
    assert mime == "audio/wav"
    with wave.open(io.BytesIO(audio)) as wav:
        assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (16000, 2, 1)
        assert wav.readframes(1600) == pcm
    assert transcribe.await_args.kwargs["model"] == "gemini-3.5-flash-lite"
    assert "en-US" in transcribe.await_args.kwargs["prompt"]


async def test_stt_error(hass, entry):
    with patch("custom_components.antigravity.stt.transcribe", new=AsyncMock(side_effect=UpstreamError("x"))):
        entity = stt.async_get_speech_to_text_entity(hass, STT)
        metadata = stt.SpeechMetadata(
            language="en-US",
            format=stt.AudioFormats.OGG,
            codec=stt.AudioCodecs.OPUS,
            bit_rate=stt.AudioBitRates.BITRATE_16,
            sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
            channel=stt.AudioChannels.CHANNEL_MONO,
        )
        result = await entity.async_process_audio_stream(metadata, _stream(b"OggS" * 10))
    assert result.result is stt.SpeechResultState.ERROR


async def test_stt_subentry_only_lists_audio_models(hass, entry):
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "stt"), context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    models = [m["value"] for m in schema[CONF_CHAT_MODEL].config["options"]]
    assert "gpt-oss-120b" not in models
    assert "gemini-3.5-flash-lite" in models
    assert CONF_WEB_SEARCH not in schema


async def test_free_form_object_uses_prompt_schema_on_gemini(hass, entry):
    fake = FakeStream([TextDelta('{"rooms": {"kitchen": 9}}'), Finish("STOP")])
    with patch("custom_components.antigravity.api.client.AntigravityClient.stream_generate", new=fake):
        result = await ai_task.async_generate_data(
            hass,
            task_name="t",
            entity_id=TASK,
            instructions="rooms",
            structure=probatio.Schema({probatio.Required("rooms"): dict}),
        )
    assert result.data == {"rooms": {"kitchen": 9}}
    request = fake.calls[0][1]
    assert request["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseSchema" not in request["generationConfig"]
    assert "JSON Schema" in request["systemInstruction"]["parts"][0]["text"]
