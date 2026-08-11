"""Tests for config_flow.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.haier_home.config_flow import HaierHomeConfigFlow


class TestConfigFlowEulaStep:
    """Test async_step_eula."""

    @pytest.mark.asyncio
    async def test_eula_step_show_form(self):
        """Test eula step shows form."""
        mock_hass = MagicMock()
        mock_hass.config.language = "zh-Hans"

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass

        with patch(
            "custom_components.haier_home.config_flow.HaierHttpClient"
        ) as mock_http_client_class:
            mock_http_client = MagicMock()
            mock_http_client.get_risk_notice = AsyncMock(return_value="EULA text")
            mock_http_client_class.return_value = mock_http_client

            result = await flow.async_step_eula()

            assert result["type"] == "form"
            assert result["step_id"] == "eula"

    @pytest.mark.asyncio
    async def test_eula_step_accepted(self):
        """Test eula step accepted redirects to region."""
        mock_hass = MagicMock()
        mock_hass.config.language = "zh-Hans"

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass
        flow._eula_text = "EULA text"

        result = await flow.async_step_eula(user_input={"eula_accepted": True})

        assert result["type"] == "form"
        assert result["step_id"] == "region"

    @pytest.mark.asyncio
    async def test_eula_step_not_accepted(self):
        """Test eula step not accepted shows error."""
        mock_hass = MagicMock()
        mock_hass.config.language = "zh-Hans"

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass
        flow._eula_text = "EULA text"

        result = await flow.async_step_eula(user_input={"eula_accepted": False})

        assert result["type"] == "form"
        assert result["step_id"] == "eula"
        assert result["errors"]["base"] == "eula_not_accepted"

    @pytest.mark.asyncio
    async def test_eula_step_fetch_failure(self):
        """Test eula step fetch failure aborts."""
        mock_hass = MagicMock()
        mock_hass.config.language = "en"

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass

        with patch(
            "custom_components.haier_home.config_flow.HaierHttpClient"
        ) as mock_http_client_class:
            mock_http_client = MagicMock()
            mock_http_client.get_risk_notice = AsyncMock(side_effect=Exception("Network error"))
            mock_http_client_class.return_value = mock_http_client

            result = await flow.async_step_eula()

            assert result["type"] == "abort"
            assert result["reason"] == "risk_notice_error"


class TestConfigFlowRegionStep:
    """Test async_step_region."""

    @pytest.mark.asyncio
    async def test_region_step_show_form(self):
        """Test region step shows form."""
        mock_hass = MagicMock()

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass

        result = await flow.async_step_region()

        assert result["type"] == "form"
        assert result["step_id"] == "region"

    @pytest.mark.asyncio
    async def test_region_step_submit(self):
        """Test region step submit redirects to oauth."""
        mock_hass = MagicMock()

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass

        # This test verifies HaierHomeConfigFlow's own region logic, not HA's
        # OAuth2 flow machinery. Stub the inherited handler that would
        # otherwise drive the real OAuth2 authorization.
        with patch.object(
            HaierHomeConfigFlow,
            "async_step_pick_implementation",
            AsyncMock(return_value={"type": "form", "step_id": "pick_implementation"}),
        ):
            result = await flow.async_step_region(
                user_input={"region": "cn", "language": "zh-Hans"}
            )

        assert flow._region == "cn"
        assert flow._language == "zh-Hans"
        assert result["type"] == "form"
        assert result["step_id"] == "pick_implementation"


class TestConfigFlowOauthStep:
    """Test async_step_oauth."""

    @pytest.mark.asyncio
    async def test_oauth_step(self):
        """Test oauth step creates implementation."""
        mock_hass = MagicMock()

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass
        flow._region = "cn"

        # Same isolation as test_region_step_submit: verify the OAuth
        # preparation logic without driving HA's real OAuth2 flow.
        with patch.object(
            HaierHomeConfigFlow,
            "async_step_pick_implementation",
            AsyncMock(return_value={"type": "form", "step_id": "pick_implementation"}),
        ):
            result = await flow.async_step_oauth()

        assert flow._ag_client_id != ""
        assert result["type"] == "form"
        assert result["step_id"] == "pick_implementation"


class TestConfigFlowOauthCreateEntry:
    """Test async_oauth_create_entry."""

    @pytest.mark.asyncio
    async def test_oauth_create_entry_success(self):
        """Test oauth_create_entry success."""
        mock_hass = MagicMock()

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass
        flow._region = "cn"
        flow._language = "zh-Hans"
        flow._ag_client_id = "test_client_id"

        with patch(
            "custom_components.haier_home.config_flow.HaierHttpClient"
        ) as mock_http_client_class:
            mock_http_client = MagicMock()
            mock_http_client.get_account_info = AsyncMock(
                return_value={"userId": "123", "nickName": "Test"}
            )
            mock_http_client_class.return_value = mock_http_client

            result = await flow.async_oauth_create_entry(
                data={
                    "token": {
                        "access_token": "test_token",
                        "refresh_token": "test_refresh_token",
                        "expires_in": 7200,
                        "expires_at": 9999999999,
                    },
                    "auth_implementation": "test_impl",
                }
            )

            assert flow._uid == "123"
            assert flow._nickname == "Test"
            assert result["type"] == "form"
            assert result["step_id"] == "homes"

    @pytest.mark.asyncio
    async def test_oauth_create_entry_failure(self):
        """Test oauth_create_entry failure."""
        mock_hass = MagicMock()

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass
        flow._region = "cn"
        flow._language = "zh-Hans"
        flow._ag_client_id = "test_client_id"

        with patch(
            "custom_components.haier_home.config_flow.HaierHttpClient"
        ) as mock_http_client_class:
            mock_http_client = MagicMock()
            mock_http_client.get_account_info = AsyncMock(side_effect=Exception("API error"))
            mock_http_client_class.return_value = mock_http_client

            result = await flow.async_oauth_create_entry(
                data={
                    "token": {
                        "access_token": "test_token",
                        "refresh_token": "test_refresh_token",
                        "expires_in": 7200,
                        "expires_at": 9999999999,
                    },
                    "auth_implementation": "test_impl",
                }
            )

            assert result["type"] == "abort"
            assert result["reason"] == "oauth_token_error"


class TestConfigFlowHomesStep:
    """Test async_step_homes."""

    @pytest.mark.asyncio
    async def test_homes_step_no_client(self):
        """Test homes step aborts when no client."""
        mock_hass = MagicMock()

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass

        result = await flow.async_step_homes()

        assert result["type"] == "abort"
        assert result["reason"] == "no_client"

    @pytest.mark.asyncio
    async def test_homes_step_show_form(self):
        """Test homes step shows form."""
        mock_hass = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.get_homes = AsyncMock(
            return_value={"createfamilies": [{"familyId": "f1", "familyName": "Home 1"}]}
        )

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass
        flow._http_client = mock_http_client
        flow._language = "en"

        result = await flow.async_step_homes()

        assert result["type"] == "form"
        assert result["step_id"] == "homes"

    @pytest.mark.asyncio
    async def test_homes_step_no_homes_selected(self):
        """Test homes step shows error when no homes selected."""
        mock_hass = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.get_homes = AsyncMock(
            return_value={"createfamilies": [{"familyId": "f1", "familyName": "Home 1"}]}
        )

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass
        flow._http_client = mock_http_client
        flow._language = "en"

        result = await flow.async_step_homes(user_input={"homes": []})

        assert result["type"] == "form"
        assert result["step_id"] == "homes"
        assert result["errors"]["base"] == "no_homes_selected"

    @pytest.mark.asyncio
    async def test_homes_step_success(self):
        """Test homes step success with scene sync."""
        mock_hass = MagicMock()
        mock_hass.config_entries.async_get_entry = MagicMock(return_value=None)

        mock_http_client = MagicMock()
        mock_http_client.get_homes = AsyncMock(
            return_value={"createfamilies": [{"familyId": "f1", "familyName": "Home 1"}]}
        )
        mock_http_client.get_scenes = AsyncMock(return_value={"f1": []})

        flow = HaierHomeConfigFlow()
        flow.hass = mock_hass
        # Mirrors ConfigFlowManager.async_init: give the flow a mutable context
        # so the inherited async_set_unique_id can store the unique id.
        flow.handler = "haier_home"
        flow.flow_id = "test-flow"
        flow.context = {}
        flow._http_client = mock_http_client
        flow._language = "en"
        flow._region = "cn"
        flow._uid = "123"
        flow._token = {"access_token": "test_token"}
        flow._ag_client_id = "test_client_id"

        # Isolate the inherited flow-termination machinery: this test covers
        # async_step_homes' own data-gathering, not HA's entry creation.
        with (
            patch.object(HaierHomeConfigFlow, "async_set_unique_id", AsyncMock()),
            patch.object(HaierHomeConfigFlow, "_abort_if_unique_id_configured", MagicMock()),
            patch.object(
                HaierHomeConfigFlow,
                "async_create_entry",
                MagicMock(return_value={"type": "create_entry"}),
            ),
        ):
            result = await flow.async_step_homes(
                user_input={
                    "homes": ["f1"],
                    "room_sync_mode": "family_and_room",
                    "scene_sync": "none",
                }
            )

            assert result["type"] == "create_entry"
            assert flow._family_names == {"f1": "Home 1"}


class TestConfigFlowHelpers:
    """Test helper methods."""

    def test_get_default_mark(self):
        """Test _get_default_mark."""
        flow = HaierHomeConfigFlow()
        flow._language = "en"

        result = flow._get_default_mark()
        assert isinstance(result, str)

    def test_translate_label_map(self):
        """Test _translate_label_map."""
        flow = HaierHomeConfigFlow()
        flow._language = "en"

        result = flow._translate_label_map("room_sync_options")
        assert isinstance(result, dict)
