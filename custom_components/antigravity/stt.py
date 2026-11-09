"""Speech-to-text: the recorded utterance is sent inline to a Gemini model."""

from __future__ import annotations

import io
import logging
import wave
from collections.abc import AsyncIterable

import aiohttp
from homeassistant.components import stt
from homeassistant.const import CONF_PROMPT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AntigravityConfigEntry
from .api.errors import AntigravityError
from .api.media import transcribe
from .const import DEFAULT_STT_PROMPT, SUBENTRY_STT
from .llm_entity import AntigravityLLMEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Gemini transcribes many languages; Home Assistant needs an explicit list.
LANGUAGES = [
    "af-ZA", "ar-AE", "ar-EG", "ar-SA", "az-AZ", "bg-BG", "bn-IN", "ca-ES", "cs-CZ", "da-DK", "de-AT", "de-CH",
    "de-DE", "el-GR", "en-AU", "en-CA", "en-GB", "en-IE", "en-IN", "en-NZ", "en-US", "en-ZA", "es-AR", "es-ES",
    "es-MX", "es-US", "et-EE", "eu-ES", "fa-IR", "fi-FI", "fil-PH", "fr-BE", "fr-CA", "fr-CH", "fr-FR", "gl-ES",
    "he-IL", "hi-IN", "hr-HR", "hu-HU", "hy-AM", "id-ID", "is-IS", "it-IT", "ja-JP", "ka-GE", "kk-KZ", "ko-KR",
    "lt-LT", "lv-LV", "mk-MK", "ms-MY", "nb-NO", "nl-BE", "nl-NL", "pl-PL", "pt-BR", "pt-PT", "ro-RO", "ru-RU",
    "sk-SK", "sl-SI", "sq-AL", "sr-RS", "sv-SE", "sw-KE", "ta-IN", "te-IN", "th-TH", "tr-TR", "uk-UA", "ur-PK",
    "uz-UZ", "vi-VN", "zh-CN", "zh-HK", "zh-TW",
]  # fmt: skip


async def async_setup_entry(
    hass: HomeAssistant, entry: AntigravityConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_STT:
            async_add_entities([AntigravitySttEntity(entry, subentry)], config_subentry_id=subentry.subentry_id)


def pcm_to_wav(pcm: bytes, sample_rate: int, bits: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(bits // 8)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


class AntigravitySttEntity(stt.SpeechToTextEntity, AntigravityLLMEntity):
    @property
    def supported_languages(self) -> list[str]:
        return LANGUAGES

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        return [stt.AudioFormats.WAV, stt.AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        return [stt.AudioCodecs.PCM, stt.AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        return [stt.AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        return [stt.AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        audio = b"".join([chunk async for chunk in stream])
        if metadata.format is stt.AudioFormats.WAV:
            # The pipeline streams raw PCM for "wav"; add the header the model needs.
            audio = pcm_to_wav(audio, metadata.sample_rate.value, metadata.bit_rate.value)
        prompt = self.subentry.data.get(CONF_PROMPT) or DEFAULT_STT_PROMPT
        if metadata.language:
            prompt += f"\nThe spoken language is {metadata.language}. Transcribe in that language."
        model = self._model()
        if model is None:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        try:
            text = await transcribe(
                self.entry.runtime_data.client,
                audio,
                f"audio/{metadata.format.value}",
                model=model.upstream_id("low"),
                prompt=prompt,
            )
        except (AntigravityError, aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Transcription failed: %s", err)
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        if not text:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)
