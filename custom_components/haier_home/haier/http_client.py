"""HTTP client for the Haier cloud REST API.

Wraps the authenticated REST calls used during setup and runtime (homes,
devices, digital models, scenes, account, logout). Handles request signing,
per-request token resolution and a single 401/403 refresh-and-retry.
"""

import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from ..const import (
    API_ENDPOINT_MAP,
    API_HOSTS_MAP,
    APP_ID,
    APP_VERSION,
    DEFAULT_LANGUAGE,
    DEFAULT_REGION,
)

_LOGGER = logging.getLogger(__name__)


class HaierAPIError(Exception):
    """Raised when the Haier API returns a business-level error (retCode != 00000)."""

    def __init__(self, error_code: str | None = None, error_message: str | None = None) -> None:
        """Initialise the error.

        Args:
            error_code: The API ``retCode`` returned by the server.
            error_message: The API ``retInfo`` message, if any.
        """
        self.error_code = error_code
        self.error_message = error_message
        _LOGGER.warning(
            "Haier API request failed [%s]: %s",
            error_code,
            error_message or "(no message)",
        )
        super().__init__("Haier API request failed")

    def __str__(self) -> str:
        if self.error_code and self.error_message:
            return f"Haier API request failed [{self.error_code}]: {self.error_message}"
        if self.error_code:
            return f"Haier API request failed [{self.error_code}]"
        return "Haier API request failed"


