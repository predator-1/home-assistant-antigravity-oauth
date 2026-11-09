# Upstream sync

The OpenClaw plugin repository investigates every agy release (binary fingerprint, changelog, live smoke) and records the outcome in its `src/constants.ts`. This port follows that file instead of repeating the analysis.

`scripts/sync_upstream.py` compares `custom_components/antigravity/const.py` with the plugin's `main` (`--plugin-constants` takes a local path instead):

| exit | verdict | meaning | action |
|---|---|---|---|
| 0 | NO_CHANGE | in step | none |
| 10 | SAFE | only `CLI_VERSION` changed | `python scripts/sync_upstream.py --apply`, run tests and `scripts/smoke.py`, bump `manifest.json` version, CHANGELOG entry, release |
| 20 | REVIEW_NEEDED | OAuth client, secret (SHA-256), redirect URI, scopes or API host changed | read the plugin's matching investigation issue and `docs/protocol.md`, port by hand |
| 30 | ERROR | source unreachable or a constant missing | fix the parser |

`.github/workflows/upstream.yml` runs it daily and opens one issue while constants differ. The client secret is compared by hash and never printed.

Other upstream facts the plugin learns (model ids, request shapes) do not live in its constants; check its `docs/protocol.md` changes when the issue opens.
