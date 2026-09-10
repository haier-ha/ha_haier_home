"""Config flow for Haier Home integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import (
    async_register_implementation,
)
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DEFAULT_LANGUAGE,
    DEFAULT_REGION,
    DOMAIN,
    LANGUAGE_OPTIONS,
    REDIRECT_URL,
    REGION_OPTIONS,
    ROOM_SYNC_OPTIONS,
    SCENE_SYNC_OPTIONS,
)
from .haier import (
    HaierAPIError,
    HaierHttpClient,
    generate_ag_client_id,
)
from .haier.flow_i18n import translate
from .haier.oauth2 import HaierOAuth2Implementation

_LOGGER = logging.getLogger(__name__)


class HaierHomeConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Handle a config flow for Haier Home."""

    VERSION = 1
    DOMAIN = DOMAIN

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._region: str = DEFAULT_REGION
        self._language: str = ""
        self._token: dict[str, Any] = {}
        self._uid: str = ""
        self._nickname: str = ""
        self._eula_text: str = ""
        self._room_sync_mode: str = "family_and_room"
        self._scene_sync: str = "all_manual"
        self._http_client: HaierHttpClient | None = None
        self._all_scenes: dict[str, list[dict[str, Any]]] = {}
        self._family_names: dict[str, str] = {}
        self._ag_client_id: str = ""
        self._auth_implementation: str = ""

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    def _get_eula_language(self) -> str:
        """Return the language to use for the EULA/risk-notice text.

        At this point in the config flow the user has not yet chosen the
        integration's own language option, so we fall back to Home
        Assistant's global language (``Configuration → General → Language``).
        The per-user Profile language is stored in the frontend's per-user
        storage and is not reachable from a config flow (no user_id context
        is injected during first-time setup), so the system language is the
        best signal we have.
        """
        return self.hass.config.language or DEFAULT_LANGUAGE

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step - redirect to EULA."""
        return await self.async_step_eula()

    async def async_step_eula(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show EULA/risk disclaimer and require acceptance."""
        errors: dict[str, str] = {}
        _LOGGER.debug("async_step_eula: Initializing EULA step")

        if user_input is not None:
            if not user_input.get("eula_accepted", False):
                errors["base"] = "eula_not_accepted"
            else:
                return await self.async_step_region()

        if not self._eula_text:
            # Region is fixed to cn (only supported region); language follows
            # HA's global language so the EULA renders in the same language
            # the user picked for their HA UI.
            eula_language = self._get_eula_language()
            _LOGGER.debug("async_step_eula: EULA language: %s", eula_language)
            http_client = HaierHttpClient(
                hass=self.hass,
                region=DEFAULT_REGION,
                language=eula_language,
            )
            try:
                eula_text = await http_client.get_risk_notice()
            except (TimeoutError, aiohttp.ClientError, HaierAPIError):  # fmt: skip
                _LOGGER.warning(
                    "Failed to fetch risk notice for region %s",
                    DEFAULT_REGION,
                    exc_info=True,
                )
                return self.async_abort(reason="risk_notice_error")
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Unexpected error fetching risk notice for region %s",
                    DEFAULT_REGION,
                )
                return self.async_abort(reason="risk_notice_error")
            self._eula_text = eula_text or ""

        # On validation failure the whole form re-renders and the frontend
        # resets the scroll position to the top, out of view of HA's native
        # error banner (which sits just above the checkbox at the bottom of a
        # long risk notice). Prepend the same hint to the top of the
        # description so the user still sees what to do after the scroll reset.
        # Use a local variable; never mutate the cached ``self._eula_text``.
        display_text = self._eula_text
        if errors:
            lang = self._get_eula_language()
            hint = (
                "> ⚠️ **请阅读风险告知文本，并勾选页面底部的同意条款后再点击「下一步」。**\n\n"
                if lang.startswith("zh")
                else "> ⚠️ **Please read the risk disclosure and check the consent box at the bottom before clicking Next.**\n\n"
            )
            display_text = hint + self._eula_text

        return self.async_show_form(
            step_id="eula",
            data_schema=vol.Schema(
                {
                    vol.Required("eula_accepted", default=False): bool,
                }
            ),
            description_placeholders={"eula_text": display_text},
            errors=errors,
            last_step=False,
        )

    async def async_step_region(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select region and optional language override."""
        _LOGGER.debug("async_step_region: Initializing region step")

        if user_input is not None:
            self._region = user_input["region"]
            self._language = user_input.get("language") or DEFAULT_LANGUAGE
            return await self.async_step_oauth()

        return self.async_show_form(
            step_id="region",
            data_schema=vol.Schema(
                {
                    vol.Required("region", default=DEFAULT_REGION): SelectSelector(
                        SelectSelectorConfig(
                            options=list(REGION_OPTIONS),
                            translation_key="region",
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required("language", default=DEFAULT_LANGUAGE): vol.In(LANGUAGE_OPTIONS),
                }
            ),
            description_placeholders={"redirect_url": REDIRECT_URL},
            last_step=False,
        )

    async def async_step_oauth(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle OAuth authorization."""
        if not self._ag_client_id:
            self._ag_client_id = generate_ag_client_id(self._region)

        implementation = HaierOAuth2Implementation(self.hass, self._ag_client_id, self._region)
        async_register_implementation(self.hass, DOMAIN, implementation)

        return await self.async_step_pick_implementation(user_input={"implementation": DOMAIN})

    async def async_oauth_create_entry(
        self, data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Create config entry after OAuth2 authorization."""
        token = data.get("token")
        if not isinstance(token, dict) or not token.get("access_token"):
            return self.async_abort(reason="token_unset")
        self._token = token
        auth_implementation = data.get("auth_implementation")
        if not isinstance(auth_implementation, str) or not auth_implementation:
            return self.async_abort(reason="auth_implementation_unset")
        self._auth_implementation = auth_implementation

        try:
            self._http_client = HaierHttpClient(
                hass=self.hass,
                region=self._region,
                ag_client_id=self._ag_client_id,
                language=self._language,
                token_provider=lambda: self._token["access_token"],
            )

            account_info = await self._http_client.get_account_info()
            self._uid = account_info.get("userId", "")
            self._nickname = account_info.get("nickName", "")

            return await self.async_step_homes()

        except Exception as err:
            _LOGGER.error("Error processing OAuth callback: %s", err, exc_info=True)
            return self.async_abort(reason="oauth_token_error")

    async def async_step_homes(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select homes, room sync mode, and scene sync option."""
        errors: dict[str, str] = {}

        if self._http_client is None:
            return self.async_abort(reason="no_client")

        try:
            homes_data = await self._http_client.get_homes()
            create_families = homes_data.get("createfamilies", [])
            join_families = homes_data.get("joinfamilies", [])
            all_families = create_families + join_families
        except Exception as err:
            _LOGGER.error("Error fetching homes: %s", err, exc_info=True)
            errors["base"] = "Failed to fetch homes"
            all_families = []

        if user_input is not None:
            selected_homes = user_input.get("homes", [])
            if not selected_homes:
                errors["base"] = "no_homes_selected"
            else:
                self._room_sync_mode = user_input.get("room_sync_mode", "family_and_room")
                self._scene_sync = user_input.get("scene_sync", "all_manual")

                self._family_names = {
                    f.get("familyId"): f.get("familyName", "")
                    for f in all_families
                    if f.get("familyId") in selected_homes
                }

                self._all_scenes = {}
                if self._scene_sync != "none":
                    _LOGGER.debug("Fetching scenes for %d selected families", len(selected_homes))
                    try:
                        raw_scenes = await self._http_client.get_scenes(selected_homes)
                        for family_id, scenes in raw_scenes.items():
                            if family_id in selected_homes:
                                self._all_scenes[family_id] = scenes or []
                        _LOGGER.debug("Cached scenes for %d families", len(self._all_scenes))
                    except Exception as err:
                        _LOGGER.warning("Failed to fetch scenes: %s", err)
                        self._all_scenes = {}

                return await self._async_create_entry(selected_homes)

        default_mark = self._get_default_mark()
        home_options: dict[str, str] = {}
        for family in all_families:
            family_id = family.get("familyId", "")
            family_name = family.get("familyName", "Unknown")
            is_default = family.get("isDefault", 0)
            mark = default_mark if is_default == 1 else ""
            home_options[family_id] = f"{family_name}{mark}"

        room_sync_labels = self._translate_label_map("room_sync_options")
        scene_sync_labels = self._translate_label_map("scene_sync_options")

        return self.async_show_form(
            step_id="homes",
            data_schema=vol.Schema(
                {
                    vol.Required("homes"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=family_id, label=label)
                                for family_id, label in home_options.items()
                            ],
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required("room_sync_mode", default="family_and_room"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=value,
                                    label=room_sync_labels.get(value, value),
                                )
                                for value in ROOM_SYNC_OPTIONS
                            ],
                            multiple=False,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required("scene_sync", default="all_manual"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=value,
                                    label=scene_sync_labels.get(value, value),
                                )
                                for value in SCENE_SYNC_OPTIONS
                            ],
                            multiple=False,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "homes_title": translate(self._language, "homes_title"),
                "homes_desc": translate(self._language, "homes_desc"),
                "homes_label": translate(self._language, "homes_label"),
                "room_sync_label": translate(self._language, "room_sync_label"),
                "scene_sync_label": translate(self._language, "scene_sync_label"),
            },
            errors=errors,
            last_step=False,
        )

    def _get_default_mark(self) -> str:
        """Return the "default home" marker in the user's selected language."""
        value = translate(self._language, "default_mark", default="")
        if not isinstance(value, str):
            _LOGGER.error(
                "Invalid translation type for default_mark in %s: expected str, got %s",
                self._language,
                type(value).__name__,
            )
            return ""
        return value

    def _translate_label_map(self, key: str) -> dict[str, str]:
        """Fetch a ``{value: label}`` selector map with runtime type checking."""
        value = translate(self._language, key, default={})
        if not isinstance(value, dict):
            _LOGGER.error(
                "Invalid translation type for %s in %s: expected dict, got %s",
                key,
                self._language,
                type(value).__name__,
            )
            return {}
        return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}

    async def _async_create_entry(
        self, selected_homes: list[str]
    ) -> config_entries.ConfigFlowResult:
        """Create the config entry with all collected data."""
        entry_uuid = f"{self._region}_{self._uid}"
        await self.async_set_unique_id(entry_uuid)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Haier Smart Home",
            data={
                "region": self._region,
                "token": self._token,
                "homes": selected_homes,
                "uid": self._uid,
                "ag_client_id": self._ag_client_id,
                "language": self._language,
                "room_sync_mode": self._room_sync_mode,
                "scene_sync": self._scene_sync,
                "scenes": self._all_scenes,
                "family_names": self._family_names,
                "auth_implementation": self._auth_implementation,
            },
        )
