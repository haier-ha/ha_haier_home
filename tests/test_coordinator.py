"""Tests for haier/coordinator.py."""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.haier_home.haier.coordinator import (
    HaierCoordinator,
)
from custom_components.haier_home.haier.oauth2 import HaierOAuth2Implementation
from tests.mock_data import create_mock_ac_device


class TestHaierCoordinatorProperties:
    """Test HaierCoordinator properties."""

    def test_properties(self):
        """Test coordinator properties."""
        device = create_mock_ac_device()
        devices = {device.device_id: device}

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices=devices,
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        assert coordinator.devices == devices
        assert coordinator.region == "cn"
        assert coordinator.connected is False
        assert coordinator.status == "normal"


class TestHaierCoordinatorListeners:
    """Test listener registration and notification."""

    def test_add_listener(self):
        """Test adding a listener."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        called = []
        unsub = coordinator.async_add_listener(lambda: called.append(1))

        coordinator._notify_listeners()
        assert len(called) == 1

        unsub()
        coordinator._notify_listeners()
        assert len(called) == 1


class TestHaierCoordinatorTokenRefresh:
    """Test token refresh logic."""

    @pytest.mark.asyncio
    async def test_token_needs_refresh_no_oauth_session(self):
        """Test token_needs_refresh returns False when no OAuth session."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        assert coordinator._token_needs_refresh() is False

    @pytest.mark.asyncio
    async def test_token_needs_refresh_missing_expires_at(self):
        """Test _token_needs_refresh treats a missing expires_at as needs-refresh."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        mock_session = MagicMock()
        # Legacy/corrupt token without an expiry timestamp must not raise.
        mock_session.token = {"access_token": "test_token"}
        coordinator._oauth_session = mock_session

        assert coordinator._token_needs_refresh() is True

    @pytest.mark.asyncio
    async def test_refresh_token_no_oauth_session(self):
        """Test _refresh_token fails when no OAuth session."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        result = await coordinator._refresh_token()
        assert result is False
        assert coordinator.status == "error_no_oauth_session"

    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
        """Test _refresh_token refreshes and writes back the new token.

        The refreshed token is written back to the single authoritative source,
        ``config_entry.data["token"]``, which the gate owns and which HTTP
        resolves through its token provider.
        """
        device = create_mock_ac_device()

        old_token = {
            "access_token": "test_token",
            "refresh_token": "refresh_token",
            "expires_at": 0,
        }
        new_token_data = {
            "access_token": "new_token",
            "refresh_token": "refresh_token",
            "expires_in": 3600,
            "expires_at": 9999999999,
        }
        mock_oauth_session = MagicMock()
        mock_oauth_session.token = old_token
        mock_oauth_session.valid_token = False
        mock_oauth_session.implementation.async_refresh_token = AsyncMock(
            return_value=new_token_data
        )

        mock_http_client = MagicMock()
        # Note: _refresh_token is decoupled from the WebSocket — a connected
        # socket is NOT touched here. Reconnecting with the fresh token is the
        # job of _reconnect_ws / _handle_auth_failure / the refresh loop.

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
            http_client=mock_http_client,
        )
        coordinator._oauth_session = mock_oauth_session
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.data = {"token": old_token}

        result = await coordinator._refresh_token()

        assert result is True
        mock_oauth_session.implementation.async_refresh_token.assert_awaited_once_with(old_token)
        # The fresh token is written back to the single authority
        # (config_entry.data["token"]).
        _update_kwargs = coordinator._hass.config_entries.async_update_entry.call_args.kwargs
        assert _update_kwargs["data"]["token"] == new_token_data
        assert coordinator._token == "new_token"

    @pytest.mark.asyncio
    async def test_token_needs_refresh_not_expired(self):
        """Test _token_needs_refresh returns False while the token is still valid.

        Freshness is judged against the in-memory ``_token_data`` the refresh
        gate maintains, using its ``expires_at`` — not the OAuth session.
        """
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            token_data={
                "access_token": "test_token",
                "expires_in": 7200,
                "refresh_token": "test_refresh_token",
                "expires_at": int(time.time()) + 2 * 864000,
            },
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._oauth_session = MagicMock()

        assert coordinator._token_needs_refresh() is False

    @pytest.mark.asyncio
    async def test_token_needs_refresh_expired(self):
        """Test _token_needs_refresh returns True when the token is expired.

        A past ``expires_at`` on the in-memory ``_token_data`` is inside the
        early-refresh window, so a refresh is required.
        """
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            token_data={"access_token": "test_token", "expires_at": 1000},
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._oauth_session = MagicMock()

        assert coordinator._token_needs_refresh() is True

    @pytest.mark.asyncio
    async def test_token_needs_refresh_still_valid(self):
        """Test _token_needs_refresh returns False when token is still valid.

        A far-future ``expires_at`` on the in-memory ``_token_data`` is outside
        the early-refresh window, so no refresh is needed.
        """
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            token_data={"access_token": "test_token", "expires_at": 9999999999},
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._oauth_session = MagicMock()

        assert coordinator._token_needs_refresh() is False

    @pytest.mark.asyncio
    async def test_refresh_token_does_not_touch_ws(self):
        """_refresh_token is decoupled from the WebSocket.

        Refreshing the token is the gate's only job; reconnecting a (possibly
        connected) WebSocket belongs to its callers. So refresh must succeed and
        return ``True`` without disconnecting/reconnecting the socket.
        """
        device = create_mock_ac_device()
        old_token = {"access_token": "test_token", "expires_at": 0}
        mock_oauth_session = MagicMock()
        mock_oauth_session.token = old_token
        mock_oauth_session.valid_token = False
        mock_oauth_session.implementation.async_refresh_token = AsyncMock(
            return_value={"access_token": "new_token", "expires_in": 3600, "expires_at": 9999999999}
        )

        mock_ws_client = MagicMock()
        mock_ws_client.connected = True
        mock_ws_client.disconnect = AsyncMock()
        mock_ws_client.connect = AsyncMock(return_value=True)
        mock_ws_client.start_listening = AsyncMock()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._oauth_session = mock_oauth_session
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.data = {"token": old_token}
        coordinator._ws_client = mock_ws_client

        result = await coordinator._refresh_token()

        assert result is True
        # Decoupled: refresh must NOT rebuild the socket itself.
        mock_ws_client.disconnect.assert_not_called()
        mock_ws_client.connect.assert_not_called()
        mock_ws_client.start_listening.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_token_succeeds_regardless_of_ws_state(self):
        """The token refresh result is independent of the WebSocket state.

        Refreshing and reconnecting are separate responsibilities: even when a
        connected socket would fail to rebuild, ``_refresh_token`` still reports
        the refresh itself as successful (``True``). The socket rebuild outcome
        is surfaced separately by :meth:`_reconnect_ws`.
        """
        device = create_mock_ac_device()
        old_token = {"access_token": "test_token", "expires_at": 0}
        mock_oauth_session = MagicMock()
        mock_oauth_session.token = old_token
        mock_oauth_session.valid_token = False
        mock_oauth_session.implementation.async_refresh_token = AsyncMock(
            return_value={"access_token": "new_token", "expires_in": 3600, "expires_at": 9999999999}
        )

        # A connected socket whose rebuild would FAIL: this must not affect the
        # refresh result, because refresh no longer drives the socket.
        mock_ws_client = MagicMock()
        mock_ws_client.connected = True
        mock_ws_client.disconnect = AsyncMock()
        mock_ws_client.connect = AsyncMock(return_value=False)
        mock_ws_client.start_listening = AsyncMock()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._oauth_session = mock_oauth_session
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.data = {"token": old_token}
        coordinator._ws_client = mock_ws_client

        result = await coordinator._refresh_token()

        # Refresh succeeded; the failing socket is a separate concern.
        assert result is True
        mock_ws_client.disconnect.assert_not_called()

    async def test_refresh_token_succeeds_without_socket(self):
        """A refresh before the WebSocket exists still succeeds.

        Building the socket belongs to ``_connect``/``async_start``; ``_refresh_token``
        is purely about the token, so the absence of a socket never affects it.
        """
        device = create_mock_ac_device()
        old_token = {"access_token": "test_token", "expires_at": 0}
        mock_oauth_session = MagicMock()
        mock_oauth_session.token = old_token
        mock_oauth_session.valid_token = False
        mock_oauth_session.implementation.async_refresh_token = AsyncMock(
            return_value={"access_token": "new_token", "expires_in": 3600, "expires_at": 9999999999}
        )

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._oauth_session = mock_oauth_session
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.data = {"token": old_token}
        # No _ws_client at all.

        result = await coordinator._refresh_token()

        assert result is True

    @pytest.mark.asyncio
    async def test_refresh_token_exception(self):
        """Test _refresh_token exception handling."""
        device = create_mock_ac_device()
        mock_oauth_session = MagicMock()
        mock_oauth_session.token = {"access_token": "test_token", "expires_at": 0}
        mock_oauth_session.valid_token = False
        mock_oauth_session.implementation.async_refresh_token = AsyncMock(
            side_effect=ValueError("fail")
        )
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._oauth_session = mock_oauth_session
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.data = {"token": {"access_token": "test_token"}}

        result = await coordinator._refresh_token()

        assert result is False
        assert coordinator.status == "error_refresh_failed"

    @pytest.mark.asyncio
    async def test_handle_auth_failure_force_refresh_and_reconnect(self):
        """A server auth rejection force-refreshes the token and reconnects WS."""
        coordinator = _CoordinatorContext.create()
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.entry_id = "e1"
        coordinator._refresh_token = AsyncMock(return_value=True)
        coordinator._reconnect_ws = AsyncMock(return_value=True)

        await coordinator._handle_auth_failure()

        # Server rejected the token, so we refresh regardless of the expiry window.
        coordinator._refresh_token.assert_awaited_once_with(force=True)
        coordinator._reconnect_ws.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_auth_failure_marks_reauth_when_refresh_fails(self):
        """If the force refresh itself fails, flag re-auth instead of reconnecting."""
        coordinator = _CoordinatorContext.create()
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.entry_id = "e1"
        coordinator._refresh_token = AsyncMock(return_value=False)
        coordinator._reconnect_ws = AsyncMock()

        await coordinator._handle_auth_failure()

        coordinator._reconnect_ws.assert_not_awaited()
        assert coordinator.status == "error_auth_failed"


