import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def models_payload():
    return load_fixture("fetch_available_models.json")


@pytest.fixture
def quota_payload():
    return load_fixture("quota_summary.json")
