"""Tests for haier/websocket_client.py."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.haier_home.haier.websocket_client import HaierWebSocketClient


class TestHaierWebSocketClientProperties:
    """Test HaierWebSocketClient properties."""

    def test_connected_property(self):
        """Test connected property."""
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        assert client.connected is False

    def test_generate_sn(self):
        """Test generate_sn generates unique serial numbers."""
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        sn1 = client.generate_sn()
        sn2 = client.generate_sn()
        assert sn1 != sn2
        assert sn1.startswith("sn_")

    def test_generate_trace_id(self):
        """Test generate_trace_id generates UUID."""
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        trace_id = client.generate_trace_id()
        assert len(trace_id) == 32  # UUID without hyphens


class TestHaierWebSocketClientSendCommands:
    """Test send_heartbeat, send_bound_devs, and send_command."""

    @pytest.mark.asyncio
    async def test_send_heartbeat_not_connected(self):
        """Test send_heartbeat when not connected."""
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        # Should not raise
        await client.send_heartbeat()

    @pytest.mark.asyncio
    async def test_send_heartbeat_connected(self):
        """Test send_heartbeat when connected."""
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True

        await client.send_heartbeat()

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args
        assert call_args.args[0]["topic"] == "HeartBeat"
        # The sent sn is recorded as pending for ACK correlation.
        assert client._heartbeat_pending_sn == call_args.args[0]["content"]["sn"]

    @pytest.mark.asyncio
    async def test_send_bound_devs_not_connected(self):
        """Test send_bound_devs when not connected."""
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        # Should not raise
        await client.send_bound_devs(["device_001"])

    @pytest.mark.asyncio
    async def test_send_bound_devs_connected(self):
        """Test send_bound_devs when connected."""
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True

        await client.send_bound_devs(["device_001"])

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args
        assert call_args.args[0]["topic"] == "BoundDevs"
        assert call_args.args[0]["content"]["devs"] == ["device_001"]

    @pytest.mark.asyncio
    async def test_send_bound_devs_empty_skipped(self):
        """An empty BoundDevs list is skipped (no message sent to the cloud)."""
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True

        await client.send_bound_devs([])

        mock_ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_command_not_connected(self):
        """Test send_command when not connected."""
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        result = await client.send_command([{"deviceId": "device_001", "cmdArgs": {}}])
        assert result is None

    @pytest.mark.asyncio
    async def test_send_command_connected(self):
        """Test send_command when connected."""
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True

        result = await client.send_command([{"deviceId": "device_001", "cmdArgs": {}}])

        assert result is not None
        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args
        assert call_args.args[0]["topic"] == "BatchCmdReq"


class TestHaierWebSocketClientHandleMessage:
    """Test _handle_message method."""

    @pytest.mark.asyncio
    async def test_handle_message_heartbeat_ack(self):
        """Test handling HeartBeatAck."""
        from types import SimpleNamespace

        msg = SimpleNamespace(data='{"topic": "HeartBeatAck", "content": {"sn": "test_sn"}}')

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._last_heartbeat_sn = "test_sn"
        client._heartbeat_pending_sn = "test_sn"

        await client._handle_message(msg)

        # A matching ACK records the ack time and clears the pending heartbeat.
        assert client._last_ack_time > 0
        assert client._heartbeat_pending_sn is None

    @pytest.mark.asyncio
    async def test_handle_message_heartbeat_mismatch(self):
        """Test handling HeartBeatAck with mismatched sn."""
        from types import SimpleNamespace

        msg = SimpleNamespace(data='{"topic": "HeartBeatAck", "content": {"sn": "wrong_sn"}}')

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._last_heartbeat_sn = "test_sn"

        # Should not raise, just log warning
        await client._handle_message(msg)

    @pytest.mark.asyncio
    async def test_check_liveness_before_first_ack(self):
        """Test _check_liveness does nothing before the first ACK is seen."""
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        await client._check_liveness()

        client.disconnect_callback.assert_not_called()
        assert client.connected is False  # untouched by the check itself

    @pytest.mark.asyncio
    async def test_check_liveness_within_threshold(self):
        """Test _check_liveness leaves a recently-acked connection alone."""
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._last_ack_time = time.monotonic()

        await client._check_liveness()

        client.disconnect_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_liveness_stale_tears_down(self):
        """Test a heartbeat ACK silence past the threshold recycles the socket."""
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True
        # No ACK for well past STALE_HEARTBEAT_SECONDS.
        client._last_ack_time = time.monotonic() - 1000

        await client._check_liveness()

        mock_ws.close.assert_awaited_once()
        assert client.connected is False
        client.disconnect_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_callback(self):
        """Test handling message with callback."""
        from types import SimpleNamespace

        callback = MagicMock()

        msg = SimpleNamespace(data='{"topic": "GenMsgDown", "content": {"data": "test_data"}}')

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=callback,
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        await client._handle_message(msg)

        callback.assert_called_once_with("GenMsgDown", {"data": "test_data"})

    @pytest.mark.asyncio
    async def test_handle_message_invalid_json(self):
        """Test handling invalid JSON."""
        from types import SimpleNamespace

        msg = SimpleNamespace(data="not valid json")

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        # Should not raise
        await client._handle_message(msg)


class TestHaierWebSocketClientDisconnect:
    """Test disconnect method."""

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnect method."""
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True

        await client.disconnect()

        assert client._connected is False
        mock_ws.close.assert_called_once()