class _CoordinatorContext:
    """Helper to create a coordinator for token refresh loop tests."""

    @staticmethod
    def create(oauth_session=None, ws_client=None):
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._oauth_session = oauth_session or MagicMock()
        coordinator._ws_client = ws_client
        return coordinator


class TestHaierCoordinatorTokenRefreshLoop:
    """Test _token_refresh_loop various branches."""

    @pytest.mark.asyncio
    async def test_token_refresh_loop_cancelled(self):
        """Test _token_refresh_loop exits on CancelledError."""
        coordinator = _CoordinatorContext.create()
        coordinator._stopped = False
        coordinator._token_needs_refresh = MagicMock(return_value=True)
        coordinator._refresh_token = AsyncMock(return_value=True)

        with patch.object(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError())):
            await coordinator._token_refresh_loop()

    @pytest.mark.asyncio
    async def test_token_refresh_loop_stopped_flag(self):
        """Test _token_refresh_loop exits when _stopped is True."""
        coordinator = _CoordinatorContext.create()
        coordinator._stopped = True

        await coordinator._token_refresh_loop()

    @pytest.mark.asyncio
    async def test_token_refresh_loop_needs_refresh_failure(self):
        """Test _token_refresh_loop increments failure_count on refresh failure."""
        coordinator = _CoordinatorContext.create()
        coordinator._stopped = False
        coordinator._token_needs_refresh = MagicMock(return_value=True)
        coordinator._refresh_token = AsyncMock(return_value=False)

        with patch.object(asyncio, "sleep", AsyncMock(side_effect=[None, None])):
            coordinator._stopped = True
            await asyncio.wait_for(coordinator._token_refresh_loop(), timeout=2)

    @pytest.mark.asyncio
    async def test_token_refresh_loop_no_refresh_needed(self):
        """Test _token_refresh_loop sleeps full interval when no refresh needed."""
        coordinator = _CoordinatorContext.create()
        coordinator._stopped = False
        coordinator._token_needs_refresh = MagicMock(return_value=False)

        async def stop_after_sleep(_interval):
            coordinator._stopped = True

        with patch.object(asyncio, "sleep", AsyncMock(side_effect=stop_after_sleep)):
            await asyncio.wait_for(coordinator._token_refresh_loop(), timeout=2)

        coordinator._token_needs_refresh.assert_called()

    @pytest.mark.asyncio
    async def test_token_refresh_loop_generic_exception(self):
        """Test _token_refresh_loop handles generic exception."""
        coordinator = _CoordinatorContext.create()
        coordinator._stopped = False
        coordinator._token_needs_refresh = MagicMock(side_effect=RuntimeError("unexpected"))

        with patch.object(asyncio, "sleep", AsyncMock(side_effect=[None, None])):
            coordinator._stopped = True
            await asyncio.wait_for(coordinator._token_refresh_loop(), timeout=2)

    @pytest.mark.asyncio
    async def test_token_refresh_loop_multiple_failures_backoff(self):
        """Test _token_refresh_loop exponential backoff on repeated failures."""
        coordinator = _CoordinatorContext.create()
        coordinator._stopped = False
        coordinator._token_needs_refresh = MagicMock(return_value=True)
        coordinator._refresh_token = AsyncMock(return_value=False)

        sleep_intervals = []

        async def capture_sleep(interval):
            sleep_intervals.append(interval)
            if len(sleep_intervals) >= 3:
                coordinator._stopped = True

        # Pin a high refresh-interval ceiling so the backoff (60 -> 120 -> 240)
        # is bounded by min_retry_interval rather than clipped by the max. This
        # keeps the assertion stable when TOKEN_REFRESH_INTERVAL is temporarily
        # lowered for fast local validation (see const.py's "# FOR TEST" block).
        with (
            patch(
                "custom_components.haier_home.haier.coordinator.TOKEN_REFRESH_INTERVAL",
                3600,
            ),
            patch.object(asyncio, "sleep", AsyncMock(side_effect=capture_sleep)),
        ):
            await asyncio.wait_for(coordinator._token_refresh_loop(), timeout=2)

        assert sleep_intervals[0] == 60
        assert sleep_intervals[1] == 120

    @pytest.mark.asyncio
    async def test_token_refresh_loop_stopped_while_sleeping(self):
        """Test _token_refresh_loop exits when stopped mid-sleep."""
        coordinator = _CoordinatorContext.create()
        coordinator._stopped = False
        coordinator._token_needs_refresh = MagicMock(side_effect=RuntimeError("fail"))

        async def stop_on_sleep(_interval):
            coordinator._stopped = True

        with patch.object(asyncio, "sleep", AsyncMock(side_effect=stop_on_sleep)):
            await coordinator._token_refresh_loop()


