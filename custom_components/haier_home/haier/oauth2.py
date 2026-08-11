"""Haier OAuth2 implementation for Home Assistant."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    API_ENDPOINT_MAP,
    API_HOSTS_MAP,
    APP_ID,
    APP_VERSION,
    DOMAIN,
    OAUTH2_AUTH_URL,
    OAUTH2_CALLBACK_URL,
    OAUTH2_CLIENT_ID,
)
from .http_client import HaierAPIError
from .utils import mask_token, validate_construct_token

_LOGGER = logging.getLogger(__name__)


class HaierOAuth2Implementation(config_entry_oauth2_flow.AbstractOAuth2Implementation):
    """Haier OAuth2 implementation."""

    def __init__(self, hass: HomeAssistant, ag_client_id: str, region: str) -> None:
        """Initialize the implementation."""
        self.hass = hass
        self._domain = DOMAIN
        self._region = region
        self._ag_client_id = ag_client_id

    @property
    def name(self) -> str:
        """Name of the implementation."""
        return f"Haier Home ({self._region})"

    @property
    def domain(self) -> str:
        """Domain that is providing the implementation."""
        return self._domain

    @property
    def client_id(self) -> str:
        """Client ID."""
        return self._ag_client_id

    @property
    def authorize_url(self) -> str:
        """Authorize URL."""
        return OAUTH2_AUTH_URL

    @property
    def token_url(self) -> str:
        """Token URL."""
        host = API_HOSTS_MAP[self._region]
        return f"https://{host}{API_ENDPOINT_MAP['token']}"

    @property
    def scope(self) -> list[str]:
        """Scope for the OAuth2 request."""
        return []

    @property
    def redirect_uri(self) -> str:
        """Redirect URI."""
        return OAUTH2_CALLBACK_URL

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        """Generate authorize URL."""
        from urllib.parse import urlencode

        from homeassistant.helpers.config_entry_oauth2_flow import _encode_jwt

        state = _encode_jwt(self.hass, {"flow_id": flow_id, "redirect_uri": self.redirect_uri})
        params = {
            "redirect_uri": self.redirect_uri,
            "client_id": OAUTH2_CLIENT_ID,
            "response_type": "code",
            "state": state,
        }
        return f"{self.authorize_url}?{urlencode(params)}"

    async def async_resolve_external_data(self, external_data: dict[str, Any]) -> dict[str, Any]:
        """Resolve external data to token."""
        code = external_data.get("code")
        if not code:
            raise ValueError("Missing 'code' in OAuth callback data")

        _LOGGER.debug("Resolving OAuth authorization code for region %s", self._region)

        data = {
            "code": code,
            "clientId": self._ag_client_id,
            "redirectUri": self.redirect_uri,
            "grantType": "authorization_code",
        }
        body_str = json.dumps(data)
        timestamp = str(int(time.time() * 1000))

        headers = {
            "Connection": "keep-alive",
            "Content-Type": "application/json;charset=utf-8",
            "appId": APP_ID,
            "appVersion": APP_VERSION,
            "clientId": self._ag_client_id,
            "Accept-Language": "zh",
            "timestamp": timestamp,
            "User-Agent": "Apache-HttpClient/4.5.14 (Java/1.8.0_442)",
        }

        session = async_get_clientsession(self.hass)
        async with session.post(self.token_url, data=body_str, headers=headers) as resp:
            # Check HTTP status first so non-JSON error pages do not shadow
            # the real HTTP-level failure with a JSONDecodeError.
            resp.raise_for_status()
            result = await resp.json()

            if result.get("retCode") != "00000":
                raise HaierAPIError(
                    error_code=result.get("retCode"),
                    error_message=result.get("retInfo", "Token request failed"),
                )
            token_data = result.get("data", {})
            token = validate_construct_token(token_data)
            # Token initially issued by the OAuth authorization flow.
            _LOGGER.debug(
                "OAuth token issued: %s (region=%s)",
                mask_token(token.get("access_token")),
                self._region,
            )
            return token

    async def _async_refresh_token(self, token: dict[str, Any]) -> dict[str, Any]:
        """Refresh access token."""
        host = API_HOSTS_MAP[self._region]
        refresh_url = (
            f"https://{host}{API_ENDPOINT_MAP.get('refresh_token', API_ENDPOINT_MAP['token'])}"
        )
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh token available")

        _LOGGER.debug("Refreshing OAuth token for region %s", self._region)

        data = {
            "refreshToken": refresh_token,
            "clientId": self._ag_client_id,
            "grantType": "refresh_token",
        }
        body_str = json.dumps(data)
        timestamp = str(int(time.time() * 1000))

        headers = {
            "Connection": "keep-alive",
            "Content-Type": "application/json;charset=utf-8",
            "appId": APP_ID,
            "appVersion": APP_VERSION,
            "clientId": self._ag_client_id,
            "Accept-Language": "zh",
            "timestamp": timestamp,
            "User-Agent": "Apache-HttpClient/4.5.14 (Java/1.8.0_442)",
        }

        session = async_get_clientsession(self.hass)
        async with session.post(refresh_url, data=body_str, headers=headers) as resp:
            # Check HTTP status first so non-JSON error pages do not shadow
            # the real HTTP-level failure with a JSONDecodeError.
            resp.raise_for_status()
            result = await resp.json()

            if result.get("retCode") != "00000":
                raise HaierAPIError(
                    error_code=result.get("retCode"),
                    error_message=result.get("retInfo", "Token refresh failed"),
                )

            token_data = result.get("data", {})
            token = validate_construct_token(token_data)
            # Refreshed on demand with the stored refresh_token.
            _LOGGER.debug(
                "OAuth token refreshed via refresh_token: %s (region=%s)",
                mask_token(token.get("access_token")),
                self._region,
            )
            return token
