# Changelog

## 1.5.301

- The account device shows the subscription plan (for example Google AI Pro) instead of `free-tier`. Google reports the plan separately from the Antigravity tier; the plan is now read from there and refreshed on every start, so existing installs update without signing in again.

## 1.5.300

First release, for agy 1.5.3.

- Sign-in with the Google account that has the Antigravity subscription: open the sign-in link, paste the redirect URL. Reauth when the refresh token is revoked.
- Quota sensors: remaining percent and reset time for each usage window.
- Conversation agents: any subscription model with reasoning effort, Assist control, streamed replies and thinking, and Google Search as a tool that works together with Assist.
- AI Task: text and structured data (with attachments) and image generation.
- Speech-to-text for Assist voice pipelines.
- Requires Home Assistant 2026.10 or newer.