class HaierHttpClient:
    """Authenticated REST client for the Haier cloud API."""

    def __init__(
        self,
        hass: HomeAssistant,
        region: str = DEFAULT_REGION,
        ag_client_id: str | None = None,
        language: str | None = None,
        token_provider: Callable[[], str | None] | None = None,
        auth_failure_handler: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Initialise the client.

        Args:
            hass: Home Assistant instance (provides the shared aiohttp session).
            region: Region key selecting the API host (e.g. ``"cn"``).
            ag_client_id: Per-install client id sent as ``clientId`` header.
            language: ``Accept-Language`` value for API responses.
            token_provider: Sync callable returning the current token
                (read-only, no refresh). This is the client's ONLY way to
                obtain a token — the client never holds one itself. In normal
                operation it is wired to the coordinator's
                ``_current_access_token``; the one-shot logout client passes a
                provider returning the entry's static token. May be set after
                construction, before the first request.
            auth_failure_handler: Async callable invoked on HTTP 401/403 to
                force a token refresh before the request is retried once.
        """
        self._hass = hass
        self._region = region
        self._host = API_HOSTS_MAP[region]
        self._app_id = APP_ID
        self._app_version = APP_VERSION
        self._ag_client_id = ag_client_id
        self._app_key = ""
        self._language = language or DEFAULT_LANGUAGE
        self._session: aiohttp.ClientSession | None = None
        self._closed = False
        self.token_provider = token_provider
        self.auth_failure_handler = auth_failure_handler

    async def _ensure_session(self) -> None:
        """Ensure an aiohttp session is available (idempotent).

        Uses Home Assistant's managed global session so all HTTP requests
        share HA's connection pool, SSL and proxy configuration. ``hass`` is a
        required constructor argument because a production client always runs
        within Home Assistant and must not fall back to a private session.
        """
        if self._closed:
            raise RuntimeError("HaierHttpClient has been closed")

        if self._session is None or self._session.closed:
            self._session = aiohttp_client.async_get_clientsession(self._hass)

    async def async_init(self) -> None:
        """Initialise the HTTP client session."""
        await self._ensure_session()

    def _generate_signature(self, url: str, body: str = "") -> tuple[str, str]:
        """Generate a SHA-256 signature for API request authentication.

        Args:
            url: Request endpoint path used in the signing string.
            body: Serialized request body; whitespace is stripped before signing.

        Returns:
            The ``(signature, timestamp)`` pair, where ``timestamp`` is the
            millisecond epoch used in the signing string.
        """
        timestamp = str(int(time.time() * 1000))
        if body:
            body = body.replace(" ", "").replace("\t", "").replace("\r", "").replace("\n", "")

        sign_str = f"{url}{body}{self._app_id}{self._app_key}{timestamp}"
        return hashlib.sha256(sign_str.encode("utf-8")).hexdigest(), timestamp

    async def _build_auth_kwargs(
        self,
        url: str,
        endpoint: str,
        signature_required: bool,
        request_kwargs: dict,
    ) -> dict:
        """Build a request kwargs dict with a fresh auth header/signature.

        Called per attempt so a 401/403 retry rebuilds the header with the
        newly refreshed token and a fresh signature. ``request_kwargs`` is
        never mutated: each attempt gets its own headers/body snapshot.

        Args:
            url: Full request URL used for signing.
            endpoint: API endpoint path (for error messages).
            signature_required: Add the app-level SHA-256 ``sign``/``timestamp``
                header when set and ``_app_key`` is configured.
            request_kwargs: Caller-supplied kwargs (``headers``, ``data``/``json``).

        Returns:
            A new kwargs dict with headers, ``accessToken`` and serialized body.
        """
        headers = dict(request_kwargs.get("headers", {}))
        headers["Connection"] = "keep-alive"
        headers["Content-Type"] = "application/json;charset=utf-8"
        headers["appId"] = self._app_id
        headers["appVersion"] = self._app_version
        headers["clientId"] = self._ag_client_id
        headers["Accept-Language"] = self._language
        headers["timestamp"] = str(int(time.time() * 1000))
        headers["User-Agent"] = "Apache-HttpClient/4.5.14 (Java/1.8.0_442)"

        # The client holds no token; the provider is the only source. Normal
        # operation wires it to the coordinator's read-only current token; the
        # one-shot logout client injects a provider returning the entry's token.
        if self.token_provider is None:
            raise RuntimeError(f"No token_provider configured for request to {endpoint}")

        access_token = self.token_provider()
        if not access_token:
            raise RuntimeError(f"token_provider returned no token for request to {endpoint}")

        headers["accessToken"] = access_token

        body = request_kwargs.get("data", "")
        if not body:
            body = request_kwargs.get("json", "")

        if body and isinstance(body, dict):
            body_str = json.dumps(body)
        else:
            body_str = str(body)

        if signature_required and self._app_key:
            signature, timestamp = self._generate_signature(url, body_str)
            headers["sign"] = signature
            headers["timestamp"] = timestamp

        build_kwargs = dict(request_kwargs)
        # The body is serialized into ``data`` above, so drop any ``json``
        # key from the copy — aiohttp raises if both ``data`` and ``json`` are
        # passed to the same request.
        build_kwargs.pop("json", None)
        build_kwargs["headers"] = headers
        build_kwargs["data"] = body_str
        return build_kwargs

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        signature_required: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Make an authenticated HTTP request to the Haier API.

        Signs and sends the request, then validates the API response code. On
        HTTP 401/403 the ``auth_failure_handler`` runs and the request is
        retried once with a freshly built header.

        Args:
            method: HTTP method (``"GET"`` / ``"POST"``).
            endpoint: API endpoint path appended to the region host.
            signature_required: Whether to add the app-level signature header.
            **kwargs: Extra request kwargs (``data``/``json``/``headers``).

        Returns:
            The ``data`` payload from the decoded API response.

        Raises:
            HaierAPIError: When the API returns a non-``00000`` ``retCode``.
        """
        url = f"https://{self._host}{endpoint}"

        _LOGGER.debug("Making %s request to %s", method, url)
        await self._ensure_session()
        assert self._session is not None

        async def _send() -> Any:
            req_kwargs = await self._build_auth_kwargs(url, endpoint, signature_required, kwargs)
            async with self._session.request(method, url, **req_kwargs) as resp:
                try:
                    resp.raise_for_status()
                except aiohttp.ClientResponseError as err:
                    # A 401/403 means the server rejected our token. If a
                    # handler is wired (the coordinator force-refreshes the
                    # token and reconnects the WebSocket) we invoke it and give
                    # the request one retry with the fresh token. A handler
                    # failure is logged and the original error re-raised so the
                    # root cause is not masked.
                    if err.status in (401, 403) and self.auth_failure_handler is not None:
                        _LOGGER.warning(
                            "Auth rejected (%s %s -> HTTP %s); refreshing token and retrying",
                            method,
                            url,
                            err.status,
                        )
                        try:
                            await self.auth_failure_handler()
                        except Exception as refresh_err:
                            _LOGGER.exception("Auth handler failed during retry")
                            # Keep the original 401 as the root cause.
                            raise err from refresh_err
                        retry_kwargs = await self._build_auth_kwargs(
                            url, endpoint, signature_required, kwargs
                        )
                        async with self._session.request(method, url, **retry_kwargs) as retry_resp:
                            retry_resp.raise_for_status()
                            return await self._parse_response(retry_resp, endpoint)
                    _LOGGER.warning(
                        "HTTP request failed: %s %s -> HTTP %s",
                        method,
                        url,
                        err.status,
                    )
                    raise
                return await self._parse_response(resp, endpoint)

        return await _send()

    async def _parse_response(self, resp: aiohttp.ClientResponse, endpoint: str) -> Any:
        """Decode and validate a Haier API response, raising on business errors.

        Args:
            resp: The aiohttp response to decode as JSON.
            endpoint: API endpoint path (for log messages).

        Returns:
            The ``data`` payload, or the whole response when no ``data`` key.

        Raises:
            HaierAPIError: When the response ``retCode`` is not ``00000``.
        """
        try:
            result = await resp.json()
        except (ValueError, TypeError):  # fmt: skip
            _LOGGER.exception("Failed to decode JSON response from %s", endpoint)
            raise

        _LOGGER.debug("Response from %s -> %s", endpoint, result.get("retCode"))

        if result.get("retCode") != "00000":
            raise HaierAPIError(result.get("retCode"), result.get("retInfo"))

        return result.get("data", result)

    async def get_risk_notice(self) -> str | None:
        """Fetch the risk/privacy notice text.

        This is an unauthenticated call (no access token). Returns the notice
        content, or ``None`` when unavailable or the request fails.
        """
        headers = {
            "Connection": "keep-alive",
            "Content-Type": "application/json;charset=utf-8",
            "appId": self._app_id,
            "appVersion": self._app_version,
            "Accept-Language": self._language,
            "timestamp": str(int(time.time() * 1000)),
            "User-Agent": "Apache-HttpClient/4.5.14 (Java/1.8.0_442)",
        }
        risk_notice_url = f"https://{self._host}{API_ENDPOINT_MAP['risk_notice']}"

        try:
            await self._ensure_session()
            assert self._session is not None
            async with self._session.get(risk_notice_url, headers=headers) as resp:
                resp.raise_for_status()
                result = await resp.json()
                if result.get("retCode") == "00000":
                    return result.get("data", {}).get("content")
                return None
        except (TimeoutError, aiohttp.ClientError) as e:  # fmt: skip
            _LOGGER.warning("Failed to get risk notice: %s", e)
            return None

    async def close(self) -> None:
        """Release resources held by this client.

        The aiohttp session is Home Assistant's managed global session, so it
        is intentionally *not* closed here (closing it would affect every
        integration sharing it). We only drop our reference and mark the
        client closed so no further requests are made through it.
        """
        self._closed = True
        self._session = None

    async def get_homes(self) -> Any:
        """Get family list (both created and joined families)."""
        return await self._make_request("GET", API_ENDPOINT_MAP["homes"])

    async def get_scenes(self, family_ids: list[str]) -> Any:
        """Get scene list for specified families.

        Args:
            family_ids: List of family IDs to get scenes for
        """
        data = {"familyIds": family_ids}
        return await self._make_request("POST", API_ENDPOINT_MAP["scenes"], json=data)

    async def get_devices(self, family_ids: list[str] | None = None) -> dict[str, Any]:
        """Get devices, optionally filtered by family IDs.

        Args:
            family_ids: Optional list of family IDs to filter devices
        """
        result = await self._make_request("GET", API_ENDPOINT_MAP["devices"])
        device_infos = result.get("deviceInfos", [])

        total_count = len(device_infos)

        if not family_ids:
            _LOGGER.debug("Fetched %d devices (no family filter)", total_count)
            return {"deviceInfos": device_infos}

        # Filter devices by selected family IDs
        device_infos = [device for device in device_infos if device.get("familyId") in family_ids]
        _LOGGER.debug(
            "Fetched %d devices, %d after filtering by family_ids",
            total_count,
            len(device_infos),
        )
        return {"deviceInfos": device_infos}

    async def get_device_digital_model(self, device_id: str) -> Any:
        """Get device digital model (attributes and metadata).

        Args:
            device_id: Device ID to get digital model for
        """
        data = {"deviceId": device_id}
        return await self._make_request("POST", API_ENDPOINT_MAP["device_digital_model"], data=data)

    async def execute_scene(self, family_id: str, scene_id: str) -> Any:
        """Execute a scene.

        Args:
            family_id: Family ID containing the scene
            scene_id: Scene ID to execute
        """
        data = {"familyId": family_id, "sceneId": scene_id}
        return await self._make_request("POST", API_ENDPOINT_MAP["execute_scene"], data=data)

    async def get_account_info(self) -> Any:
        """Get the current account's profile information."""
        return await self._make_request("GET", API_ENDPOINT_MAP["account_info"])

    async def logout(self) -> Any:
        """Log out, invalidating the current access token server-side."""
        return await self._make_request("POST", API_ENDPOINT_MAP["logout"])