class TestHaierCoordinatorSendCommand:
    """Test send_command logic."""

    @pytest.mark.asyncio
    async def test_send_command_not_connected(self):
        """Test send_command when not connected."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        # Should not raise
        await coordinator.async_send_command(device.device_id, {"targetTemperature": "26"})

    @pytest.mark.asyncio
    async def test_send_command_device_not_found(self):
        """Test send_command when device not found."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = MagicMock()
        coordinator._ws_client.connected = True

        # Should not raise
        await coordinator.async_send_command("unknown_device", {"targetTemperature": "26"})

    @pytest.mark.asyncio
    async def test_send_command_success(self):
        """Test send_command success."""
        device = create_mock_ac_device()
        mock_ws_client = MagicMock()
        mock_ws_client.connected = True
        mock_ws_client.send_command = AsyncMock()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = mock_ws_client

        await coordinator.async_send_command(device.device_id, {"targetTemperature": "26"})

        mock_ws_client.send_command.assert_called_once()


class TestHaierCoordinatorOnMessage:
    """Test message handling."""

    def test_on_message_gen_msg_down(self):
        """Test _on_message with GenMsgDown topic."""
        import base64
        import gzip
        import json

        device = create_mock_ac_device()

        # Create test payload
        inner_data = {
            "dev": device.device_id,
            "args": {"attributes": [{"name": "targetTemperature", "value": "26"}]},
        }
        compressed_args = gzip.compress(json.dumps(inner_data["args"]).encode())
        b64_compressed = base64.b64encode(compressed_args).decode()
        inner_data["args"] = b64_compressed
        first_json = json.dumps(inner_data)
        b64_first = base64.b64encode(first_json.encode()).decode()

        content = {"businType": "DigitalModelHA", "data": b64_first}

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        coordinator._on_message("GenMsgDown", content)

        # Device should be updated
        assert device.get_value("targetTemperature") == "26"

    def test_on_message_unhandled_topic(self):
        """Test _on_message with unhandled topic."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        # Should not raise
        coordinator._on_message("UnknownTopic", {})


class TestHaierCoordinatorStartStop:
    """Test async_start and async_stop."""

    @pytest.mark.asyncio
    async def test_async_start(self):
        """Test async_start subscribes the loaded devices and starts the refresh loop."""
        device = create_mock_ac_device()

        mock_hass = MagicMock()
        mock_hass.async_create_task = MagicMock(
            return_value=asyncio.create_task(asyncio.sleep(0.1))
        )
        mock_hass.async_create_background_task = MagicMock(
            return_value=asyncio.create_task(asyncio.sleep(0.1))
        )

        coordinator = HaierCoordinator(
            hass=mock_hass,
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        # The socket is already live (dependency readiness connected it); it just
        # needs to be instructed which devices to subscribe.
        mock_ws = MagicMock()
        mock_ws.connected = True
        mock_ws.send_bound_devs = AsyncMock()
        coordinator._ws_client = mock_ws

        await coordinator.async_start()

        mock_ws.send_bound_devs.assert_awaited_once_with([device.device_id])
        assert coordinator._token_refresh_task is not None

        # Complete the mock background tasks so no lingering tasks remain.
        await coordinator._token_refresh_task

    @pytest.mark.asyncio
    async def test_async_stop(self):
        """Test async_stop cancels tasks."""
        device = create_mock_ac_device()

        mock_ws_client = MagicMock()
        mock_ws_client.disconnect = AsyncMock()

        mock_http_client = MagicMock()
        mock_http_client.close = AsyncMock()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
            http_client=mock_http_client,
        )
        coordinator._ws_client = mock_ws_client
        coordinator._token_refresh_task = asyncio.create_task(asyncio.sleep(0.1))

        await coordinator.async_stop()

        assert coordinator._token_refresh_task is None
        mock_ws_client.disconnect.assert_called_once()
        mock_http_client.close.assert_called_once()


class TestHaierCoordinatorConnect:
    """Test _connect method."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test _connect succeeds."""
        device = create_mock_ac_device()

        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=True)
        mock_ws_client.start_listening = AsyncMock()
        mock_ws_client.send_bound_devs = AsyncMock()

        mock_hass = MagicMock()
        mock_hass.async_create_background_task = MagicMock()

        coordinator = HaierCoordinator(
            hass=mock_hass,
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        # Mock the WebSocketClient class
        with patch(
            "custom_components.haier_home.haier.coordinator.HaierWebSocketClient",
            return_value=mock_ws_client,
        ):
            await coordinator._connect()

        mock_ws_client.connect.assert_called_once()
        mock_ws_client.start_listening.assert_called_once()
        # The socket is told which devices to subscribe (coordinator's device list).
        mock_ws_client.send_bound_devs.assert_called_once_with([device.device_id])

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test _connect fails and starts reconnect loop."""
        device = create_mock_ac_device()

        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=False)
        mock_ws_client.connected = False

        mock_hass = MagicMock()
        mock_hass.async_create_background_task = MagicMock()

        coordinator = HaierCoordinator(
            hass=mock_hass,
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = mock_ws_client

        with patch(
            "custom_components.haier_home.haier.coordinator.HaierWebSocketClient",
            return_value=mock_ws_client,
        ):
            await coordinator._connect()

        mock_hass.async_create_background_task.assert_called_once()


class TestHaierCoordinatorAsyncStartWithConfigEntry:
    """Test async_start with config_entry."""

    @pytest.mark.asyncio
    async def test_dependencies_ready_binds_entry_own_implementation(self):
        """_ensure_dependencies_ready binds the OAuth2Session to THIS entry's credentials.

        The coordinator constructs ``HaierOAuth2Implementation`` from the entry's
        stored region/ag_client_id rather than resolving it via HA's shared
        per-domain registry.
        """
        device = create_mock_ac_device()

        mock_hass = MagicMock()

        mock_config_entry = MagicMock()
        mock_config_entry.data = {"region": "cn", "ag_client_id": "account_A_client"}

        mock_http_client = MagicMock()
        mock_http_client.async_init = AsyncMock()

        coordinator = HaierCoordinator(
            hass=mock_hass,
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="account_A_client",
            app_id="test_app_id",
            http_client=mock_http_client,
            config_entry=mock_config_entry,
        )

        with patch(
            "custom_components.haier_home.haier.coordinator.OAuth2Session"
        ) as mock_oauth_session_class:
            # A real refresh/connect is not the point here; stub them so we can
            # inspect the OAuth binding done by _ensure_dependencies_ready.
            coordinator._refresh_token = AsyncMock(return_value=True)
            coordinator._connect = AsyncMock()
            result = await coordinator._ensure_dependencies_ready()

            assert result is True
            mock_oauth_session_class.assert_called_once()
            _hass, _entry, implementation = mock_oauth_session_class.call_args[0]
            # The implementation is bound to the entry's own client id, not to
            # whatever a shared registry would return for another account.
            assert isinstance(implementation, HaierOAuth2Implementation)
            assert implementation._ag_client_id == "account_A_client"
            assert implementation._region == "cn"

    @pytest.mark.asyncio
    async def test_configure_oauth_binds_own_credentials_multiple_entries(self):
        """Regression (root cause): two accounts never cross-wire their tokens.

        With several Haier accounts configured, the old code resolved the OAuth
        implementation through HA's shared per-domain registry, which returns the
        last-registered implementation for *every* entry — binding one account's
        coordinator to another account's ag_client_id so its refresh would be
        rejected and it would keep using the old token. Each coordinator must
        bind to its own entry's credentials regardless of the registry.
        """
        device = create_mock_ac_device()

        entry_a = MagicMock()
        entry_a.data = {"region": "cn", "ag_client_id": "account_A_client"}
        entry_b = MagicMock()
        entry_b.data = {"region": "cn", "ag_client_id": "account_B_client"}

        coord_a = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="token_a",
            ag_client_id="account_A_client",
            app_id="test_app_id",
            config_entry=entry_a,
        )
        coord_b = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="token_b",
            ag_client_id="account_B_client",
            app_id="test_app_id",
            config_entry=entry_b,
        )

        # Even if HA's shared registry would hand both the same (B's)
        # implementation — simulated by pre-configuring them via a foreign
        # impl — _configure_oauth must still bind each to its own credentials.
        coord_a._configure_oauth(entry_a)
        coord_b._configure_oauth(entry_b)

        assert coord_a._oauth_session is not None
        assert coord_b._oauth_session is not None
        assert coord_a._oauth_session.implementation._ag_client_id == "account_A_client"
        assert coord_b._oauth_session.implementation._ag_client_id == "account_B_client"
        # And they are distinct implementations, so a refresh on A never uses B's
        # ag_client_id.
        assert coord_a._oauth_session.implementation is not coord_b._oauth_session.implementation

    def test_configure_oauth_fails_fast_on_missing_ag_client_id(self):
        """Empty/missing ag_client_id builds no OAuth session (fail-fast).

        ag_client_id is required for every authenticated request and the config
        flow always generates a non-empty value, so an empty one only appears on
        a stale/legacy entry. We must not let an empty client id flow into the
        OAuth implementation (every refresh would fail cryptically); instead
        leave ``_oauth_session`` unset so ``_refresh_token`` reports the
        actionable ``error_no_oauth_session`` status.
        """
        device = create_mock_ac_device()

        entry = MagicMock()
        entry.entry_id = "entry_empty_client"
        entry.data = {"region": "cn", "ag_client_id": ""}

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="",
            app_id="test_app_id",
            config_entry=entry,
        )

        with patch(
            "custom_components.haier_home.haier.coordinator.OAuth2Session"
        ) as mock_oauth_session_class:
            coordinator._configure_oauth(entry)
            mock_oauth_session_class.assert_not_called()

        assert coordinator._oauth_session is None

    @pytest.mark.asyncio
    async def test_current_access_token_reads_authoritative_source(self):
        """_current_access_token returns the in-memory token_data access_token.

        The single source of truth is the in-memory ``_token_data`` the refresh
        gate maintains, read directly rather than from ``config_entry.data``
        (whose write-back is delayed). ``token`` is only a fallback when
        ``_token_data`` carries no access_token.
        """
        device = create_mock_ac_device()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="fallback_token",
            token_data={"access_token": "auth_token"},
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        assert coordinator._current_access_token() == "auth_token"

    @pytest.mark.asyncio
    async def test_current_access_token_falls_back_to_token(self):
        """_current_access_token falls back to ``token`` when token_data has none."""
        device = create_mock_ac_device()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="fallback_token",
            token_data={},
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        assert coordinator._current_access_token() == "fallback_token"


class TestHaierCoordinatorGenMsgDown:
    """Test _handle_gen_msg_down various branches."""

    def test_handle_gen_msg_down_empty_data(self):
        """Test _handle_gen_msg_down with empty data."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        coordinator._handle_gen_msg_down({"data": ""})
        # Should return early without error

    def test_handle_gen_msg_down_gzip_path(self):
        """Test _handle_gen_msg_down with gzip compressed args."""
        device = create_mock_ac_device()

        inner = {
            "dev": device.device_id,
            "args": {"attributes": [{"name": "targetTemperature", "value": "26"}]},
        }
        compressed = gzip.compress(json.dumps(inner["args"]).encode())
        b64_compressed = base64.b64encode(compressed).decode()
        inner["args"] = b64_compressed
        encoded = base64.b64encode(json.dumps(inner).encode()).decode()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        coordinator._handle_gen_msg_down({"businType": "DigitalModelHA", "data": encoded})
        assert device.get_value("targetTemperature") == "26"

    def test_handle_gen_msg_down_unknown_device(self):
        """Test _handle_gen_msg_down with unknown device_id."""
        inner = {"dev": "unknown_device", "args": {"attributes": []}}
        encoded = base64.b64encode(json.dumps(inner).encode()).decode()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        coordinator._handle_gen_msg_down({"data": encoded})
        # Should not raise

    def test_handle_gen_msg_down_empty_device_id(self):
        """Test _handle_gen_msg_down with empty device_id."""
        inner = {"dev": "", "args": {}}
        encoded = base64.b64encode(json.dumps(inner).encode()).decode()

        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        coordinator._handle_gen_msg_down({"data": encoded})
        # Should not raise

    def test_handle_gen_msg_down_non_h4si_args(self):
        """Test _handle_gen_msg_down with non-gzip args that don't start with H4sI."""
        inner = {"dev": "unknown", "args": "plain_text_args"}
        encoded = base64.b64encode(json.dumps(inner).encode()).decode()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        # Should not raise
        coordinator._handle_gen_msg_down({"data": encoded})

    def test_handle_gen_msg_down_parse_exception(self):
        """Test _handle_gen_msg_down exception handling (invalid base64)."""
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        coordinator._handle_gen_msg_down({"data": "!!!invalid base64!!!"})
        # Should not raise, exception is caught


class TestHaierCoordinatorReconnectLoop:
    """Test _reconnect_loop various branches."""

    @pytest.mark.asyncio
    async def test_reconnect_loop_already_connected(self):
        """Test _reconnect_loop exits immediately when already connected."""
        device = create_mock_ac_device()
        mock_ws_client = MagicMock()
        mock_ws_client.connected = True

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = mock_ws_client

        await coordinator._reconnect_loop()
        assert coordinator._reconnect_task is None

    @pytest.mark.asyncio
    async def test_reconnect_loop_stopped_flag(self):
        """Test _reconnect_loop exits when _stopped is True."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._stopped = True

        await coordinator._reconnect_loop()
        assert coordinator._reconnect_task is None

    @pytest.mark.asyncio
    async def test_reconnect_loop_successful_reconnect(self):
        """Test _reconnect_loop successful reconnection."""
        device = create_mock_ac_device()

        mock_ws_client = MagicMock()
        mock_ws_client.connected = False
        mock_ws_client.connect = AsyncMock(return_value=True)
        mock_ws_client.start_listening = AsyncMock()
        mock_ws_client.send_bound_devs = AsyncMock()
        mock_ws_client.disconnect = AsyncMock()

        mock_hass = MagicMock()

        coordinator = HaierCoordinator(
            hass=mock_hass,
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = mock_ws_client
        coordinator._ws_client.connected = False

        async def _reconnect_impl():
            coordinator._ws_client = mock_ws_client

        with (
            patch.object(asyncio, "sleep", AsyncMock(return_value=None)),
            patch(
                "custom_components.haier_home.haier.coordinator.HaierWebSocketClient",
                return_value=mock_ws_client,
            ),
        ):
            await coordinator._reconnect_loop()

        assert coordinator._reconnect_task is None

    @pytest.mark.asyncio
    async def test_reconnect_loop_connect_fails(self):
        """Test _reconnect_loop when connect attempt fails."""
        device = create_mock_ac_device()

        mock_ws_client = MagicMock()
        mock_ws_client.connected = False
        mock_ws_client.connect = AsyncMock(return_value=False)
        mock_ws_client.disconnect = AsyncMock()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = mock_ws_client
        coordinator._ws_client.connected = False

        attempt_count = [0]

        async def sleep_and_stop(interval):
            attempt_count[0] += 1
            if attempt_count[0] >= 1:
                coordinator._stopped = True

        with (
            patch.object(asyncio, "sleep", AsyncMock(side_effect=sleep_and_stop)),
            patch(
                "custom_components.haier_home.haier.coordinator.HaierWebSocketClient",
                return_value=mock_ws_client,
            ),
        ):
            await coordinator._reconnect_loop()

        assert coordinator._reconnect_task is None

    @pytest.mark.asyncio
    async def test_reconnect_loop_cancelled(self):
        """Test _reconnect_loop exits on CancelledError."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        with patch.object(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError())):
            await coordinator._reconnect_loop()

        assert coordinator._reconnect_task is None

    @pytest.mark.asyncio
    async def test_reconnect_loop_generic_exception(self):
        """Test _reconnect_loop handles generic exception."""
        device = create_mock_ac_device()
        mock_ws_client = MagicMock()
        mock_ws_client.connected = False
        mock_ws_client.disconnect = AsyncMock(side_effect=RuntimeError("boom"))

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = mock_ws_client
        coordinator._ws_client.connected = False

        attempt_count = [0]

        async def sleep_and_stop(interval):
            attempt_count[0] += 1
            if attempt_count[0] >= 1:
                coordinator._stopped = True

        with (
            patch.object(asyncio, "sleep", AsyncMock(side_effect=sleep_and_stop)),
            patch(
                "custom_components.haier_home.haier.coordinator.HaierWebSocketClient",
                return_value=mock_ws_client,
            ),
        ):
            await coordinator._reconnect_loop()

        assert coordinator._reconnect_task is None

    @pytest.mark.asyncio
    async def test_reconnect_loop_stopped_before_connect(self):
        """Test _reconnect_loop checks stopped flag after creating new client."""
        device = create_mock_ac_device()
        mock_ws_client = MagicMock()
        mock_ws_client.connected = False
        mock_ws_client.disconnect = AsyncMock()
        mock_ws_client.connect = AsyncMock()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = mock_ws_client
        coordinator._ws_client.connected = False
        coordinator._stopped = True

        with (
            patch.object(asyncio, "sleep", AsyncMock(return_value=None)),
            patch(
                "custom_components.haier_home.haier.coordinator.HaierWebSocketClient",
                return_value=mock_ws_client,
            ),
        ):
            await coordinator._reconnect_loop()

        assert coordinator._reconnect_task is None

    @pytest.mark.asyncio
    async def test_reconnect_loop_skips_rebuild_if_connected_after_refresh(self):
        """Reconnect loop must not rebuild when another path (e.g. a token
        refresh) already reconnected while we waited on the token lock.

        The loop double-checks ``connected`` before tearing down and recreating
        self._ws_client; if the connection is already up it exits without
        touching the client, so it never disconnects a healthy connection or
        leaves two tasks racing on self._ws_client.
        """
        device = create_mock_ac_device()
        mock_ws_client = MagicMock()
        mock_ws_client.connected = False
        mock_ws_client.connect = AsyncMock(return_value=True)
        mock_ws_client.start_listening = AsyncMock()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = mock_ws_client
        # No OAuth session: the pre-rebuild token guard becomes a no-op.
        coordinator._oauth_session = None

        async def sleep_and_reconnect(interval):
            # Simulate a token refresh rebuilding the connection while this
            # loop sleeps/waits on the token lock.
            mock_ws_client.connected = True

        with (
            patch.object(asyncio, "sleep", AsyncMock(side_effect=sleep_and_reconnect)),
            patch(
                "custom_components.haier_home.haier.coordinator.HaierWebSocketClient",
                return_value=mock_ws_client,
            ),
        ):
            await coordinator._reconnect_loop()

        # Exited via the "already connected" guard: never disconnected or
        # recreated the client.
        mock_ws_client.connect.assert_not_called()
        assert coordinator._reconnect_task is None

    @pytest.mark.asyncio
    async def test_reconnect_loop_serialized_by_ws_lock(self):
        """The whole WS lifecycle is serialized by ``_ws_lock``.

        Regression for the root-cause race: while a token refresh is rebuilding
        the WebSocket (holding ``_ws_lock``), the reconnect loop must block on
        the same lock rather than tearing down / replacing ``self._ws_client``
        mid-rebuild. It may only proceed after the lock is released, so two
        coroutines can never race on the client.
        """
        device = create_mock_ac_device()
        mock_ws_client = MagicMock()
        mock_ws_client.connected = False
        mock_ws_client.connect = AsyncMock(return_value=True)
        mock_ws_client.start_listening = AsyncMock()
        mock_ws_client.send_bound_devs = AsyncMock()
        mock_ws_client.disconnect = AsyncMock()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._ws_client = mock_ws_client
        coordinator._ws_client.connected = False
        # No OAuth session: the pre-rebuild token gate becomes a no-op.
        coordinator._oauth_session = None

        # Simulate _refresh_token already holding _ws_lock while it rebuilds the
        # socket (disconnect + connect + start_listening in progress).
        await coordinator._ws_lock.acquire()

        loop_task = asyncio.create_task(coordinator._reconnect_loop())

        # The patch must stay active until loop_task finishes, because once the
        # loop acquires the lock it (re)builds a client via HaierWebSocketClient.
        with (
            patch.object(asyncio, "sleep", AsyncMock(return_value=None)),
            patch(
                "custom_components.haier_home.haier.coordinator.HaierWebSocketClient",
                return_value=mock_ws_client,
            ),
        ):
            # Give the loop time to reach the point where it needs the lock.
            await asyncio.sleep(0.05)

            # While _ws_lock is held, the loop must NOT have rebuilt anything.
            mock_ws_client.disconnect.assert_not_called()
            mock_ws_client.connect.assert_not_called()

            # Release the lock: the loop may now proceed under the lock.
            coordinator._ws_lock.release()
            await loop_task

        # After acquiring the lock it rebuilt and reconnected the client.
        mock_ws_client.disconnect.assert_awaited()
        mock_ws_client.connect.assert_awaited()
        assert coordinator._reconnect_task is None


class TestHaierCoordinatorWsDisconnected:
    """Test _ws_disconnected reconnect-suppression during token-refresh rebuild."""

    def test_ws_disconnected_schedules_reconnect_normally(self):
        """A real, unexpected disconnect schedules a reconnect."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._schedule_reconnect = MagicMock()

        coordinator._ws_disconnected()

        coordinator._schedule_reconnect.assert_called_once()

    def test_ws_disconnected_skips_reconnect_during_rebuild(self):
        """During a token-refresh WS rebuild the callback must NOT schedule a
        redundant reconnect loop (it would race / tear down the rebuild)."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._schedule_reconnect = MagicMock()
        coordinator._ws_reconnecting = True

        coordinator._ws_disconnected()

        coordinator._schedule_reconnect.assert_not_called()

    def test_ws_disconnected_ignores_when_stopped(self):
        """Not schedule a reconnect when the coordinator has been stopped."""
        device = create_mock_ac_device()
        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )
        coordinator._stopped = True
        coordinator._schedule_reconnect = MagicMock()

        coordinator._ws_disconnected()

        coordinator._schedule_reconnect.assert_not_called()


