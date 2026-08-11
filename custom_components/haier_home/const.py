"""Constants for the Haier Home integration."""

DOMAIN = "haier_home"

# Supported regions
# Region options shown in the config flow. Only the keys (region codes) are
# used to build the selector; the displayed label now comes from the HA
# translation files (``selector.region.options.<code>`` in
# ``translations/*.json``) so it follows the user's frontend language.
REGION_OPTIONS = {
    "cn": "中国大陆",
}
# Default region
DEFAULT_REGION = "cn"
# Default language (BCP-47, aligned with translations/<lang>.json filenames)
DEFAULT_LANGUAGE = "zh-Hans"

# Display language options. Keys are BCP-47 language tags used as the
# integration's internal language code and as the i18n filename stem.
LANGUAGE_OPTIONS = {
    "zh-Hans": "中文",
    "en": "English",
}

# OAuth configuration
OAUTH2_AUTH_URL = "https://account.haier.com/oauth/authorize"
OAUTH2_TOKEN_URL = "https://account.haier.com/oauth/token"
OAUTH2_CALLBACK_URL = "http://homeassistant.local:8123/auth/external/callback"

# API hosts mapping by region
API_HOSTS_MAP = {
    DEFAULT_REGION: "ha.haier.net",
}

# API endpoints mapping
API_ENDPOINT_MAP = {
    "token": "/api-gw/ha/se/account/token",
    "refresh_token": "/api-gw/ha/se/account/refresh/token",
    "risk_notice": "/api-gw/ha/se/risk/notice",
    "homes": "/api-gw/ha/se/fam/list",
    "scenes": "/api-gw/ha/se/scene/list",
    "devices": "/api-gw/ha/se/dev/list",
    "device_digital_model": "/api-gw/ha/se/dev/digitalmodels",
    "execute_scene": "/api-gw/ha/se/scene/exec",
    "account_info": "/api-gw/ha/se/account/info",
    "logout": "/api-gw/ha/se/account/logout",
}

# WebSocket configuration
WEBSOCKET_CONFIG: dict[str, dict[str, str | int]] = {
    DEFAULT_REGION: {
        "host": "ha-gw.haier.net",
        "port": 59502,
    },
}

# Application configuration
APP_ID = "MB-ISP72111109101-0004"
OAUTH2_CLIENT_ID = "SV-ISP72111109101-0004"
APP_VERSION = "1.0.0"

# appTypeCode → device type mapping
DEVICE_TYPE_MAP: dict[str, str] = {
    "A177": "AC",
    "A178": "AC",
    "A120": "AC",
}

# Platforms to forward during setup
PLATFORMS: list[str] = ["climate", "scene"]

# Event bus command event name
EVENT_SEND_COMMAND = f"{DOMAIN}_send_command"

# Config flow language options.

# Room sync options (stable keys). Display labels live in
# translations/<lang>.json / haier/i18n under the selector segment.
ROOM_SYNC_OPTIONS = [
    "none",
    "family_and_room",
    "room_only",
    "family_only",
]

# Room sync modes that actually generate an area name, in the deterministic
# order used to enumerate a device's "owned" area-name candidates
# (see device.build_area_name_candidates). This deliberately excludes "none"
# (which yields no name) and the ordering is significant: it keeps the
# candidate list stable for logging/equality and de-duplication.
MANAGED_AREA_SYNC_MODES = [
    "family_and_room",
    "room_only",
    "family_only",
]

# Scene sync options. The cloud only exposes manual scenes (no automation
# scenes), so this collapses to "sync all (manual) scenes" vs "do not sync".
# Legacy entries may still carry the removed "all" value; runtime treats any
# non-"none" value as "sync".
SCENE_SYNC_OPTIONS = [
    "all_manual",
    "none",
]

TOKEN_REFRESH_INTERVAL = 3600  # 1 hours
TOKEN_BUFFER_INTERVAL = 86400  # 1 day

# Minimum spacing between two token-driven WebSocket reconnects. A token
# refresh that actually changes the token asks the long-lived socket to
# reconnect with the new one; this floor stops a rapid series of refreshes
# (e.g. a misconfigured/flapping refresh window) from becoming a rapid series
# of reconnects that the cloud gateway rate-limits (seen as a burst of
# ServerDisconnectedError on the WebSocket handshake).
WS_RECONNECT_MIN_INTERVAL = 30  # seconds

# Command debounce windows (see docs/command-debounce-design.md). These are
# deliberately not user-configurable; both are far below the climate
# optimistic-state confirm timeout (_MODE_SWITCH_CONFIRM_TIMEOUT = 15s).
#   - Climate: leading + trailing, merged per attribute key, keyed by
#     device_id. 300ms absorbs a burst of taps on temperature +/- while
#     keeping the first tap instant.
#   - Scene: leading-only, keyed by scene_id. 1000ms swallows accidental
#     double-taps; stateless scenes must never be delayed/replayed.
CLIMATE_DEBOUNCE_MS = 300
SCENE_DEBOUNCE_MS = 1000
