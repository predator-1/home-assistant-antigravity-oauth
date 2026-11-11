import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.antigravity.api.auth import Eligibility, Tokens
from custom_components.antigravity.api.catalog import parse_catalog
from custom_components.antigravity.api.quota import parse_quota_summary
from custom_components.antigravity.const import (
    CONF_ACCESS_TOKEN,
    CONF_EMAIL,
    CONF_EXPIRES_AT,
    CONF_PROJECT_ID,
    CONF_REFRESH_TOKEN,
    CONF_TIER,
    DOMAIN,
)
from tests.conftest import load_fixture

EMAIL = "user@example.com"


@pytest.fixture(autouse=True)
async def auto_enable_custom_integrations(hass, enable_custom_integrations):
    # conversation (a dependency) needs the core integration's exposed-entities store.
    assert await async_setup_component(hass, "homeassistant", {})


@pytest.fixture
def entry_data():
    return {
        CONF_ACCESS_TOKEN: "access-1",
        CONF_REFRESH_TOKEN: "refresh-1",
        CONF_EXPIRES_AT: time.time() + 3600,
        CONF_PROJECT_ID: "proj-1",
        CONF_EMAIL: EMAIL,
        CONF_TIER: "free-tier",
    }


@pytest.fixture
def config_entry(hass, entry_data):
    entry = MockConfigEntry(domain=DOMAIN, title=EMAIL, unique_id=EMAIL, data=entry_data)
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def catalog():
    return parse_catalog(load_fixture("fetch_available_models.json"))


@pytest.fixture
def quota():
    return parse_quota_summary(load_fixture("quota_summary.json"))


@pytest.fixture
def mock_client(catalog, quota):
    with (
        patch(
            "custom_components.antigravity.api.client.AntigravityClient.fetch_catalog",
            new=AsyncMock(return_value=catalog),
        ) as fetch_catalog,
        patch(
            "custom_components.antigravity.api.client.AntigravityClient.fetch_quota",
            new=AsyncMock(return_value=quota),
        ) as fetch_quota,
        patch(
            "custom_components.antigravity.api.client.AntigravityClient.fetch_plan",
            new=AsyncMock(return_value="Google AI Pro"),
        ),
    ):
        yield fetch_catalog, fetch_quota


@pytest.fixture
def mock_sign_in():
    with (
        patch(
            "custom_components.antigravity.api.auth.exchange_code",
            new=AsyncMock(return_value=Tokens("access-2", "refresh-2", 3599)),
        ) as exchange,
        patch(
            "custom_components.antigravity.api.auth.check_eligibility",
            new=AsyncMock(return_value=Eligibility(project_id="proj-1", email=EMAIL, tier="Google AI Pro")),
        ) as eligibility,
    ):
        yield exchange, eligibility
