"""Compare const.py with the OpenClaw plugin's src/constants.ts (the agy investigation lives there).

  python scripts/sync_upstream.py [--plugin-constants PATH_OR_URL] [--apply] [--json]

Exit codes: 0 no change, 10 only CLI_VERSION changed (safe; --apply writes it and sets the
manifest version to <agyMajor>.<agyMinor>.<agyPatch*100>, docs/upstream-sync.md#versioning),
20 OAuth client, scopes, redirect or endpoints changed (review by hand), 30 error.
Secrets are never printed; the client secret is compared by SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONST = ROOT / "custom_components" / "antigravity" / "const.py"
MANIFEST = ROOT / "custom_components" / "antigravity" / "manifest.json"
DEFAULT_SOURCE = "https://raw.githubusercontent.com/predator-1/openclaw-antigravity-oauth/main/src/constants.ts"

FIELDS = ("cli_version", "client_id", "client_secret_sha256", "redirect_uri", "scopes", "api_hosts")


def _one(pattern: str, text: str, name: str) -> str:
    match = re.search(pattern, text, re.S)
    if not match:
        raise ValueError(f"{name} not found")
    return match[1]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def parse_plugin(ts: str) -> dict[str, object]:
    scopes_block = _one(r"OAUTH_SCOPES\s*=\s*\[(.*?)\]", ts, "OAUTH_SCOPES")
    return {
        "cli_version": _one(r'CLI_VERSION\s*=\s*"([^"]+)"', ts, "CLI_VERSION"),
        "client_id": _one(r'clientId:\s*"([^"]+)"', ts, "clientId"),
        "client_secret_sha256": _sha(_one(r'clientSecret:\s*"([^"]+)"', ts, "clientSecret")),
        "redirect_uri": _one(r'loopbackRedirectUri:\s*"([^"]+)"', ts, "loopbackRedirectUri"),
        "scopes": sorted(re.findall(r'"(https://[^"]+)"', scopes_block)),
        "api_hosts": sorted(set(re.findall(r'"https://([a-z0-9.-]+)/v1internal:', ts))),
    }


def parse_const(py: str) -> dict[str, object]:
    scopes_block = _one(r"OAUTH_SCOPES\s*=\s*\"\s*\"\.join\(\s*\[(.*?)\]", py, "OAUTH_SCOPES")
    return {
        "cli_version": _one(r'CLI_VERSION\s*=\s*"([^"]+)"', py, "CLI_VERSION"),
        "client_id": _one(r'CLIENT_ID\s*=\s*"([^"]+)"', py, "CLIENT_ID"),
        "client_secret_sha256": _sha(_one(r'CLIENT_SECRET\s*=\s*"([^"]+)"', py, "CLIENT_SECRET")),
        "redirect_uri": _one(r'REDIRECT_URI\s*=\s*"([^"]+)"', py, "REDIRECT_URI"),
        "scopes": sorted(re.findall(r'"(https://[^"]+)"', scopes_block)),
        "api_hosts": sorted({_one(r'API_BASE\s*=\s*"https://([a-z0-9.-]+)/v1internal"', py, "API_BASE")}),
    }


def integration_version(cli_version: str, fix: int = 0) -> str:
    """agy 1.5.3 -> 1.5.300; plugin-only fixes count up the last two digits (same as the plugin)."""
    major, minor, patch = (int(p) for p in cli_version.split("."))
    if not 0 <= fix <= 99:
        raise ValueError("fix must be 0..99")
    return f"{major}.{minor}.{patch * 100 + fix}"


def compare(plugin: dict[str, object], ours: dict[str, object]) -> tuple[int, dict[str, tuple[object, object]]]:
    changed = {f: (ours[f], plugin[f]) for f in FIELDS if ours[f] != plugin[f]}
    if not changed:
        return 0, changed
    return (10 if set(changed) == {"cli_version"} else 20), changed


def _read(source: str) -> str:
    if source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=30) as resp:
            return resp.read().decode()
    return Path(source).read_text()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plugin-constants", default=DEFAULT_SOURCE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        plugin = parse_plugin(_read(args.plugin_constants))
        const_text = CONST.read_text()
        ours = parse_const(const_text)
    except (OSError, ValueError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 30
    verdict, changed = compare(plugin, ours)
    applied = False
    if args.apply and verdict == 10:
        CONST.write_text(
            re.sub(r'CLI_VERSION = "[^"]+"', f'CLI_VERSION = "{plugin["cli_version"]}"', const_text, count=1)
        )
        manifest = json.loads(MANIFEST.read_text())
        manifest["version"] = integration_version(str(plugin["cli_version"]))
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
        applied = True
    if args.json:
        print(json.dumps({"verdict": verdict, "changed": changed, "applied": applied}, indent=2))
    else:
        names = {0: "NO_CHANGE", 10: "SAFE", 20: "REVIEW_NEEDED"}
        print(f"{names[verdict]} ({verdict})")
        for field, (old, new) in changed.items():
            print(f"  {field}: {old} -> {new}")
        if applied:
            print(f"  applied: CLI_VERSION = {plugin['cli_version']}, version = {manifest['version']}")
    return verdict


if __name__ == "__main__":
    sys.exit(main())
