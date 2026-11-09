# Home Assistant integration

Domain `antigravity`, HACS only, minimum Home Assistant 2026.10 (test harness `pytest-homeassistant-custom-component` 0.13.375 = HA 2026.10.4; live-checked on 2026.11.1).

## Config entry

- One entry per Google account; `unique_id` = lowercased email (project id if userinfo returned none); title = email.
- `data`: `access_token`, `refresh_token`, `expires_at` (epoch s), `project_id`, `email`, `tier`. Nothing in `options`.
- Setup (`__init__.py`): `TokenManager` (`session.py`) → `AntigravityClient` → `CatalogCoordinator` (6 h) and `QuotaCoordinator` (5 min); both first refreshes must succeed. `runtime_data` = `AntigravityData`.
- Errors: `AuthError` → `ConfigEntryAuthFailed` (reauth flow); network / other upstream errors → `UpdateFailed` (`SETUP_RETRY` at startup).

## Tokens

`TokenManager.async_get_token(force)` refreshes when fewer than 120 s remain or after a 401 (the client's single retry), under one lock, and writes the new tokens into `entry.data`. `invalid_grant` starts reauth.

Writing `entry.data` fires update listeners. The entry listener reloads only when the subentry snapshot (titles and data) changed, so token refreshes never reload. Because of that listener, reauth updates data and calls `async_schedule_reload` itself instead of `async_update_reload_and_abort` (HA reports that combination; it becomes an error in 2026.12); subentry reconfigure must use `async_update_and_abort` and let the listener reload.

## Config flow

`authorize` step: shows the PKCE sign-in URL (`auth_url` placeholder) and one text field `redirect_url`. Accepts the pasted redirect URL or a bare code. Bad paste / failed exchange → `invalid_auth` and a fresh PKCE session (new URL). Not eligible → abort `not_eligible`. Reauth: `reauth_confirm` → `authorize`; a different account aborts `wrong_account`.

## Conversation agents

One `conversation` subentry per agent (default one created at sign-in). Options: `chat_model` (catalog id), `reasoning_effort` (`low|medium|high`, mapped to the upstream `-low|medium|high` id; ignored by single-id models), `prompt`, `llm_hass_api`, `web_search`.

Each turn (`llm_entity.py`): Home Assistant tools (`probatio.to_openapi`) plus, when enabled, a `web_search` tool → `build_tools`; contents rebuilt from the chat log every iteration (max 10); tool results grouped into one user turn of `functionResponse` parts. Gemini thought signatures are kept in `AssistantContent.native` (`AntigravityNative`, keyed by tool-call id with the producing model id) and replayed only for the same model, else the sentinel. `web_search` calls are `ToolInput(external=True)`: the entity runs `api.search.web_search` itself on `catalog.search_model` and streams a `tool_result` delta, so search works with or without Assist (the core Google integration cannot combine its search tool with Assist). Finish reasons other than `STOP`/`MAX_TOKENS` raise `response_blocked`; quota exhaustion says when the window resets. Every turn requests a (debounced) quota refresh.

## Latency

Live, HA 2026.11.1, Assist API, one exposed `input_boolean`, "Turn on/off the desk lamp" (two runs each, 2026-11-09):

| agent model | seconds |
|---|---|
| `gemini-3.5-flash-lite` | 1.3 / 1.7 |
| `claude-sonnet-5-5` (low) | 2.0 / 2.2 |
| `gemini-3.8-flash` (low) | 5.7 / 4.9 |
| `gemini-4-argon` (low) | 8.8 / 7.7 |

Decision: new agents default to `gemini-3.5-flash-lite`.

Search grounding alone (direct `web_search`, two queries each): `gemini-3.5-flash-lite` 1.5–1.6 s, `gemini-3.8-flash-tiered` 8.2–8.5 s, `gemini-3.8-flash-low` 8.1–8.4 s; answers and source counts comparable. Decision: search uses `webSearchModelIds` (flash-lite), which upstream also routes search to; the OpenClaw plugin still sends `gemini-3.8-flash-tiered`. End to end, "search the web: who won the last Grand Prix" on the 3.8 Flash agent went from 34.9 s to 9.4 s.

Live checks in the same run: both Gemini 3.8 Flash and Claude Sonnet agents turned the lamp on and off and answered state questions; both used `web_search` and answered with sources. With nothing exposed, agents correctly reply that entities must be exposed.

## Entities

Account device (service, manufacturer Google, model = tier). Per quota window (`QuotaWindow.key` = upstream `bucketId`): `… remaining` (%, measurement) and `… reset` (timestamp). Names come from translation placeholders `{group} {window}`, e.g. `sensor.antigravity_gemini_models_weekly_remaining`.

## Live check (2026-11-09, HA 2026.11.1, macOS arm64)

Fresh config dir, entry seeded from the phase-0 login with `expires_at` in the past: entry `loaded`; token refreshed on first call and persisted (expires in 3592 s); catalog 0.87 s, quota 0.74 s; all 10 sensors created with live values. Config flow over the REST API: `authorize` form with the Google URL; a stale paste returned `invalid_auth`. No integration errors in the log.
