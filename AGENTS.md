# AGENTS.md

Home Assistant custom integration (HACS) for the Antigravity subscription. Python port of [openclaw-antigravity-oauth](https://github.com/predator-1/openclaw-antigravity-oauth); its `docs/` remain the reference for upstream behavior, this repo's `docs/` record only port-specific findings.

## Commands

```bash
uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m ruff format . && .venv/bin/python -m ruff check .   # before every commit
.venv/bin/python -m pytest -q                                           # hermetic, no network
.venv/bin/python scripts/smoke.py                                       # live, local only, uses quota
```

Layout: `custom_components/antigravity/api/` has no Home Assistant imports (auth, catalog, client, errors, quota, schema, search, turn); Home Assistant code sits beside it ([docs/home-assistant.md](docs/home-assistant.md)). `tests/` covers `api/`, `tests/ha/` the Home Assistant side; `tests/fixtures/` holds trimmed upstream payloads.

## Rules

- Target the latest Home Assistant 2026.x and Python 3.14; no compatibility code for older releases.
- Work on a branch; never force-push `main`. Commit as `predator-1 <predator-1@users.noreply.github.com>`.
- Never commit tokens, emails, project ids or raw API dumps (`.tmp/` is gitignored; fixtures are trimmed).
- Never log tokens, auth headers, emails or project ids.
- Do not change the OAuth client constants or the CLI identity in `const.py` (keep in step with the plugin's `src/constants.ts`).
- Never read or write `~/.gemini`. No native/server-side tools in chat turns: Home Assistant executes every tool; search is a separate grounded request.
- Findings go into `docs/*.md` by topic with date and evidence. No notes files.