class TestHaierWebSocketClientStartListening:
    """Test start_listening method."""

    @pytest.mark.asyncio
    async def test_start_listening(self):
        """Test start_listening creates tasks."""
        mock_hass = MagicMock()
        mock_hass.async_create_background_task = MagicMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            hass=mock_hass,
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
        )

        await client.start_listening()

        assert mock_hass.async_create_background_task.call_count == 2


class TestHaierWebSocketClientConnect:
    """Test connect method."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test connect succeeds."""
        mock_ws = MagicMock()

        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

            assert result is True
            assert client._connected is True
            mock_session.ws_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_uses_token_provider(self):
        """connect() authenticates with the provider's current token.

        The client never stores a token; the handshake must use the fresh token
        returned by ``token_provider`` (which reads the coordinator's OAuth
        gate).
        """
        mock_ws = MagicMock()

        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)

        client = HaierWebSocketClient(
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
            token_provider=lambda: "fresh_token",
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

            assert result is True
            _args, kwargs = mock_session.ws_connect.call_args
            assert kwargs["params"]["token"] == "fresh_token"

    @pytest.mark.asyncio
    async def test_connect_handshake_failure(self):
        """Test connect fails on handshake error."""
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(side_effect=aiohttp.WSServerHandshakeError(None, ()))
        mock_session.close = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

            assert result is False
            assert client._ws is None
            # The session is HA's shared global session: it must not be closed here.
            mock_session.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """Test connect fails on timeout."""
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(side_effect=TimeoutError("Timeout"))
        mock_session.close = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

            assert result is False
            assert client._ws is None
            mock_session.close.assert_not_called()


class TestHaierWebSocketClientDisconnectWithTasks:
    """Test disconnect method with running tasks."""

    @pytest.mark.asyncio
    async def test_disconnect_with_tasks(self):
        """Test disconnect cancels tasks."""
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()

        heartbeat_task = asyncio.create_task(asyncio.sleep(1))
        listener_task = asyncio.create_task(asyncio.sleep(1))

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True
        client._heartbeat_task = heartbeat_task
        client._listener_task = listener_task

        await client.disconnect()

        assert client._connected is False
        assert heartbeat_task.done()
        assert listener_task.done()
        mock_ws.close.assert_called_once()


class TestHaierWebSocketClientHeartbeatLoop:
    """Test _heartbeat_loop method."""

    @pytest.mark.asyncio
    async def test_heartbeat_loop_stops_when_disconnected(self):
        """Test heartbeat loop stops when connected is False."""
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True

        # Start heartbeat loop in background
        task = asyncio.create_task(client._heartbeat_loop())

        # Give it time to send first heartbeat
        await asyncio.sleep(0.1)

        # Stop the loop
        client._connected = False

        # Wait for task to complete
        await asyncio.wait_for(task, timeout=1.0)


class TestHaierWebSocketClientUsesSharedSession:
    """Test that the WebSocket client uses Home Assistant's shared session."""

    @pytest.mark.asyncio
    async def test_connect_uses_shared_session(self):
        """Test connect uses async_get_clientsession and never closes it."""
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ) as mock_get_session:
            result = await client.connect("localhost", 8080)

        assert result is True
        assert client._ws is mock_ws
        # connect() must obtain the shared global session.
        mock_get_session.assert_called_once()
        # The shared session must never be closed by the integration.
        await client.disconnect()
        mock_session.close.assert_not_called()


class TestHaierWebSocketClientHandleMessageCallbackError:
    """Test _handle_message callback exception handling."""

    @pytest.mark.asyncio
    async def test_handle_message_callback_error(self):
        """Test _handle_message when callback raises."""
        from types import SimpleNamespace

        callback = MagicMock(side_effect=ValueError("callback error"))
        msg = SimpleNamespace(data='{"topic": "GenMsgDown", "content": {"data": "test_data"}}')

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=callback,
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        await client._handle_message(msg)
        callback.assert_called_once()


