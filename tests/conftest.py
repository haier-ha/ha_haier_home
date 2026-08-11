"""Shared test fixtures for Haier Home tests.

Uses the Home Assistant custom-component test harness
(``pytest_homeassistant_custom_component``) so tests run against the real
Home Assistant framework instead of hand-rolled ``sys.modules`` mocks.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.mock_data import create_mock_ac_device, create_mock_coordinator  # noqa: E402


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration under test."""
    yield


@pytest.fixture
def mock_ac_device():
    return create_mock_ac_device()


@pytest.fixture
def mock_coordinator():
    return create_mock_coordinator()
