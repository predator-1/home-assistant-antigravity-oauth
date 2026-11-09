"""Image generation and audio transcription.

Ports of openclaw-antigravity-oauth src/image.ts and the audio path of src/media.ts.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from .client import AntigravityClient, InlineData
from .errors import UpstreamError

DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"
IMAGE_TIMEOUT = 180
INLINE_REQUEST_MAX_BYTES = 20 * 1024 * 1024
"""Gemini's whole-request inline limit; there is no upload path on v1internal (docs/protocol.md)."""
INLINE_MAX_BYTES = (INLINE_REQUEST_MAX_BYTES - 256 * 1024) * 3 // 4
"""Raw bytes that still fit after base64 (4/3 growth) with a 256 KiB envelope reserve."""


@dataclass(frozen=True)
class GeneratedImage:
    image: InlineData
    text: str
    model: str


def inline_part(mime_type: str, data: bytes) -> dict[str, dict[str, str]]:
    return {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(data).decode("ascii")}}


def check_inline_size(total_bytes: int) -> None:
    if total_bytes > INLINE_MAX_BYTES:
        raise UpstreamError(
            f"Attachments are {total_bytes} bytes; the limit is {INLINE_MAX_BYTES} bytes "
            "(about 20 MiB per request after base64)"
        )


async def generate_image(
    client: AntigravityClient,
    prompt: str,
    images: list[tuple[str, bytes]] | None = None,
    *,
    model: str = DEFAULT_IMAGE_MODEL,
    timeout: float = IMAGE_TIMEOUT,
) -> GeneratedImage:
    """One image from a prompt and optional input images (edit). Retries once on an empty reply."""
    images = images or []
    check_inline_size(sum(len(data) for _, data in images))
    request = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}, *(inline_part(mime, data) for mime, data in images)]}
        ],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    for _attempt in range(2):
        result = await client.generate(model, request, timeout=timeout)
        found = [d for d in result.inline_data if d.mime_type.startswith("image/")]
        if found:
            return GeneratedImage(found[0], result.text.strip(), model)
        if result.finish_reason not in ("STOP", None):
            break
    raise UpstreamError(f"No image in the response (finish reason {result.finish_reason}): {result.text[:200]}")


async def transcribe(
    client: AntigravityClient,
    audio: bytes,
    mime_type: str,
    *,
    model: str,
    prompt: str,
    timeout: float = 60,
) -> str:
    check_inline_size(len(audio))
    request = {
        "contents": [{"role": "user", "parts": [{"text": prompt}, inline_part(mime_type, audio)]}],
        "generationConfig": {"temperature": 0},
    }
    return (await client.generate(model, request, timeout=timeout)).text.strip()
