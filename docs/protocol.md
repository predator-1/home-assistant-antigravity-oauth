# Upstream protocol

Source of truth: [openclaw-antigravity-oauth docs/protocol.md](https://github.com/predator-1/openclaw-antigravity-oauth/blob/main/docs/protocol.md). Only findings specific to this port go here.

## Streaming from Python (2026-11-09, phase 0)

`aiohttp` against `v1internal:streamGenerateContent?alt=sse` works: `200 text/event-stream`, one JSON object per `data:` line, candidates under `response.candidates` (same `unwrapCandidates` rule).

- `gemini-3.8-flash-tiered`, `thinkingLevel: LOW`, "Reply with exactly: pong": 2 chunks, first token at 1.6 s, `finishReason: STOP`.
- Same model, `MEDIUM`, `includeThoughts: true`, 150-word prompt: 13 chunks; three `thought: true` parts (7.8–12.1 s) then 9 text chunks (12.2–13.1 s), each carrying cumulative `usageMetadata` (`thoughtsTokenCount` reported separately). Text arrives incrementally, so Home Assistant's streaming chat log can forward deltas as they come.
- The last chunk has empty text plus `finishReason`; skip empty text parts.

## Model catalog (2026-11-09)

`fetchAvailableModels` (`{"project"}`) returned 26 entries in `models` (a map keyed by slug; `model` holds the proto enum) plus routing lists. Differences from the OpenClaw plugin's assumptions:

- `agentModelSorts[].groups[].modelIds` is upstream's own agent picker: `gemini-4-argon-{low,medium,high}`, `gemini-3.8-flash-{low,medium,high}`, `claude-opus-5-5-{low,medium,high}`, `claude-sonnet-5-5-{low,medium,high}`, `gpt-oss-120b-medium`. The catalog uses it plus `tieredModelIds.flashLite` (`gemini-3.5-flash-lite`) instead of id-pattern filters, then collapses `-low|-medium|-high` into one model with efforts.
- Gemini 3.8 Flash now has its own `-low|-medium|-high` variants (proto `M318`–`M320`); Argon moved to `M417`–`M419`. The plugin's `PROTO_MODEL_ID_MAP` entries for M317–M320 are stale; this port does not map proto ids.
- `supportedMimeTypes` is a map `{mime: true}`, not a list.
- Routing: `defaultAgentModelId` `gemini-4-argon-medium`; `imageGenerationModelIds` `gemini-3.1-flash-image`; `tieredModelIds.flash` `gemini-3.8-flash-tiered` (used for search grounding).
- `displayName` is empty on `-tiered` and `chat_*`/`tab_*` entries and wrong on `gemini-2.5-*` (all "Gemini 3.5 Flash Lite"); none of those are in the picker.

Test fixture `tests/fixtures/fetch_available_models.json` is a trimmed copy (used fields only, five MIME types).

## Quota (2026-11-09)

`retrieveUserQuotaSummary` (`{}`): `groups[]` (`displayName`, `buckets[]`), each bucket `bucketId` (`gemini-weekly`, `gemini-5h`, `3p-weekly`, `3p-5h`, `gemini-argon-wtu-weekly`), `window` (`weekly`|`5h`), `resetTime`, `remainingFraction`, `displayName`, `description`. Group names: `Gemini Models`, `Claude and GPT models`, `Gemini 4 Argon`.

## Chat turns (2026-11-09, live probes on this account)

| request | result |
|---|---|
| `gemini-3.8-flash-low|high`, `gemini-4-argon-low`, no `generationConfig` or `thinkingConfig.includeThoughts` | 200; no thought parts on a one-word prompt; trailing empty text part carries `thoughtSignature` |
| `gemini-3.8-flash-tiered` + `thinkingLevel: MEDIUM`, longer prompt | thought parts streamed ([streaming](#streaming-from-python-2026-11-09-phase-0)) |
| `gemini-3.8-flash-tiered` + `thinkingLevel: EXTRA_HIGH` | 200 (accepted) |
| `claude-sonnet-5-5-low` with or without `includeThoughts` | 200; never returns thought parts |
| `gpt-oss-120b-medium` + `includeThoughts` | 200; many short thought parts, then text |
| `gemini-3.5-flash-lite` + `thinkingLevel: LOW` | 200; thought parts |
| `gemini-3.5-flash-lite` + `includeThoughts: false, thinkingBudget: 0` | 200 but still thinks and streams thoughts: thinking cannot be turned off |

Decision: effort is chosen only through the `-low|medium|high` upstream id; every request sends `thinkingConfig.includeThoughts: true` (harmless where unsupported); no `off` level.

Tool calls (one `get_weather` tool):

- Gemini: `functionCall {name, args, id: "call_<digits>"}` with `thoughtSignature` (≈360 chars) on the same part. Replaying that part with a `functionResponse` (same `id`): 200. Replaying without a signature: **400** `Function call is missing a thought_signature in functionCall parts`. Replaying with `skip_thought_signature_validator`: 200 on `gemini-3.8-flash-low` and `gemini-4-argon-low`. This settles the plugin's open "live multi-step prove".
- Claude: `functionCall {name, args, id: "toolu_vrtx_…"}`, no signature; replay without one: 200.

Google Search: `tools: [{googleSearch: {}}]` returns text and `groundingMetadata` (`webSearchQueries`, `groundingChunks[].web {uri,title}`) on `gemini-3.8-flash-tiered`, `gemini-3.8-flash-low` and `gemini-3.5-flash-lite`; flash-lite is ~5× faster ([latency](home-assistant.md#latency)).

## Image generation (2026-11-09)

`gemini-3.1-flash-image`, `generationConfig.responseModalities: ["TEXT", "IMAGE"]`, prompt only: 200 in 13 s, one `inlineData` `image/jpeg` part (~1 MB) and no text. The whole part arrives as **one SSE `data:` line larger than 512 KiB**, which overflows aiohttp's `StreamReader` line limit (`LineTooLong`); `client._sse_lines` splits the body itself.

## Audio input (2026-11-09)

A 2.3 s, 16 kHz 16-bit mono WAV sent as `inlineData` `audio/wav` with a "transcribe verbatim" prompt and `temperature: 0` was transcribed exactly by `gemini-3.5-flash-lite` (2.6 s), `gemini-3.8-flash-tiered` (3.0 s) and `gemini-3.8-flash-low` (3.3 s).