class TestHaierCoordinatorAsyncStop:
    """Test async_stop additional branches."""

    @pytest.mark.asyncio
    async def test_async_stop_with_reconnect_task(self):
        """Test async_stop cancels reconnect_task."""
        device = create_mock_ac_device()
        mock_ws_client = MagicMock()
        mock_ws_client.disconnect = AsyncMock()
        mock_http_client = MagicMock()
        mock_http_client.close = AsyncMock()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
            http_client=mock_http_client,
        )
        coordinator._ws_client = mock_ws_client

        reconnect_done = asyncio.Event()

        async def slow_reconnect():
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                reconnect_done.set()
                raise

        coordinator._reconnect_task = asyncio.ensure_future(slow_reconnect())
        coordinator._token_refresh_task = asyncio.create_task(asyncio.sleep(0.1))

        # Yield control so slow_reconnect actually starts executing
        # before async_stop cancels it. If we cancel a task before it
        # begins running, the CancelledError is swallowed before the
        # coroutine enters its try/except handler and the event below
        # would never be set.
        await asyncio.sleep(0)

        await coordinator.async_stop()

        assert reconnect_done.is_set()
        assert coordinator._reconnect_task is None
        assert coordinator._token_refresh_task is None
        mock_ws_client.disconnect.assert_called_once()
        mock_http_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_stop_no_tasks(self):
        """Test async_stop when there are no tasks."""
        device = create_mock_ac_device()

        coordinator = HaierCoordinator(
            hass=MagicMock(),
            region="cn",
            devices={device.device_id: device},
            token="test_token",
            ag_client_id="test_client_id",
            app_id="test_app_id",
        )

        await coordinator.async_stop()

        assert coordinator._stopped is True