class TestHaierWebSocketClientHeartbeatLoopExceptions:
    """Test _heartbeat_loop method exceptions."""

    @pytest.mark.asyncio
    async def test_heartbeat_loop_handles_exception(self):
        """Test heartbeat loop handles exception inside while loop."""
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock(side_effect=[None, RuntimeError("heartbeat failed")])

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True

        with (
            patch.object(client, "generate_sn", return_value="sn_1_1000"),
            patch(
                "custom_components.haier_home.haier.websocket_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            task = asyncio.create_task(client._heartbeat_loop())
            await asyncio.wait_for(task, timeout=1.0)
            assert task.done()


class TestHaierWebSocketClientListenForMessages:
    """Test _listen_for_messages method."""

    @pytest.mark.asyncio
    async def test_listen_ws_is_none(self):
        """Test _listen_for_messages when _ws is None."""
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = None
        await client._listen_for_messages()

    @pytest.mark.asyncio
    async def test_listen_receive_raises_cancelled(self):
        """Test _listen_for_messages when receive raises CancelledError."""
        mock_ws = MagicMock()
        mock_ws.receive = AsyncMock(side_effect=asyncio.CancelledError)
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True
        await client._listen_for_messages()

    @pytest.mark.asyncio
    async def test_listen_receive_raises_exception(self):
        """Test _listen_for_messages when receive raises generic exception."""
        mock_ws = MagicMock()
        mock_ws.receive = AsyncMock(side_effect=ConnectionError("receive failed"))
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True
        await client._listen_for_messages()

    @pytest.mark.asyncio
    async def test_listen_close_message(self):
        """Test _listen_for_messages handles CLOSE message."""
        mock_ws = MagicMock()
        close_msg = MagicMock()
        close_msg.type = aiohttp.WSMsgType.CLOSE
        close_msg.data = 1000
        close_msg.extra = "normal close"
        mock_ws.receive = AsyncMock(return_value=close_msg)
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True
        await client._listen_for_messages()
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_listen_error_message(self):
        """Test _listen_for_messages handles ERROR message."""
        mock_ws = MagicMock()
        error_msg = MagicMock()
        error_msg.type = aiohttp.WSMsgType.ERROR
        error_msg.data = "protocol error"
        mock_ws.receive = AsyncMock(return_value=error_msg)
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True
        await client._listen_for_messages()
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_listen_closed_message(self):
        """Test _listen_for_messages handles CLOSED message."""
        mock_ws = MagicMock()
        closed_msg = MagicMock()
        closed_msg.type = aiohttp.WSMsgType.CLOSED
        mock_ws.receive = AsyncMock(return_value=closed_msg)
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True
        await client._listen_for_messages()
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_listen_ping_message(self):
        """Test _listen_for_messages handles PING message."""
        mock_ws = MagicMock()
        mock_ws.pong = AsyncMock()
        close_msg = MagicMock()
        close_msg.type = aiohttp.WSMsgType.CLOSE
        close_msg.data = 1000
        close_msg.extra = "done"
        ping_msg = MagicMock()
        ping_msg.type = aiohttp.WSMsgType.PING
        mock_ws.receive = AsyncMock(side_effect=[ping_msg, close_msg])
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True
        await client._listen_for_messages()
        mock_ws.pong.assert_called_once()

    @pytest.mark.asyncio
    async def test_listen_unknown_message_type(self):
        """Test _listen_for_messages handles unknown message type."""
        mock_ws = MagicMock()
        close_msg = MagicMock()
        close_msg.type = aiohttp.WSMsgType.CLOSE
        close_msg.data = 1000
        close_msg.extra = "done"
        unknown_msg = MagicMock()
        unknown_msg.type = aiohttp.WSMsgType.PONG
        mock_ws.receive = AsyncMock(side_effect=[unknown_msg, close_msg])
        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )
        client._ws = mock_ws
        client._connected = True
        await client._listen_for_messages()


class TestHaierWebSocketClientConnectExceptionBranches:
    """Test connect method exception branches."""

    @pytest.mark.asyncio
    async def test_connect_aiohttp_client_error(self):
        """Test connect fails on aiohttp.ClientError."""
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(side_effect=aiohttp.ClientError("client error"))
        mock_session.close = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)
            assert result is False
            assert client._ws is None
            mock_session.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_generic_exception(self):
        """Test connect fails on generic exception."""
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(side_effect=RuntimeError("unexpected"))
        mock_session.close = AsyncMock()

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)
            assert result is False
            assert client._ws is None
            mock_session.close.assert_not_called()


