"""Utility functions for Haier API client."""

import logging
import random
import string
import time
import uuid
from collections.abc import Mapping
from typing import Any

_LOGGER = logging.getLogger(__name__)


def generate_instant_id() -> str:
    """Generate a 12-character instance ID with letters and digits."""
    return "HA" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def generate_ag_client_id(area: str) -> str:
    """Generate the client instance identifier.

    Format: {instant_id}.{area}.{ha_uuid}

    Args:
        area: User selected region (e.g., "cn", "sea")

    Returns:
        The formatted client instance identifier
    """
    ha_uuid = str(uuid.uuid4()).replace("-", "")[:16]
    return f"{generate_instant_id()}.{area}.{ha_uuid}"


def mask_token(token: str | None, prefix: int = 4) -> str:
    """Return a masked preview of a token for logging.

    Only the first ``prefix`` characters are shown, so a token can be told
    apart (e.g. whether it changed after a refresh) without exposing it.
    """
    if not token:
        return "<none>"
    return f"{token[:prefix]}***"


def validate_construct_token(token_data: dict[str, Any]) -> dict[str, Any]:
    """Validate and construct token data."""
    if not token_data:
        raise ValueError("Token data is empty")
    if not (
        "accessToken" in token_data and "refreshToken" in token_data and "expiresIn" in token_data
    ):
        raise ValueError("Token data is invalid, missing required fields")
    expires_in = int(token_data["expiresIn"])
    expires_at = time.time() + expires_in
    token = {
        "access_token": token_data["accessToken"],
        "refresh_token": token_data["refreshToken"],
        "expires_in": expires_in,
        "expires_at": expires_at,
    }
    # Masked preview: the prefix identifies the token across produce/refresh.
    _LOGGER.debug(
        "OAuth token prepared: %s (expires_in=%ss)",
        mask_token(token["access_token"]),
        expires_in,
    )
    return token


def validate_token_structure(token: Any) -> None:
    """Validate that a stored token is well-formed; raise ``ValueError`` if not.

    A validate function only checks and raises — it returns ``None`` and does
    not extract business values. A token is well-formed only when it carries
    the four fields the OAuth flow / refresh produce: ``access_token``,
    ``refresh_token``, ``expires_in`` and ``expires_at``.

    Args:
        token: token dict loaded from ``config_entry.data["token"]``.

    Raises:
        TypeError: when ``token`` is not a dict (wrong type).
        ValueError: when the token is missing any of the four required fields.
    """
    if not isinstance(token, dict):
        raise TypeError("Token is not a dict")
    missing = [
        name
        for name, value in (
            ("access_token", token.get("access_token")),
            ("refresh_token", token.get("refresh_token")),
            ("expires_in", token.get("expires_in")),
            ("expires_at", token.get("expires_at")),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Token missing required field(s): {', '.join(missing)}")


def validate_entry_data(data: Mapping[str, Any]) -> None:
    """Validate the config-flow-produced entry data; raise on invalid input.

    The single place that checks the shape of ``config_entry.data`` at setup, so
    the rest of setup can assume these fields exist instead of re-checking them.
    It only validates and raises — it does not return or extract values.

    Error semantics — two distinct kinds of breakage, surfaced as two distinct
    exception types so the caller can react with the right user-facing action:

    * ``ValueError``: the *token* structure is broken. This is recoverable by
      re-authenticating (reauth), so the caller should raise
      ``ConfigEntryAuthFailed``.
    * ``KeyError``: non-token config-flow data (e.g. ``region``, ``language``,
      ``ag_client_id``) is missing/corrupt. Reauth cannot repair this — the user
      must re-run the whole config flow, so the caller should raise
      ``ConfigEntryNotReady`` to surface that.
    """
    try:
        validate_token_structure(data.get("token", {}))
    except (TypeError, ValueError) as err:
        raise ValueError(f"Token problem: {err}") from err

    missing = [field for field in ("ag_client_id", "region", "language") if not data.get(field)]
    if missing:
        raise KeyError(f"Config entry missing field(s): {', '.join(missing)}")