class TestHaierCoordinatorWsHandshakeAuthFailure:
    """Test _handle_ws_handshake_auth_failure (invoked from inside connect())."""

    @pytest.mark.asyncio
    async def test_force_refreshes_and_does_not_reconnect(self):
        """It force-refreshes the token but must NOT reconnect (avoids _ws_lock deadlock)."""
        coordinator = _CoordinatorContext.create()
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.entry_id = "e1"
        coordinator._refresh_token = AsyncMock(return_value=True)
        coordinator._reconnect_ws = AsyncMock()

        await coordinator._handle_ws_handshake_auth_failure()

        # Force refresh regardless of the local expiry window ...
        coordinator._refresh_token.assert_awaited_once_with(force=True)
        # ... but reconnection is the caller's job, not this handler's.
        coordinator._reconnect_ws.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_marks_reauth_when_force_refresh_fails(self):
        """When the force refresh fails, flag re-auth (dead refresh_token)."""
        coordinator = _CoordinatorContext.create()
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.entry_id = "e1"
        coordinator._refresh_token = AsyncMock(return_value=False)

        await coordinator._handle_ws_handshake_auth_failure()

        assert coordinator.status == "error_auth_failed"


class TestHaierCoordinatorSyncWsToCurrentToken:
    """Test the converged + debounced token-driven WS reconnect."""

    @pytest.mark.asyncio
    async def test_reconnects_when_token_changed(self):
        """A changed token triggers a reconnect and stamps the reconnect time."""
        coordinator = _CoordinatorContext.create()
        coordinator._reconnect_ws = AsyncMock(return_value=True)
        coordinator._current_access_token = MagicMock(return_value="new_token")
        coordinator._last_ws_token_reconnect_at = 0.0

        await coordinator._sync_ws_to_current_token("old_token")

        coordinator._reconnect_ws.assert_awaited_once()
        assert coordinator._last_ws_token_reconnect_at > 0

    @pytest.mark.asyncio
    async def test_skips_when_token_unchanged(self):
        """No reconnect when the token did not actually change."""
        coordinator = _CoordinatorContext.create()
        coordinator._reconnect_ws = AsyncMock()
        coordinator._current_access_token = MagicMock(return_value="same_token")

        await coordinator._sync_ws_to_current_token("same_token")

        coordinator._reconnect_ws.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_debounced_within_interval(self):
        """A token change too soon after the last reconnect is debounced away."""
        coordinator = _CoordinatorContext.create()
        coordinator._reconnect_ws = AsyncMock()
        coordinator._current_access_token = MagicMock(return_value="new_token")
        # Last reconnect happened just now -> within WS_RECONNECT_MIN_INTERVAL.
        coordinator._last_ws_token_reconnect_at = time.monotonic()

        await coordinator._sync_ws_to_current_token("old_token")

        coordinator._reconnect_ws.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reconnects_after_interval_elapsed(self):
        """Once the debounce interval has passed, a token change reconnects again."""
        coordinator = _CoordinatorContext.create()
        coordinator._reconnect_ws = AsyncMock(return_value=True)
        coordinator._current_access_token = MagicMock(return_value="new_token")
        # Last reconnect far in the past -> debounce no longer applies.
        coordinator._last_ws_token_reconnect_at = time.monotonic() - 10_000

        await coordinator._sync_ws_to_current_token("old_token")

        coordinator._reconnect_ws.assert_awaited_once()


