# Auth

Same OAuth client, scopes and eligibility check as [openclaw-antigravity-oauth docs/auth.md](https://github.com/predator-1/openclaw-antigravity-oauth/blob/main/docs/auth.md). Code: `custom_components/antigravity/api/auth.py`.

## Sign-in flow (decided 2026-11-09, phase 0)

- **Device code: not available.** `POST oauth2.googleapis.com/device/code` with agy's client returns `401 invalid_client: Invalid client type` (Desktop/installed client).
- **Home Assistant's standard OAuth2 flow: not usable.** It redirects to `my.home-assistant.io`; agy's client only accepts `http://localhost:51121/oauth-callback`.
- **Used: PKCE `S256` with paste-back.** The config flow shows the authorize URL; the user signs in, the browser lands on `localhost:51121/oauth-callback?...` (page fails to load, expected), and the user pastes that URL (or the bare code) into the form. `parse_callback_input` checks `state`.

Evidence (2026-11-09, `scripts/spike_phase0.py`, macOS arm64, Python 3.14.9, aiohttp 3.14.5, UA `antigravity/cli/1.5.3 darwin/arm64`): paste-back exchange 200 (`expires_in` 3599 s, refresh token issued); Google appends `openid` to the granted scopes; `loadCodeAssist` 200 with `currentTier.id` `free-tier` and a managed `cloudaicompanionProject`; userinfo returned an email; `refresh_token` grant 200.

## Tiers (2026-11-11)

`currentTier` is not the subscription. For a Google AI Pro account `loadCodeAssist` returned `currentTier` `{id: free-tier, name: Antigravity}` (as in phase 0 above) and the plan separately in `paidTier` `{id: g1-pro-tier, name: Google AI Pro}` (plus `availableCredits`); `allowedTiers` was `free-tier`, `standard-tier`. The plugin reads only `currentTier`.

The integration stores `paidTier.name`, falling back to its id, then `currentTier` (`plan_name` in `api/auth.py`), as `tier`, shown as the account device's model. Setup calls `loadCodeAssist` again and updates the stored plan, so upgrades, cancellations and entries created before this fix are picked up without a new sign-in; a failure there keeps the stored value and does not block setup.

Evidence: live `loadCodeAssist` (`ideType: ANTIGRAVITY`), 200, response keys `allowedTiers`, `cloudaicompanionProject`, `currentTier`, `gcpManaged` (false), `paidTier`, `upgradeSubscriptionUri`.

## Storage and refresh

Tokens, expiry and project id live in the config entry data. Refresh before expiry; `invalid_grant` raises `ConfigEntryAuthFailed`, which starts Home Assistant's reauth flow (same paste-back form). Never log tokens, emails or project ids.
