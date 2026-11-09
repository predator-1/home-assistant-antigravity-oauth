# Upstream protocol

Source of truth: [openclaw-antigravity-oauth docs/protocol.md](https://github.com/predator-1/openclaw-antigravity-oauth/blob/main/docs/protocol.md). Only findings specific to this port go here.

## Streaming from Python (2026-11-09, phase 0)

`aiohttp` against `v1internal:streamGenerateContent?alt=sse` works: `200 text/event-stream`, one JSON object per `data:` line, candidates under `response.candidates` (same `unwrapCandidates` rule).

- `gemini-3.8-flash-tiered`, `thinkingLevel: LOW`, "Reply with exactly: pong": 2 chunks, first token at 1.6 s, `finishReason: STOP`.
- Same model, `MEDIUM`, `includeThoughts: true`, 150-word prompt: 13 chunks; three `thought: true` parts (7.8–12.1 s) then 9 text chunks (12.2–13.1 s), each carrying cumulative `usageMetadata` (`thoughtsTokenCount` reported separately). Text arrives incrementally, so Home Assistant's streaming chat log can forward deltas as they come.
- The last chunk has empty text plus `finishReason`; skip empty text parts.
