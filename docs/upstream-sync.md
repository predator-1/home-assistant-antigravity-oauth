# Upstream sync

The OpenClaw plugin repository investigates every agy release (binary fingerprint, changelog, live smoke) and records the outcome in its `src/constants.ts`. This port follows that file instead of repeating the analysis.

`scripts/sync_upstream.py` compares `custom_components/antigravity/const.py` with the plugin's `main` (`--plugin-constants` takes a local path instead):

| exit | verdict | meaning | action |
|---|---|---|---|
| 0 | NO_CHANGE | in step | none |
| 10 | SAFE | only `CLI_VERSION` changed | `python scripts/sync_upstream.py --apply` (also sets the manifest version), run tests and `scripts/smoke.py`, CHANGELOG entry, release |
| 20 | REVIEW_NEEDED | OAuth client, secret (SHA-256), redirect URI, scopes or API host changed | read the plugin's matching investigation issue and `docs/protocol.md`, port by hand |
| 30 | ERROR | source unreachable or a constant missing | fix the parser |

`.github/workflows/upstream.yml` runs it daily and opens one issue while constants differ. The client secret is compared by hash and never printed.

Other upstream facts the plugin learns (model ids, request shapes) do not live in its constants; check its `docs/protocol.md` changes when the issue opens.

## Versioning

Same scheme as the plugin ([its install-and-release.md](https://github.com/predator-1/openclaw-antigravity-oauth/blob/main/docs/install-and-release.md#versioning)):

```
version = <agyMajor>.<agyMinor>.<agyPatch * 100 + fix>     fix = 00..99
```

agy 1.5.3 → `1.5.300`; integration-only fixes → `1.5.301`, `1.5.302`; agy 1.5.4 → `1.5.400`. The tag is `v<version>`. `tests/test_sync_upstream.py` fails if `manifest.json` and `CLI_VERSION` disagree. The plugin and this integration share the agy part but count fixes independently.
