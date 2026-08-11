"""Tests for application_credentials.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.haier_home.application_credentials import async_get_authorization_server
from custom_components.haier_home.const import OAUTH2_AUTH_URL, OAUTH2_TOKEN_URL


class TestApplicationCredentials:
    """Test application credentials."""

    @pytest.mark.asyncio
    async def test_async_get_authorization_server(self):
        """Test async_get_authorization_server returns correct AuthorizationServer."""
        mock_hass = MagicMock()

        result = await async_get_authorization_server(mock_hass)

        assert result.authorize_url == OAUTH2_AUTH_URL
        assert result.token_url == OAUTH2_TOKEN_URL
