# home-assistant-antigravity-oauth

Home Assistant custom integration (HACS) for the Google Antigravity subscription. Python port of [openclaw-antigravity-oauth](https://github.com/predator-1/openclaw-antigravity-oauth): OAuth sign-in, conversation agent with Assist tools and Google Search, AI Task (structured data, image generation, attachments), speech-to-text and quota sensors.

Unofficial: not affiliated with or endorsed by Google.

Status: in development. Requires Home Assistant 2026.10 or newer.

## Install (HACS, private repository for now)

1. HACS → ⋮ → Custom repositories → add this repository as an *Integration*.
2. Install **Antigravity**, restart Home Assistant.
3. Settings → Devices & services → Add integration → **Antigravity**. Open the Google sign-in link, sign in, then copy the address of the page that fails to load (`http://localhost:51121/oauth-callback?...`) and paste it into the form.

Docs: [docs/home-assistant.md](docs/home-assistant.md), [docs/auth.md](docs/auth.md), [docs/protocol.md](docs/protocol.md). Contributor rules: [AGENTS.md](AGENTS.md).
