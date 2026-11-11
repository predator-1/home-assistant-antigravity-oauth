# home-assistant-antigravity-oauth

Home Assistant custom integration (HACS) for the Google Antigravity subscription. Python port of [openclaw-antigravity-oauth](https://github.com/predator-1/openclaw-antigravity-oauth): OAuth sign-in, conversation agent with Assist tools and Google Search, AI Task (structured data, image generation, attachments), speech-to-text and quota sensors.

Unofficial: not affiliated with or endorsed by Google.

Requires Home Assistant 2026.10 or newer and [HACS](https://hacs.xyz/docs/use/).

## Install

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=predator-1&repository=home-assistant-antigravity-oauth&category=integration)

1. Click the button above (or HACS → ⋮ → Custom repositories → add `https://github.com/predator-1/home-assistant-antigravity-oauth`, type *Integration*).
2. **Download** Antigravity in HACS and restart Home Assistant.
3. [![Add the Antigravity integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=antigravity) (or Settings → Devices & services → Add integration → **Antigravity**).
4. Open the Google sign-in link, sign in with the account that has the subscription, then copy the address of the page that fails to load (`http://localhost:51121/oauth-callback?...`) and paste it into the form.

Sign-in creates a conversation agent, an AI Task entity and a speech-to-text entity; add more under the integration (⋮ → Add …). Updates arrive through HACS. Versions follow agy: agy 1.5.3 → `1.5.300` ([versioning](docs/upstream-sync.md#versioning)).

Docs: [docs/home-assistant.md](docs/home-assistant.md), [docs/auth.md](docs/auth.md), [docs/protocol.md](docs/protocol.md). Contributor rules: [AGENTS.md](AGENTS.md).
