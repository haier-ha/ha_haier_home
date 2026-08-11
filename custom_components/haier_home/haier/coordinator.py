"""Data coordinator for the Haier Home integration.

Central runtime owner for one config entry. It keeps the OAuth token fresh,
manages the WebSocket connection (connect / reconnect / teardown), dispatches
debounced device commands, and applies incoming push messages to the device
models before notifying entity listeners.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import gzip
import json
import logging
import time
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

from ..const import (
    CLIMATE_DEBOUNCE_MS,
    DEFAULT_REGION,
    TOKEN_BUFFER_INTERVAL,
    TOKEN_REFRESH_INTERVAL,
    WEBSOCKET_CONFIG,
    WS_RECONNECT_MIN_INTERVAL,
)
from ..device import HaierDevice
from .command_debouncer import CommandDebouncer
from .http_client import HaierHttpClient
from .oauth2 import HaierOAuth2Implementation
from .utils import mask_token
from .websocket_client import HaierWebSocketClient

_LOGGER = logging.getLogger(__name__)


class HaierCoordinator:
    """Coordinator for managing Haier device connections and state."""

    def __init__(
        self,
        hass: HomeAssistant,
        region: str,
        devices: dict[str, HaierDevice],
        token: str,
        ag_client_id: str,
        app_id: str,
        token_data: dict | None = None,
        config_entry: ConfigEntry | None = None,
        http_client: HaierHttpClient | None = None,
    ) -> None:
        """Initialise the coordinator.

        Args:
            hass: Home Assistant instance.
            region: Region key selecting the WebSocket host/port.
            devices: Device map (passed by reference; filled in by setup).
            token: Initial access token.
            ag_client_id: Per-install client id for auth and WebSocket.
            app_id: Application id sent with WebSocket/API requests.
            token_data: Full stored token dict (access/refresh/expiry).
            config_entry: The config entry this coordinator belongs to.
            http_client: Pre-built HTTP client, or ``None`` to skip HTTP.
        """
        self._hass = hass
        self._region = region
        self._devices = devices
        self._token = token
        self._ag_client_id = ag_client_id
        self._app_id = app_id
        self._listeners: list[Callable] = []
        self._ws_client: HaierWebSocketClient | None = None
        self._http_client: HaierHttpClient | None = http_client
        self._token_refresh_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._token_data = token_data or {}
        self._oauth_session: OAuth2Session | None = None
        self._config_entry = config_entry
        self._status = "normal"
        # Serializes all token-refresh paths so concurrent callers never
        # refresh twice.
        self._token_lock = asyncio.Lock()
        # True while a token refresh is rebuilding the WebSocket, so
        # _ws_disconnected skips scheduling a redundant reconnect.
        self._ws_reconnecting = False
        # Serializes the whole WebSocket lifecycle so refresh and reconnect
        # paths never race on self._ws_client.
        self._ws_lock = asyncio.Lock()
        # Set by async_stop; background loops check it and exit on teardown.
        self._stopped = False
        # Monotonic time of the last token-driven reconnect. Debounces
        # reconnects to at most one per WS_RECONNECT_MIN_INTERVAL so a burst of
        # token refreshes cannot become a burst of reconnects.
        self._last_ws_token_reconnect_at = 0.0

        ws_config = WEBSOCKET_CONFIG[region]
        self._ws_host = str(ws_config["host"])
        self._ws_port = int(ws_config["port"])

        # Debounce downstream device commands (leading + trailing, merged per
        # attribute key, bucketed by device_id). See
        # docs/command-debounce-design.md.
        self._command_debouncer = CommandDebouncer(
            hass,
            CLIMATE_DEBOUNCE_MS,
            self._send_now,
            trailing=True,
        )

    def _ws_disconnected(self) -> None:
        """Handle an unexpected connection drop from the WebSocketClient.

        Schedules a reconnect via :meth:`_schedule_reconnect`, unless the
        coordinator is stopped, or the drop is part of a token-refresh rebuild
        (``_ws_reconnecting``, whose rebuild itself reconnects).
        """
        _LOGGER.info(
            "Use token %s to handle WebSocket disconnected, scheduling reconnect",
            mask_token(self._token),
        )
        if self._stopped:
            return
        if self._ws_reconnecting:
            _LOGGER.debug("_ws_disconnected during token-refresh WS rebuild; skipping reconnect")
            return
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Start the reconnect loop in a background task (idempotent)."""
        _LOGGER.debug("Scheduling reconnect task")
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return  # reconnect loop is already running
        if self._stopped:
            return
        self._reconnect_task = self._hass.async_create_background_task(
            self._reconnect_loop(),
            "haier_reconnect_loop",
        )
        _LOGGER.debug("Scheduled reconnect task")

    @property
    def devices(self) -> dict[str, HaierDevice]:
        """Return all managed devices."""
        return self._devices

    @property
    def region(self) -> str:
        """Return area/family name."""
        return self._region

    @property
    def connected(self) -> bool:
        """Return connection status."""
        if not self._ws_client:
            return False
        return self._ws_client.connected

    @property
    def status(self) -> str:
        """Return the current status."""
        return self._status

    def _configure_oauth(self, config_entry: ConfigEntry | None = None) -> None:
        """Bind this coordinator to the OAuth2 session for its own config entry.

        Builds the ``HaierOAuth2Implementation`` from this entry's own
        ``region``/``ag_client_id`` and wraps it in an :class:`OAuth2Session`, so
        every account's coordinator is isolated from the other entries.

        Idempotent: calling again with an already-initialised :attr:`_oauth_session`
        is a no-op, so ``async_setup_entry`` can configure OAuth up-front and
        ``async_start`` can call it again as a fallback.
        """
        if self._oauth_session is not None:
            return
        if config_entry is not None:
            self._config_entry = config_entry
        if self._config_entry is None:
            _LOGGER.debug("_configure_oauth skipped: no config entry")
            return

        region = self._config_entry.data.get("region", DEFAULT_REGION)
        ag_client_id = self._config_entry.data.get("ag_client_id", "")
        if not ag_client_id:
            # ag_client_id is required for every authenticated request (HTTP
            # clientId, WebSocket agClientId and the OAuth refresh clientId).
            # Skip building an OAuth session and let _refresh_token surface the
            # actionable "error_no_oauth_session" status instead of failing
            # cryptically on every refresh.
            _LOGGER.error(
                "Config entry %s missing required ag_client_id; OAuth session not "
                "built — re-add the account to regenerate credentials",
                self._config_entry.entry_id,
            )
            self._oauth_session = None
            return
        implementation = HaierOAuth2Implementation(self._hass, ag_client_id, region)
        self._oauth_session = OAuth2Session(self._hass, self._config_entry, implementation)
        _LOGGER.debug(
            "OAuth2Session initialized (region=%s, ag_client_id=%s)", region, ag_client_id
        )

    async def _ensure_dependencies_ready(self) -> bool:
        """Make the integration dependencies (token + HTTP + WebSocket) ready.

        Explicit, ordered readiness called at setup entry BEFORE any cloud call,
        so by the time we pull data the auth stack is fully live:

          1. verify / refresh the token (fail -> return False -> caller reauths)
          2. initialise the HTTP client session
          3. build + connect the WebSocket with the current token

        Returns ``False`` when the token could not be made valid.
        """
        self._configure_oauth()
        if not await self._refresh_token():
            return False
        if self._http_client:
            await self._http_client.async_init()
            _LOGGER.debug("HTTP client session initialized")
        await self._connect()
        return True

    def _current_access_token(self) -> str:
        """Return the current access_token (read-only, no refresh, no lock).

        The single source of truth is the in-memory token the refresh gate
        maintains (``self._token_data`` / ``self._token``), updated the instant
        a refresh succeeds. It is read here directly instead of
        ``config_entry.data["token"]`` because ``async_update_entry`` writes
        back asynchronously: reading the entry could return the previous token
        for a scheduling tick and put HTTP and WS on different generations.
        Both consumers read this, so they always share the exact same token.
        """
        if isinstance(self._token_data, dict):
            token = self._token_data.get("access_token")
            if token:
                return token
        return self._token

    def _token_needs_refresh(self) -> bool:
        """Return whether the access token needs refreshing.

        Refreshes when the token is already expired or will expire within the
        next ``TOKEN_BUFFER_INTERVAL`` seconds (early-refresh window),
        comparing the ``expires_at`` epoch timestamp against ``time.time()``,
        or when HA's built-in :attr:`OAuth2Session.valid_token` reports it
        invalid. Returns ``False`` only when the session is not initialised.
        When ``expires_at`` is unset the token cannot be verified as fresh, so
        it is treated as needing a refresh rather than trusted or crashed on.
        """
        if self._oauth_session is None:
            _LOGGER.debug("OAuth session not initialised; skipping refresh check")
            return False
        # Judge freshness against the in-memory token (the single source of
        # truth the refresh gate keeps up to date), NOT config_entry.data,
        # whose write-back via async_update_entry is delayed. Reading the entry
        # could see a just-refreshed token as still stale and trigger a second,
        # redundant refresh — the exact cause of HTTP and WS ending up on
        # different token generations.
        token = self._token_data if isinstance(self._token_data, dict) else {}
        expires_at = token.get("expires_at")
        if expires_at is None:
            # A token with no expiry timestamp cannot be validated; force a
            # refresh instead of trusting it or raising out of setup.
            _LOGGER.debug("Token expires_at unset; treating as needing refresh")
            return True

        seconds_left = expires_at - time.time()
        _LOGGER.debug("Token expires_at=%s (~%ds left)", expires_at, seconds_left)

        if expires_at <= time.time() + TOKEN_BUFFER_INTERVAL:
            # Refresh when the token is already expired or will expire within
            # the next TOKEN_BUFFER_INTERVAL seconds (early-refresh window).
            _LOGGER.debug("Token within refresh window, needs refresh")
            return True

        _LOGGER.debug("Token is still valid")
        return False

    async def _refresh_token(self, force: bool = False) -> bool:
        """Refresh the OAuth2 access token (the single refresh gate).

        Checks, refreshes, and writes the new token back to
        ``config_entry.data["token"]``. Does not touch the WebSocket;
        reconnecting with the new token is the caller's job. Runs under
        :attr:`_token_lock` so refreshes never run concurrently.

        Args:
            force: Refresh regardless of the expiry window. Use when the server
                has already rejected the token (HTTP 401, refused handshake).

        Returns:
            ``True`` when the token is valid; ``False`` on failure (the caller
            keeps the previous token).
        """
        if self._oauth_session is None:
            _LOGGER.error("OAuth session not initialised")
            self._status = "error_no_oauth_session"
            return False

        async with self._token_lock:
            if not force and not self._token_needs_refresh():
                return True
            try:
                # Refresh via the OAuth implementation directly: it recomputes
                # expires_at from the server's expires_in, unlike
                # async_ensure_token_valid() which short-circuits on a still-valid
                # token and would skip the early-refresh window above.
                _LOGGER.debug("Attempting OAuth token refresh")
                new_token_data = await self._oauth_session.implementation.async_refresh_token(
                    self._oauth_session.token
                )
                # Fail-fast guards: stop this refresh on any broken result so
                # the caller keeps the previous token and the loop retries.
                if not ("expires_in" in new_token_data and "expires_at" in new_token_data):
                    _LOGGER.error("Token refresh returned data missing expires_in/expires_at")
                    self._status = "error_refresh_failed"
                    return False
                if not self._config_entry:
                    _LOGGER.error("Config entry is unset during token refresh")
                    self._status = "error_refresh_failed"
                    return False

                new_token = new_token_data.get("access_token")
                if not new_token:
                    _LOGGER.error("Token refresh failed for access_token is unset")
                    self._status = "error_refresh_failed"
                    return False

                self._token_data = new_token_data
                self._token = new_token
                self._status = "normal"

                self._hass.config_entries.async_update_entry(
                    self._config_entry,
                    data={**self._config_entry.data, "token": new_token_data},
                )
                _LOGGER.debug(
                    "OAuth token refreshed: %s (new TTL: ~%ss)",
                    mask_token(new_token),
                    new_token_data.get("expires_in"),
                )
            except Exception:
                _LOGGER.exception("Failed to refresh token.")
                self._status = "error_refresh_failed"
                return False

        return True

    async def _reconnect_ws(self) -> bool:
        """Reconnect the WebSocket with the current (latest) token.

        Tears down and rebuilds an existing socket with the current token. When
        no socket exists yet, delegates to :meth:`_connect`.

        Returns:
            ``True`` when the socket ends up connected, ``False`` otherwise.
        """
        if self._ws_client is None:
            # No socket built yet: first connect is _connect's job (it builds
            # the client and handshakes with the current token). Delegate rather
            # than fabricate a "reconnect" of a socket that never existed.
            _LOGGER.debug("_reconnect_ws: no socket yet, delegating to _connect")
            await self._connect()
            return self.connected

        async with self._ws_lock:
            self._ws_reconnecting = True
            try:
                _LOGGER.debug(
                    "Reconnecting WebSocket with updated token (token=%s)",
                    mask_token(self._current_access_token()),
                )
                if self.connected:
                    await self._ws_client.disconnect()
                result = await self._ws_client.connect(self._ws_host, self._ws_port)
                if result:
                    _LOGGER.info("WebSocket reconnected successfully with new token")
                    await self._ws_client.start_listening()
                    await self._ws_client.send_bound_devs(list(self._devices.keys()))
                    return True
                _LOGGER.error("Failed to reconnect WebSocket after token refresh")
            finally:
                self._ws_reconnecting = False

        # Reconnect failed. This path is reached e.g. when the handshake was
        # rejected 401/403: _handle_ws_handshake_auth_failure has already
        # force-refreshed the token, but _reconnect_ws itself does not retry.
        # Hand off to the backoff reconnect loop (outside _ws_lock, and only
        # after _ws_reconnecting is cleared, so it can rebuild cleanly) so
        # recovery does not stall until the next disconnect/refresh event.
        if not self._stopped:
            self._schedule_reconnect()
        return False

    async def _sync_ws_to_current_token(self, previous_token: str | None) -> None:
        """Bring the WebSocket onto the current token after a refresh (debounced).

        Rebuilds the socket only when the token actually changed and at least
        ``WS_RECONNECT_MIN_INTERVAL`` seconds have passed since the last
        token-driven reconnect, so a flapping refresh window cannot cause a
        reconnect storm.

        Args:
            previous_token: The access token seen before the caller's refresh.
        """
        if self._current_access_token() == previous_token:
            return
        now = time.monotonic()
        elapsed = now - self._last_ws_token_reconnect_at
        if self._last_ws_token_reconnect_at and elapsed < WS_RECONNECT_MIN_INTERVAL:
            _LOGGER.debug(
                "Skipping token-driven WS reconnect (debounced, %.0fs < %ds)",
                elapsed,
                WS_RECONNECT_MIN_INTERVAL,
            )
            return
        self._last_ws_token_reconnect_at = now
        await self._reconnect_ws()

    async def _handle_auth_failure(self) -> None:
        """React to a server-side auth rejection (HTTP 401/403, refused handshake).

        The server rejected the current token, so the local ``expires_at``
        cannot be trusted (the token may have been revoked/expired server-side).
        Force a refresh regardless of the expiry window; on success reconnect
        the WebSocket with the new token. This is one of the auth-failure
        channels that keep token refresh + WS reconnect closed-loop even though
        both have periodic timings.
        """
        if await self._refresh_token(force=True):
            # Token recovered: make sure the WebSocket runs with the new one.
            # An auth failure is a hard signal (server actively rejected us), so
            # reconnect immediately -- NOT via the debounced sync path -- but
            # still stamp the reconnect time so the periodic refresh loop does
            # not pile a second reconnect on top within the debounce window.
            self._last_ws_token_reconnect_at = time.monotonic()
            await self._reconnect_ws()
            return
        # Force refresh failed (e.g. the refresh_token itself is dead) -> reauth.
        self._status = "error_auth_failed"
        _LOGGER.error(
            "Server rejected the token and force refresh failed; "
            "re-authentication is required for entry %s",
            self._config_entry.entry_id if self._config_entry else "<unknown>",
        )

    async def _handle_ws_handshake_auth_failure(self) -> None:
        """Force-refresh the token after a WebSocket handshake is rejected (401/403).

        Invoked by :class:`HaierWebSocketClient` from inside ``connect()`` while
        the coordinator holds :attr:`_ws_lock`, so it must NOT reconnect here
        (that also takes ``_ws_lock`` and would deadlock). It only refreshes the
        token; the surrounding ``_connect``/``_reconnect_loop`` retry handshakes
        with the fresh token. ``_refresh_token`` uses the separate
        ``_token_lock``, so this is safe under the WS lock.
        """
        if not await self._refresh_token(force=True):
            self._status = "error_auth_failed"
            _LOGGER.error(
                "WebSocket handshake rejected and force refresh failed; "
                "re-authentication is required for entry %s",
                self._config_entry.entry_id if self._config_entry else "<unknown>",
            )

    async def _token_refresh_loop(self) -> None:
        """Background loop that periodically refreshes the token.

        Sleeps ``TOKEN_REFRESH_INTERVAL`` between checks, refreshes when needed,
        syncs the WebSocket to the new token, and backs off exponentially on
        failure. Exits when the coordinator is stopped.
        """
        _LOGGER.debug("Token refresh loop started")

        failure_count = 0
        min_retry_interval = 60
        max_retry_interval = TOKEN_REFRESH_INTERVAL

        while not self._stopped:
            try:
                if self._token_needs_refresh():
                    _LOGGER.info("Token needs refresh, attempting to refresh...")
                    before = self._current_access_token()
                    if await self._refresh_token():
                        failure_count = 0
                        # The token may have changed: bring the WebSocket up to
                        # date with the new one so the long-lived socket never
                        # runs longer than a refresh cycle on a stale token.
                        # Converged + debounced through _sync_ws_to_current_token
                        # so a flapping refresh window cannot storm reconnects.
                        await self._sync_ws_to_current_token(before)
                    else:
                        failure_count += 1
                        _LOGGER.warning("Token refresh failed, attempt %d", failure_count)

                if failure_count > 0:
                    retry_interval = min(
                        min_retry_interval * (2 ** (failure_count - 1)),
                        max_retry_interval,
                    )
                    _LOGGER.debug("Waiting %d seconds before next retry", retry_interval)
                    await asyncio.sleep(retry_interval)
                else:
                    await asyncio.sleep(TOKEN_REFRESH_INTERVAL)

            except asyncio.CancelledError:
                _LOGGER.debug("Token refresh loop cancelled")
                break
            except Exception:
                _LOGGER.exception("Error in token refresh loop")
                failure_count += 1
                retry_interval = min(
                    min_retry_interval * (2 ** (failure_count - 1)),
                    max_retry_interval,
                )
                await asyncio.sleep(retry_interval)

    def async_add_listener(self, callback: Callable) -> Callable:
        """Register a listener called on device-state changes.

        Args:
            callback: Zero-arg callable invoked when device state updates.

        Returns:
            An unsubscribe function that removes the listener.
        """
        self._listeners.append(callback)

        def _unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return _unsubscribe

    def _notify_listeners(self) -> None:
        """Call all registered listeners."""
        for listener in self._listeners:
            listener()

    def _on_message(self, topic: str, content: dict) -> None:
        """Route an incoming WebSocket message by topic.

        Args:
            topic: Message topic; only ``GenMsgDown`` is handled.
            content: Decoded message content.
        """
        _LOGGER.debug("Received message: topic=%s", topic)

        if topic == "GenMsgDown":
            self._handle_gen_msg_down(content)
        else:
            _LOGGER.warning("coordinator: Unhandled topic: %s", topic)

    def _handle_gen_msg_down(self, content: dict) -> None:
        """Dispatch a ``GenMsgDown`` message by ``businType``.

        Handles ``DigitalModelHA`` (attribute updates), ``DevOfflineNotify`` and
        ``DevOnlineNotify`` (device online/offline); anything else is ignored.

        Args:
            content: Decoded ``GenMsgDown`` content.
        """
        busin_type = content.get("businType", "")
        if busin_type == "DigitalModelHA":
            self._handle_digital_model_ha(content)
        elif busin_type in ("DevOfflineNotify", "DevOnlineNotify"):
            self._handle_dev_online_notify(content, busin_type == "DevOnlineNotify")
        else:
            _LOGGER.debug("Ignored GenMsgDown businType: %s", busin_type)

    def _handle_dev_online_notify(self, content: dict, online: bool) -> None:
        """Apply a device online/offline notification and refresh the UI.

        Args:
            content: Decoded notification content (base64 ``data`` of devs).
            online: ``True`` for an online notification, ``False`` for offline.
        """
        data = content.get("data", "")
        if not data:
            return

        try:
            first_json = json.loads(base64.b64decode(data).decode("utf-8"))
            for device_id in first_json.get("devs") or []:
                device = self._devices.get(device_id)
                if device is None:
                    _LOGGER.debug(
                        "Ignored %s for unknown device %s",
                        "online" if online else "offline",
                        device_id,
                    )
                    continue
                device.set_online(online)
                _LOGGER.debug("Device %s is %s", device_id, "online" if online else "offline")
            self._notify_listeners()
        except Exception:
            _LOGGER.exception(
                "Failed to parse %s", "DevOnlineNotify" if online else "DevOfflineNotify"
            )

    def _handle_digital_model_ha(self, content: dict) -> None:
        """Apply a ``DigitalModelHA`` attribute-update message to its device.

        Args:
            content: Decoded message content; ``data`` is base64, and
                ``args`` may be gzip-compressed (``H4sI`` prefix).
        """
        data = content.get("data", "")
        if not data:
            return

        try:
            first_layer = base64.b64decode(data).decode("utf-8")
            first_json = json.loads(first_layer)
            if (
                "args" in first_json
                and isinstance(first_json["args"], str)
                and first_json["args"].startswith("H4sI")
            ):
                compressed_args = base64.b64decode(first_json["args"])
                decompressed_args = gzip.decompress(compressed_args)
                args_json = json.loads(decompressed_args.decode("utf-8"))
                first_json["args"] = args_json
            device_id = first_json.get("dev", "")
            if device_id and device_id in self._devices:
                device = self._devices[device_id]
                # Flatten the wire payload into the uniform envelope the
                # device model expects. The transport-specific
                # ``args.attributes`` shape is confined to this adapter so
                # HaierDevice stays agnostic of how the cloud packs updates.
                args = first_json.get("args") or {}
                attrs = args.get("attributes") if isinstance(args, dict) else None
                device.async_on_message({"data": list(attrs or [])})
                self._notify_listeners()
                _LOGGER.debug("Updated device %s attributes", device_id)
            else:
                _LOGGER.debug(
                    "Ignored message for %s device %s",
                    "unknown" if device_id else "empty",
                    device_id or "(none)",
                )
        except Exception:
            _LOGGER.exception("Failed to parse GenMsgDown")

    async def async_send_command(self, device_id: str, commands: dict) -> bool:
        """Debounce, then send a command to a device.

        Bursts to the same device are merged per attribute key inside a short
        window (leading + trailing); the first command in an idle window is
        sent immediately for instant UI feedback. See
        docs/command-debounce-design.md.

        Args:
            device_id: Target device id.
            commands: Attribute name -> value map to apply.

        Returns:
            ``True`` if the command was sent or accepted for merging.
        """
        return await self._command_debouncer.async_submit(device_id, commands)

    async def _send_now(self, device_id: str, commands: dict) -> bool:
        """Send a command to a device via the WebSocket connection.

        Builds a ``BatchCmdReq`` payload (one entry per parameter) and forwards
        it to the WebSocket client.

        Args:
            device_id: Target device id.
            commands: Attribute name -> value map to apply.

        Returns:
            ``True`` on success; ``False`` if the WebSocket is not connected or
            the device is unknown.
        """
        if not self.connected or not self._ws_client:
            _LOGGER.warning("Cannot send command: WebSocket not connected")
            return False

        if device_id not in self._devices:
            _LOGGER.warning("Device %s not found", device_id)
            return False

        cmd_list = []
        for idx, (param_name, value) in enumerate(commands.items()):
            cmd_list.append(
                {"deviceId": device_id, "index": idx, "cmdArgs": {param_name: str(value)}}
            )

        try:
            cmd_sn = await self._ws_client.send_command(cmd_list)
            if cmd_sn is None:
                _LOGGER.error("Failed to send command to device %s (WS not connected)", device_id)
                return False
        except Exception:
            _LOGGER.exception("Error sending command to device %s", device_id)
            return False
        else:
            return True

    async def _connect(self) -> None:
        """Connect to WebSocket server with retry logic."""
        if self._stopped:
            _LOGGER.debug("_connect skipped: coordinator is stopped")
            return

        # Ensure the token is valid before the first handshake, WITHOUT forcing.
        # _refresh_token is the single, locked refresh gate shared with HTTP, so
        # a plain call only refreshes when the token actually needs it and is a
        # no-op otherwise. This keeps HTTP and WS on the exact same token: the
        # coordinator refreshes once, both consumers read it via
        # _current_access_token. A genuine server-side rejection is still
        # handled by the 401/403 auth-failure path (_handle_ws_handshake_auth_failure),
        # which is the only place that force-refreshes. Runs OUTSIDE _ws_lock
        # (a refresh may itself take _ws_lock to rebuild).
        await self._refresh_token()

        # Build -> connect -> listen runs atomically under _ws_lock so it never
        # interleaves with the token-refresh rebuild or the reconnect loop.
        async with self._ws_lock:
            if self._stopped:
                _LOGGER.debug("_connect skipped: coordinator stopped under ws lock")
                return
            if self.connected and self._ws_client:
                _LOGGER.debug("_connect skipped: already connected")
                return

            self._ws_client = HaierWebSocketClient(
                app_id=self._app_id,
                message_callback=self._on_message,
                disconnect_callback=self._ws_disconnected,
                hass=self._hass,
                token_provider=self._current_access_token,
                auth_failure_handler=self._handle_ws_handshake_auth_failure,
            )

            _LOGGER.info(
                "Use token %s to connect to WebSocket: %s:%d",
                mask_token(self._current_access_token()),
                self._ws_host,
                self._ws_port,
            )
            result = await self._ws_client.connect(self._ws_host, self._ws_port)

            if result:
                _LOGGER.info("WebSocket connection established successfully")

                await self._ws_client.start_listening()
                # Register the coordinator's device list with the socket.
                await self._ws_client.send_bound_devs(list(self._devices.keys()))
                _LOGGER.debug("Started background tasks")
                self._status = "normal"
                self._notify_listeners()
            else:
                _LOGGER.error(
                    "Failed to establish WebSocket connection to %s:%d",
                    self._ws_host,
                    self._ws_port,
                )

            _LOGGER.debug("_connect task completed, result=%s", result)

            # Start reconnect task if connection failed
            if not self.connected and not self._stopped:
                self._schedule_reconnect()

    async def _reconnect_loop(self) -> None:
        """Reconnect loop with exponential backoff."""
        _LOGGER.debug(
            "Use token %s to start Reconnect loop", mask_token(self._current_access_token())
        )

        min_retry_interval = 10
        max_retry_interval = 300
        failure_count = 0

        while not self._stopped:
            try:
                if self.connected:
                    _LOGGER.debug("Reconnect loop exiting: already connected")
                    break

                failure_count += 1
                retry_interval = min(
                    min_retry_interval * (2 ** (failure_count - 1)),
                    max_retry_interval,
                )

                _LOGGER.info(
                    "Attempting to reconnect WebSocket (attempt %d), waiting %d seconds",
                    failure_count,
                    retry_interval,
                )
                await asyncio.sleep(retry_interval)

                if self._stopped:
                    _LOGGER.debug("Reconnect loop exiting: coordinator stopped")
                    break

                # Ensure the token is valid before reconnecting, WITHOUT forcing.
                # Reuse the shared refresh gate so a reconnect does not mint a new
                # token when the current one is still valid — that is what kept
                # HTTP and WS on different token generations. A connection-layer
                # drop (ServerDisconnectedError) is NOT a token verdict, so the
                # existing token is reused; only a real 401/403 handshake
                # rejection force-refreshes, via _handle_ws_handshake_auth_failure.
                await self._refresh_token()

                # Fast-path: skip if already connected, in case a refresh or
                # another path rebuilt the connection while we were on the gate.
                if self.connected:
                    _LOGGER.debug("Reconnect loop: already connected, skipping rebuild")
                    break

                # Teardown + recreate + connect is atomic under _ws_lock so the
                # rebuild never interleaves with the refresh path or other loops.
                async with self._ws_lock:
                    # Re-check under the lock: the refresh may have rebuilt the
                    # socket between the fast-path check and acquiring the lock.
                    if self.connected and self._ws_client:
                        _LOGGER.debug(
                            "Reconnect loop: already connected under ws lock, skipping rebuild"
                        )
                        break

                    # Tear down the previous client before creating a new one.
                    if self._ws_client:
                        with contextlib.suppress(Exception):
                            await self._ws_client.disconnect()

                    ws_client = HaierWebSocketClient(
                        app_id=self._app_id,
                        message_callback=self._on_message,
                        disconnect_callback=self._ws_disconnected,
                        hass=self._hass,
                        token_provider=self._current_access_token,
                        auth_failure_handler=self._handle_ws_handshake_auth_failure,
                    )

                    # Re-check stopped before storing the reference: async_stop
                    # may have fired mid-build; disconnect the orphan and exit.
                    if self._stopped:
                        with contextlib.suppress(Exception):
                            await ws_client.disconnect()
                        _LOGGER.debug("Reconnect loop exiting: coordinator stopped mid-connect")
                        break

                    self._ws_client = ws_client

                    result = await self._ws_client.connect(self._ws_host, self._ws_port)
                    if result:
                        _LOGGER.info("WebSocket reconnected successfully")
                        await self._ws_client.start_listening()
                        # Register the coordinator's device list on the socket.
                        await self._ws_client.send_bound_devs(list(self._devices.keys()))
                        # A successful reconnect runs the socket with the current
                        # token, so clear any error_ws_reconnect_failed left by a
                        # failed refresh commit — surface recovery to callers.
                        self._status = "normal"
                        self._notify_listeners()
                        break
                    _LOGGER.warning("Reconnect attempt %d failed", failure_count)

            except asyncio.CancelledError:
                _LOGGER.debug("Reconnect loop cancelled")
                break
            except Exception:
                _LOGGER.exception("Error in reconnect loop")
                await asyncio.sleep(min_retry_interval)

        self._reconnect_task = None

    async def async_start(self) -> None:
        """Subscribe the loaded device list over the socket and start services.

        setup_entry calls ``_ensure_dependencies_ready`` first (token + HTTP +
        an initial WebSocket connect) before loading the device list, so the
        socket is already live here; drops are recovered by the reconnect loop.
        This method only registers the device list the coordinator now holds and
        starts the background token refresh loop.
        """

        # The socket is just a channel; it does not own the device list. Now
        # that the real devices are loaded, instruct it to subscribe them.
        if self._ws_client and self.connected:
            await self._ws_client.send_bound_devs(list(self._devices.keys()))

        # Only create token refresh task if not already running
        if self._token_refresh_task is None or self._token_refresh_task.done():
            self._token_refresh_task = self._hass.async_create_background_task(
                self._token_refresh_loop(),
                "haier_token_refresh_loop",
            )
            _LOGGER.debug("Created token refresh task: %s", self._token_refresh_task)

    async def async_stop(self) -> None:
        """Stop the coordinator."""
        _LOGGER.info("async_stop called")

        # Signal stop first so background loops exit before we await their tasks.
        self._stopped = True

        # Cancel any pending debounce timers so their callbacks never fire
        # against a torn-down coordinator. Pending merged commands are
        # discarded (acceptable per design).
        self._command_debouncer.async_cancel()

        # Cancel reconnect task first (may be blocked on connect();
        # use a short timeout so the caller is never stuck waiting).
        if self._reconnect_task:
            _LOGGER.info("Cancelling reconnect_task: %s", self._reconnect_task)
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._reconnect_task, timeout=10)
            self._reconnect_task = None

        # Cancel token refresh task
        if self._token_refresh_task:
            _LOGGER.info("Cancelling token_refresh_task: %s", self._token_refresh_task)
            self._token_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._token_refresh_task, timeout=10)
            self._token_refresh_task = None

        # Disconnect under _ws_lock to await any in-flight rebuild/connect
        # before tearing the client down.
        if self._ws_client:
            _LOGGER.info("Disconnecting WebSocket client")
            async with self._ws_lock:
                if self._ws_client:
                    await self._ws_client.disconnect()

        # Close HTTP client
        if self._http_client:
            _LOGGER.info("Closing HTTP client session")
            await self._http_client.close()

        _LOGGER.info("Coordinator stopped")