class TestHaierWebSocketClientHandshakeAuthFailure:
    """Test connect() distinguishes token rejection from connection-layer drops."""

    @pytest.mark.asyncio
    async def test_handshake_401_invokes_auth_failure_handler(self):
        """A 401 handshake rejection invokes the auth-failure handler (token refused)."""
        auth_handler = AsyncMock()
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(
            side_effect=aiohttp.WSServerHandshakeError(
                MagicMock(), (), status=401, message="unauthorized"
            )
        )

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
            auth_failure_handler=auth_handler,
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

        assert result is False
        assert client._ws is None
        auth_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handshake_403_invokes_auth_failure_handler(self):
        """A 403 handshake rejection also invokes the auth-failure handler."""
        auth_handler = AsyncMock()
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(
            side_effect=aiohttp.WSServerHandshakeError(
                MagicMock(), (), status=403, message="forbidden"
            )
        )

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
            auth_failure_handler=auth_handler,
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

        assert result is False
        auth_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handshake_non_auth_status_skips_handler(self):
        """A non-401/403 handshake error (e.g. 503) is NOT a token problem."""
        auth_handler = AsyncMock()
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(
            side_effect=aiohttp.WSServerHandshakeError(
                MagicMock(), (), status=503, message="unavailable"
            )
        )

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
            auth_failure_handler=auth_handler,
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

        assert result is False
        auth_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_server_disconnected_skips_auth_handler(self):
        """A connection-layer drop (ServerDisconnectedError) must NOT refresh the token."""
        auth_handler = AsyncMock()
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(
            side_effect=aiohttp.ServerDisconnectedError("Server disconnected")
        )

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
            auth_failure_handler=auth_handler,
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

        assert result is False
        assert client._ws is None
        auth_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handshake_401_without_handler_does_not_raise(self):
        """A 401 with no handler wired still fails cleanly (no crash)."""
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(
            side_effect=aiohttp.WSServerHandshakeError(
                MagicMock(), (), status=401, message="unauthorized"
            )
        )

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

        assert result is False

    @pytest.mark.asyncio
    async def test_auth_handler_exception_swallowed(self):
        """A failing auth-failure handler is logged, not propagated out of connect()."""
        auth_handler = AsyncMock(side_effect=RuntimeError("refresh boom"))
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock(
            side_effect=aiohttp.WSServerHandshakeError(
                MagicMock(), (), status=401, message="unauthorized"
            )
        )

        client = HaierWebSocketClient(
            token_provider=lambda: "test_token",
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
            auth_failure_handler=auth_handler,
        )

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

        assert result is False
        auth_handler.assert_awaited_once()


class TestHaierWebSocketClientMissingToken:
    """Guard behaviour when the token_provider yields no token.

    A ``None``/empty token is meaningless: it must never be serialized into a
    message (``agClientId: null``) or a handshake param. Each call site rejects
    it at use via ``_resolve_token`` and degrades gracefully.
    """

    def _client(self, token_provider):
        return HaierWebSocketClient(
            token_provider=token_provider,
            app_id="test_app_id",
            message_callback=MagicMock(),
            disconnect_callback=MagicMock(),
            hass=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_connect_no_token_returns_false_without_connecting(self):
        """connect() bails out to False and never opens a session on a missing token."""
        mock_session = MagicMock()
        mock_session.ws_connect = AsyncMock()

        client = self._client(lambda: None)

        with patch(
            "custom_components.haier_home.haier.websocket_client.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await client.connect("localhost", 8080)

        assert result is False
        assert client._ws is None
        mock_session.ws_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_command_no_token_returns_none_without_sending(self):
        """send_command() returns None and sends nothing when the token is missing."""
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock()

        client = self._client(lambda: None)
        client._ws = mock_ws
        client._connected = True

        result = await client.send_command([{"deviceId": "device_001", "cmdArgs": {}}])

        assert result is None
        mock_ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_heartbeat_no_token_skips_send(self):
        """send_heartbeat() skips the send (no agClientId: null) on a missing token."""
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock()

        client = self._client(lambda: None)
        client._ws = mock_ws
        client._connected = True

        await client.send_heartbeat()

        mock_ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_bound_devs_no_token_skips_send(self):
        """send_bound_devs() skips the send on a missing token."""
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock()

        client = self._client(lambda: "")  # empty string is also rejected
        client._ws = mock_ws
        client._connected = True

        await client.send_bound_devs(["device_001"])

        mock_ws.send_json.assert_not_called()
