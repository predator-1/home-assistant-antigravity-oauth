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

## Entities

Account device (service, manufacturer Google, model = tier). Per quota window (`QuotaWindow.key` = upstream `bucketId`): `… remaining` (%, measurement) and `… reset` (timestamp). Names come from translation placeholders `{group} {window}`, e.g. `sensor.antigravity_gemini_models_weekly_remaining`.

## Live check (2026-11-09, HA 2026.11.1, macOS arm64)

Fresh config dir, entry seeded from the phase-0 login with `expires_at` in the past: entry `loaded`; token refreshed on first call and persisted (expires in 3592 s); catalog 0.87 s, quota 0.74 s; all 10 sensors created with live values. Config flow over the REST API: `authorize` form with the Google URL; a stale paste returned `invalid_auth`. No integration errors in the log.
