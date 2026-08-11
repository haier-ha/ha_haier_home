"""Tests for haier/oauth2.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.haier_home.haier.http_client import HaierAPIError
from custom_components.haier_home.haier.oauth2 import HaierOAuth2Implementation


class TestHaierOAuth2ImplementationProperties:
    """Test HaierOAuth2Implementation properties."""

    def test_name(self):
        """Test name property."""
        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")
        assert impl.name == "Haier Home (cn)"

    def test_domain(self):
        """Test domain property."""
        from custom_components.haier_home.const import DOMAIN

        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")
        assert impl.domain == DOMAIN

    def test_client_id(self):
        """Test client_id property."""
        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "test_client_id", "cn")
        assert impl.client_id == "test_client_id"

    def test_authorize_url(self):
        """Test authorize_url property."""
        from custom_components.haier_home.const import OAUTH2_AUTH_URL

        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")
        assert impl.authorize_url == OAUTH2_AUTH_URL

    def test_token_url(self):
        """Test token_url property."""
        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")
        assert "ha.haier.net" in impl.token_url
        assert "/api-gw/ha/se/account/token" in impl.token_url

    def test_scope(self):
        """Test scope property."""
        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")
        assert impl.scope == []

    def test_redirect_uri(self):
        """Test redirect_uri property."""
        from custom_components.haier_home.const import OAUTH2_CALLBACK_URL

        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")
        assert impl.redirect_uri == OAUTH2_CALLBACK_URL


class TestHaierOAuth2ImplementationGenerateAuthorizeUrl:
    """Test async_generate_authorize_url method."""

    @pytest.mark.asyncio
    async def test_generate_authorize_url(self):
        """Test generating authorize URL."""
        from custom_components.haier_home.const import OAUTH2_AUTH_URL, OAUTH2_CLIENT_ID

        hass = SimpleNamespace()

        def mock_encode_jwt(hass, data):
            return "encoded_jwt_state"

        impl = HaierOAuth2Implementation(hass, "client_id", "cn")

        with patch("homeassistant.helpers.config_entry_oauth2_flow._encode_jwt", mock_encode_jwt):
            url = await impl.async_generate_authorize_url("flow_001")

        assert OAUTH2_AUTH_URL in url
        assert "client_id=" + OAUTH2_CLIENT_ID in url
        assert "response_type=code" in url
        assert "state=encoded_jwt_state" in url


class TestHaierOAuth2ImplementationResolveExternalData:
    """Test async_resolve_external_data method."""

    @pytest.mark.asyncio
    async def test_resolve_external_data_success(self):
        """Test successful token resolution."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value={
                "retCode": "00000",
                "data": {
                    "accessToken": "new_access_token",
                    "refreshToken": "new_refresh_token",
                    "expiresIn": "7200",
                },
            }
        )

        class MockResponse:
            async def __aenter__(self):
                return mock_response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class MockClientSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            def post(self, *args, **kwargs):
                return MockResponse()

        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")

        with patch(
            "custom_components.haier_home.haier.oauth2.async_get_clientsession",
            return_value=MockClientSession(),
        ):
            result = await impl.async_resolve_external_data({"code": "auth_code"})

        assert result["access_token"] == "new_access_token"
        assert result["refresh_token"] == "new_refresh_token"
        assert result["expires_in"] == 7200

    @pytest.mark.asyncio
    async def test_resolve_external_data_no_code(self):
        """Test error when no code in external data."""
        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")

        with pytest.raises(Exception, match="Missing 'code' in OAuth callback data"):
            await impl.async_resolve_external_data({})

    @pytest.mark.asyncio
    async def test_resolve_external_data_api_error(self):
        """Test API error handling."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value={
                "retCode": "99999",
                "retInfo": "Invalid code",
            }
        )

        class MockResponse:
            async def __aenter__(self):
                return mock_response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class MockClientSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            def post(self, *args, **kwargs):
                return MockResponse()

        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")

        with patch(
            "custom_components.haier_home.haier.oauth2.async_get_clientsession",
            return_value=MockClientSession(),
        ):
            with pytest.raises(HaierAPIError):
                await impl.async_resolve_external_data({"code": "invalid_code"})


class TestHaierOAuth2ImplementationRefreshToken:
    """Test _async_refresh_token method."""

    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
        """Test successful token refresh."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value={
                "retCode": "00000",
                "data": {
                    "accessToken": "refreshed_access_token",
                    "refreshToken": "refreshed_refresh_token",
                    "expiresIn": "7200",
                },
            }
        )

        class MockResponse:
            async def __aenter__(self):
                return mock_response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class MockClientSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            def post(self, *args, **kwargs):
                return MockResponse()

        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")

        with patch(
            "custom_components.haier_home.haier.oauth2.async_get_clientsession",
            return_value=MockClientSession(),
        ):
            result = await impl._async_refresh_token({"refresh_token": "old_refresh_token"})

        assert result["access_token"] == "refreshed_access_token"
        assert result["refresh_token"] == "refreshed_refresh_token"
        assert result["expires_in"] == 7200

    @pytest.mark.asyncio
    async def test_refresh_token_api_error(self):
        """Test API error handling during token refresh."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value={
                "retCode": "99999",
                "retInfo": "Invalid refresh token",
            }
        )

        class MockResponse:
            async def __aenter__(self):
                return mock_response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class MockClientSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            def post(self, *args, **kwargs):
                return MockResponse()

        hass = SimpleNamespace()
        impl = HaierOAuth2Implementation(hass, "client_id", "cn")

        with patch(
            "custom_components.haier_home.haier.oauth2.async_get_clientsession",
            return_value=MockClientSession(),
        ):
            with pytest.raises(HaierAPIError):
                await impl._async_refresh_token({"refresh_token": "invalid_refresh_token"})
