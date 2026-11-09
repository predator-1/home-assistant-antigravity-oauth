"""Constants for the Antigravity integration.

Endpoints, OAuth client and client identity mirror openclaw-antigravity-oauth
src/constants.ts. Do not change the OAuth client or CLI identity.
"""

from __future__ import annotations

import platform
import uuid

DOMAIN = "antigravity"
DEFAULT_TITLE = "Antigravity"

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
CONF_PROJECT_ID = "project_id"
CONF_EMAIL = "email"
CONF_TIER = "tier"
CONF_REDIRECT_URL = "redirect_url"

# Subentry options
CONF_CHAT_MODEL = "chat_model"
CONF_REASONING_EFFORT = "reasoning_effort"
CONF_WEB_SEARCH = "web_search"

SUBENTRY_CONVERSATION = "conversation"
SUBENTRY_AI_TASK = "ai_task_data"
SUBENTRY_STT = "stt"
DEFAULT_CONVERSATION_NAME = "Antigravity conversation"
DEFAULT_AI_TASK_NAME = "Antigravity AI Task"
DEFAULT_STT_NAME = "Antigravity STT"
DEFAULT_STT_PROMPT = "Transcribe the attached audio verbatim. Reply with the transcript only."
RECOMMENDED_CHAT_MODEL = "gemini-3.5-flash-lite"
"""Fastest for Assist (~1.5 s per command; docs/home-assistant.md#latency)."""
RECOMMENDED_REASONING_EFFORT = "low"
"""Used by models with effort variants; low keeps replies fast."""
REASONING_EFFORTS = ("low", "medium", "high")
WEB_SEARCH_TOOL = "web_search"

CLI_VERSION = "1.5.3"

DEFAULT_PROJECT_ID = "default-cli-project"

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo?alt=json"

API_BASE = "https://daily-cloudcode-pa.googleapis.com/v1internal"
LOAD_CODE_ASSIST_URL = f"{API_BASE}:loadCodeAssist"
MODELS_URL = f"{API_BASE}:fetchAvailableModels"
QUOTA_SUMMARY_URL = f"{API_BASE}:retrieveUserQuotaSummary"
USER_QUOTA_URL = f"{API_BASE}:retrieveUserQuota"
STREAM_URL = f"{API_BASE}:streamGenerateContent?alt=sse"

CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
CLIENT_SECRET = "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"
REDIRECT_URI = "http://localhost:51121/oauth-callback"

OAUTH_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/cclog",
        "https://www.googleapis.com/auth/experimentsandconfigs",
    ]
)

_GO_OS = {"win32": "windows", "sunos": "solaris"}
_GO_ARCH = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "i386": "386",
    "i686": "386",
    "armv7l": "arm",
}


def build_user_agent(system: str | None = None, machine: str | None = None) -> str:
    """Return agy's User-Agent with the honest host os/arch in Go naming."""
    os_name = (system if system is not None else platform.system()).lower() or "unknown"
    raw_arch = (machine if machine is not None else platform.machine()).lower()
    arch = _GO_ARCH.get(raw_arch, raw_arch or "unknown")
    return f"antigravity/cli/{CLI_VERSION} {_GO_OS.get(os_name, os_name)}/{arch}"


def build_api_headers(access_token: str) -> dict[str, str]:
    """Headers for every v1internal request."""
    return {
        "User-Agent": build_user_agent(),
        "x-activity-request-id": str(uuid.uuid4()),
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
