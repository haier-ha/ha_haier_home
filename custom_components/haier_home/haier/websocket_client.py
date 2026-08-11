"""Haier WebSocket client module."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


class HaierWebSocketClient:
    """Haier WebSocket client for real-time device communication."""

    HEARTBEAT_INTERVAL = 60
    # A heartbeat that goes unacknowledged longer than this is treated as a
    # stale (half-open) connection, which the listener cannot detect because
    # no CLOSE frame ever arrives.
    STALE_HEARTBEAT_SECONDS = HEARTBEAT_INTERVAL * 3

    def __init__(
        self,
        token_provider: Callable[[], str],
        app_id: str,
        message_callback: Callable[[str, dict], None] | None,
        disconnect_callback: Callable[[], None] | None,
        hass: HomeAssistant,
        auth_failure_handler: Callable[[], Awaitable[None]] | None = None,
    ):
        """Initialise the WebSocket client.

        Args:
            token_provider: Read-only callable returning the current token,
                resolved at handshake time (this client never stores a token).
                Must return a non-empty token; ``None``/empty is meaningless
                here (it would emit ``agClientId: null`` or an invalid
                handshake param) and is rejected at use via ``_resolve_token``.
            app_id: Application id sent as ``appId``.
            message_callback: Called as ``(topic, content)`` for each message.
            disconnect_callback: Called when the connection is lost.
            hass: Home Assistant instance (provides the shared session).
            auth_failure_handler: Async callable invoked when the handshake is
                rejected for a bad token (HTTP 401/403).
        """
        self.app_id = app_id
        self.message_callback = message_callback
        self.disconnect_callback = disconnect_callback
        self._hass = hass
        # Handles a handshake token rejection (401/403), which needs a token
        # refresh rather than a plain reconnect, so it is kept separate from
        # disconnect_callback.
        self._auth_failure_handler = auth_failure_handler
        # Read-only token provider resolved at handshake time. Safe to call
        # while the coordinator holds its refresh lock (no refresh, no lock).
        self._token_provider = token_provider
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._heartbeat_sn = 0
        self._last_heartbeat_time = 0
        self._last_heartbeat_sn: str | None = None
        # Keep-Alive liveness tracking: the most recent heartbeat awaiting an
        # ACK, when it was sent (monotonic), and when the last ACK arrived.
        # ACK silence past STALE_HEARTBEAT_SECONDS marks the link as stale.
        self._heartbeat_pending_sn: str | None = None
        self._heartbeat_pending_sent_at = 0.0
        self._last_ack_time = 0.0
        self._connected = False
        self._heartbeat_task: asyncio.Task | None = None
        self._listener_task: asyncio.Task | None = None

    def generate_sn(self) -> str:
        """Generate an auto-incrementing serial number for messages.

        Format: ``sn_<counter>_<epoch_ms>``, used in heartbeats and command
        requests to correlate acknowledgements.
        """
        self._heartbeat_sn += 1
        return f"sn_{self._heartbeat_sn}_{int(time.time() * 1000)}"

    def generate_trace_id(self) -> str:
        """Generate 32-bit UUID format TraceId."""
        return uuid.uuid4().hex

    def _resolve_token(self) -> str:
        """Resolve the current token via the provider, rejecting a missing one.

        ``agClientId`` and the handshake ``token``/``agClientId`` params are the
        current access token. A ``None``/empty token is meaningless: it would
        emit ``"agClientId": null`` in a message or an invalid handshake param,
        so it is treated as an error here rather than sent to the server.

        Returns:
            The non-empty current access token.

        Raises:
            RuntimeError: If the provider returns ``None`` or an empty token.
        """
        token = self._token_provider()
        if not token:
            raise RuntimeError("token_provider returned no token")
        return token

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._connected

    async def send_heartbeat(self) -> None:
        """Send a ``HeartBeat`` message to keep the WebSocket alive.

        Includes the round-trip duration (ms since the last heartbeat) so
        the server can monitor connection quality. Records the sent sn so the
        matching ``HeartBeatAck`` can be correlated for liveness tracking.
        """
        if not self._ws or not self._connected:
            return

        current_time = int(time.time() * 1000)
        duration = current_time - self._last_heartbeat_time if self._last_heartbeat_time > 0 else 0
        self._last_heartbeat_time = current_time

        try:
            ag_client_id = self._resolve_token()
        except RuntimeError:
            _LOGGER.warning("Skipping heartbeat: no token available")
            return

        sn = self.generate_sn()
        self._last_heartbeat_sn = sn
        self._heartbeat_pending_sn = sn
        self._heartbeat_pending_sent_at = time.monotonic()

        heartbeat_msg = {
            "topic": "HeartBeat",
            "agClientId": ag_client_id,
            "content": {"sn": sn, "duration": duration},
        }
        _LOGGER.debug("Sending heartbeat (sn=%s, duration=%dms)", sn, duration)
        await self._ws.send_json(heartbeat_msg)

    async def send_bound_devs(self, devices: list[str]) -> None:
        """Register a device list with the server via a ``BoundDevs`` message.

        An empty list is skipped. Send failures are best-effort: logged and
        swallowed so a transient push error never tears down the connection.

        Args:
            devices: Device ids to subscribe for push updates.
        """
        if not self._ws or not self._connected:
            return
        if not devices:
            _LOGGER.debug("Skipping empty BoundDevs registration")
            return

        try:
            ag_client_id = self._resolve_token()
        except RuntimeError:
            _LOGGER.warning("Skipping BoundDevs registration: no token available")
            return

        bound_devs_msg = {
            "topic": "BoundDevs",
            "agClientId": ag_client_id,
            "content": {"devs": devices},
        }

        try:
            await self._ws.send_json(bound_devs_msg)
        except Exception:  # noqa: BLE001 - best-effort subscription push
            _LOGGER.warning("Failed to send BoundDevs registration", exc_info=True)

    async def send_command(self, cmds: list[dict]) -> str | None:
        """Send a ``BatchCmdReq`` command message.

        Args:
            cmds: Command entries (each with ``deviceId``, ``index``, ``cmdArgs``).

        Returns:
            The command serial number (``cmd_sn``) on success, or ``None`` if
            the WebSocket is not connected.
        """
        if not self._ws or not self._connected:
            _LOGGER.error("WebSocket not connected, cannot send command")
            return None

        try:
            ag_client_id = self._resolve_token()
        except RuntimeError:
            _LOGGER.warning("Cannot send command: no token available")
            return None

        trace_id = self.generate_trace_id()
        cmd_sn = self.generate_sn()

        cmd_msg = {
            "topic": "BatchCmdReq",
            "agClientId": ag_client_id,
            "content": {"trace": trace_id, "sn": cmd_sn, "data": cmds},
        }
        _LOGGER.debug("HaierWebSocketClient -> Sending command: %s", cmd_msg)
        await self._ws.send_json(cmd_msg)
        return cmd_sn

    async def _handle_message(self, msg: aiohttp.WSMessage) -> None:
        """Decode a text message and dispatch it.

        Heartbeat ACKs update liveness tracking; everything else is forwarded
        to ``message_callback``.

        Args:
            msg: The received WebSocket message.
        """

        msg_str = str(msg.data) if msg.data is not None else ""
        try:
            data = json.loads(msg_str)
            topic = data.get("topic", "")
            content = data.get("content", {})

            if topic == "HeartBeatAck":
                sn = content.get("sn", "")
                self._last_ack_time = time.monotonic()
                if self._heartbeat_pending_sn == sn:
                    latency_ms = (time.monotonic() - self._heartbeat_pending_sent_at) * 1000
                    _LOGGER.debug("Heartbeat ACK (sn=%s) in %.0f ms", sn, latency_ms)
                    self._heartbeat_pending_sn = None
                elif self._last_heartbeat_sn != sn:
                    _LOGGER.warning(
                        "Heartbeat mismatch: expected sn=%s, got sn=%s",
                        self._last_heartbeat_sn,
                        sn,
                    )
            elif self.message_callback:
                try:
                    self.message_callback(topic, content)
                except Exception:
                    _LOGGER.exception("Error in message callback")
        except json.JSONDecodeError:
            _LOGGER.warning("Cannot parse JSON: %s", msg_str[:100])

    async def _heartbeat_loop(self) -> None:
        """Heartbeat loop."""
        await self.send_heartbeat()

        while self._connected:
            try:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                if self._connected:
                    await self.send_heartbeat()
                    await self._check_liveness()
            except asyncio.CancelledError:
                break
            except Exception:
                _LOGGER.exception("Heartbeat failed")
                break

    async def _check_liveness(self) -> None:
        """Detect a stale keep-alive (no ACK past the threshold) and recycle it.

        A half-open TCP connection never delivers a CLOSE frame, so the message
        listener cannot detect it; prolonged heartbeat-ACK silence is the only
        signal. When no ACK has arrived within ``STALE_HEARTBEAT_SECONDS``, log
        a warning and tear the socket down so the coordinator's reconnect loop
        restores the link. ``_last_ack_time`` stays 0 until the first ACK, so a
        freshly-connected link is never misjudged as stale.
        """
        if self._last_ack_time <= 0:
            return
        age = time.monotonic() - self._last_ack_time
        if age <= self.STALE_HEARTBEAT_SECONDS:
            return
        _LOGGER.warning("No heartbeat ACK for %.0fs; WebSocket likely stale, reconnecting", age)
        self._connected = False
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self.disconnect_callback:
            self.disconnect_callback()

    async def _listen_for_messages(self) -> None:
        """Listen for incoming WebSocket messages."""
        if not self._ws:
            _LOGGER.warning("WebSocket is None, cannot listen for messages")
            return

        msg_count = 0
        try:
            while self._connected:
                try:
                    msg = await self._ws.receive()
                except asyncio.CancelledError:
                    break
                except Exception:
                    _LOGGER.exception("Error receiving message.")
                    break

                msg_count += 1

                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg)
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    _LOGGER.warning(
                        "Server requested close: code=%s, reason=%s", msg.data, msg.extra
                    )
                    self._connected = False
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", msg.data)
                    self._connected = False
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    _LOGGER.warning("WebSocket connection closed by peer")
                    self._connected = False
                    break
                elif msg.type == aiohttp.WSMsgType.PING:
                    await self._ws.pong()
                else:
                    _LOGGER.warning("Received unknown message type: %s", msg.type)
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOGGER.exception("Error in message listener.")
        finally:
            # Report the lost connection to the coordinator so it can reconnect.
            # _connected was already cleared on close/error above; the
            # coordinator checks its own stopped flag before scheduling.
            if self._connected:
                self._connected = False
            if self.disconnect_callback:
                self.disconnect_callback()

    async def connect(self, host: str, port: int) -> bool:
        """Open the WebSocket connection and perform the handshake.

        Resolves the token via the provider at handshake time. On a 401/403
        rejection the ``auth_failure_handler`` runs so the caller can retry with
        a refreshed token.

        Args:
            host: WebSocket server host.
            port: WebSocket server port.

        Returns:
            ``True`` when connected, ``False`` on any failure.
        """
        url = f"wss://{host}:{port}/userag"
        # Resolve the token at handshake time through the provider, so the
        # freshest token from the coordinator's OAuth gate is always used. A
        # missing token makes the handshake params meaningless, so fail fast
        # instead of connecting with token=None/agClientId=None.
        try:
            token = self._resolve_token()
        except RuntimeError:
            _LOGGER.warning("Cannot connect WebSocket: no token available")
            return False
        params = {"token": token, "agClientId": token, "appId": self.app_id}

        _LOGGER.info("Connecting to WebSocket: %s", url)

        # Use Home Assistant's managed global session. Its lifecycle is owned
        # by HA, so we never close it here; we only manage the ws connection.
        session = async_get_clientsession(self._hass)

        try:
            self._ws = await session.ws_connect(
                url,
                params=params,
                heartbeat=HaierWebSocketClient.HEARTBEAT_INTERVAL,
                timeout=aiohttp.ClientWSTimeout(ws_receive=None),
            )
            self._connected = True
            # Fresh connection: clear any liveness state left over from a
            # previous link so the new one starts from a clean slate.
            self._last_ack_time = 0.0
            self._heartbeat_pending_sn = None
            # Don't send BoundDevs / heartbeat / start listener here - the
            # coordinator owns the device list and instructs this socket.
            _LOGGER.debug("WebSocket connection established, ready for heartbeat and listener")
        except aiohttp.WSServerHandshakeError as err:
            # Handshake reached the server but was *rejected* at the HTTP layer.
            # A 401/403 means the token was refused: surface it distinctly and
            # invoke the auth-failure handler so the coordinator force-refreshes
            # the token and reconnects (mirrors the HTTP client's 401 retry
            # loop). This is the true "token rejected" path -- distinct from a
            # ServerDisconnectedError, which is a connection-layer drop with no
            # token verdict.
            self._ws = None
            if err.status in (401, 403):
                _LOGGER.warning(
                    "WebSocket handshake rejected (HTTP %s): token refused by server",
                    err.status,
                )
                if self._auth_failure_handler is not None:
                    try:
                        await self._auth_failure_handler()
                    except Exception:  # noqa: BLE001 - handler is best-effort
                        _LOGGER.exception("Auth-failure handler failed after WS handshake reject")
            else:
                _LOGGER.exception("WebSocket handshake failed (HTTP %s)", err.status)
            return False
        except (TimeoutError, aiohttp.ClientError):  # fmt: skip
            # Connection-layer failure (e.g. ServerDisconnectedError): the peer
            # dropped the TCP/handshake before an HTTP verdict. This is NOT a
            # token problem -- do not force a refresh; let the reconnect loop
            # retry with backoff.
            _LOGGER.exception("WebSocket connection failed (connection-layer)")
            self._ws = None
            return False
        except Exception:
            _LOGGER.exception("Unknown error", exc_info=True)
            self._ws = None
            return False
        else:
            return True

    async def disconnect(self) -> None:
        """Disconnect from WebSocket server."""
        _LOGGER.debug("Disconnecting from WebSocket start")
        self._connected = False
        if self._heartbeat_task:
            _LOGGER.debug("Cancel heartbeat task")
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        if self._listener_task:
            _LOGGER.debug("Cancel listener task")
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
            _LOGGER.info("WebSocket disconnected")
        # The aiohttp session is Home Assistant's managed global session, so it
        # is intentionally not closed here (closing it would affect every
        # integration sharing it). HA owns its lifecycle.
        _LOGGER.debug("Disconnecting from WebSocket ops done")

    async def start_listening(self) -> None:
        """Start heartbeat and message listener tasks."""
        assert self._hass is not None
        self._heartbeat_task = self._hass.async_create_background_task(
            self._heartbeat_loop(), "haier_heartbeat_loop"
        )
        self._listener_task = self._hass.async_create_background_task(
            self._listen_for_messages(), "haier_message_listener"
        )

        _LOGGER.debug("Started heartbeat and listener tasks")