class TestHaierCoordinatorReconnectWsSchedulesOnFailure:
    """Test _reconnect_ws hands off to the backoff loop when the rebuild fails."""

    @pytest.mark.asyncio
    async def test_schedules_reconnect_when_rebuild_fails(self):
        """A failed handshake (e.g. post-401) schedules the reconnect loop."""
        mock_ws_client = MagicMock()
        mock_ws_client.connected = True
        mock_ws_client.disconnect = AsyncMock()
        mock_ws_client.connect = AsyncMock(return_value=False)

        coordinator = _CoordinatorContext.create(ws_client=mock_ws_client)
        coordinator._stopped = False
        coordinator._schedule_reconnect = MagicMock()

        result = await coordinator._reconnect_ws()

        assert result is False
        coordinator._schedule_reconnect.assert_called_once()
        # The reconnecting flag is cleared before handing off.
        assert coordinator._ws_reconnecting is False

    @pytest.mark.asyncio
    async def test_does_not_schedule_when_stopped(self):
        """A failed rebuild during teardown must not schedule a reconnect."""
        mock_ws_client = MagicMock()
        mock_ws_client.connected = False
        mock_ws_client.disconnect = AsyncMock()
        mock_ws_client.connect = AsyncMock(return_value=False)

        coordinator = _CoordinatorContext.create(ws_client=mock_ws_client)
        coordinator._stopped = True
        coordinator._schedule_reconnect = MagicMock()

        result = await coordinator._reconnect_ws()

        assert result is False
        coordinator._schedule_reconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_does_not_schedule(self):
        """A successful rebuild does not schedule a redundant reconnect."""
        mock_ws_client = MagicMock()
        mock_ws_client.connected = True
        mock_ws_client.disconnect = AsyncMock()
        mock_ws_client.connect = AsyncMock(return_value=True)
        mock_ws_client.start_listening = AsyncMock()
        mock_ws_client.send_bound_devs = AsyncMock()

        coordinator = _CoordinatorContext.create(ws_client=mock_ws_client)
        coordinator._stopped = False
        coordinator._schedule_reconnect = MagicMock()

        result = await coordinator._reconnect_ws()

        assert result is True
        coordinator._schedule_reconnect.assert_not_called()


class TestHaierCoordinatorAuthFailureStampsReconnectTime:
    """The HTTP 401 auth-failure path reconnects immediately and stamps the time."""

    @pytest.mark.asyncio
    async def test_stamps_reconnect_time(self):
        """_handle_auth_failure records the reconnect time so the loop won't pile on."""
        coordinator = _CoordinatorContext.create()
        coordinator._config_entry = MagicMock()
        coordinator._config_entry.entry_id = "e1"
        coordinator._refresh_token = AsyncMock(return_value=True)
        coordinator._reconnect_ws = AsyncMock(return_value=True)
        coordinator._last_ws_token_reconnect_at = 0.0

        await coordinator._handle_auth_failure()

        coordinator._reconnect_ws.assert_awaited_once()
        assert coordinator._last_ws_token_reconnect_at > 0


class TestHaierCoordinatorRefreshLoopUsesDebouncedSync:
    """The refresh loop routes WS reconnection through the debounced sync path."""

    @pytest.mark.asyncio
    async def test_loop_calls_sync_with_previous_token(self):
        """On a successful refresh the loop hands the pre-refresh token to the sync."""
        coordinator = _CoordinatorContext.create()
        coordinator._stopped = False
        coordinator._token_needs_refresh = MagicMock(return_value=True)
        coordinator._refresh_token = AsyncMock(return_value=True)
        coordinator._current_access_token = MagicMock(return_value="before_token")
        coordinator._sync_ws_to_current_token = AsyncMock()

        async def stop_after_sleep(_interval):
            coordinator._stopped = True

        with patch.object(asyncio, "sleep", AsyncMock(side_effect=stop_after_sleep)):
            await asyncio.wait_for(coordinator._token_refresh_loop(), timeout=2)

        coordinator._sync_ws_to_current_token.assert_awaited_with("before_token")
