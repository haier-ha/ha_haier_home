"""Climate platform for Haier Home integration."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util.unit_conversion import TemperatureConverter, TemperatureDeltaConverter

from .const import DOMAIN
from .device import DataStep, HaierDevice
from .entity import HaierDeviceEntity
from .haier.coordinator import HaierCoordinator

_LOGGER = logging.getLogger(__name__)

# How long (seconds) to keep reporting the pre-command state after a mode
# switch before giving up on confirmation and falling back to the live device
# state. This guards against the pending state getting stuck if the device
# never reports the requested operationMode (e.g. it rejected/clamped the
# command).
_MODE_SWITCH_CONFIRM_TIMEOUT = 15


@HaierDeviceEntity.register_platform("climate")
class HaierClimateEntity(HaierDeviceEntity, ClimateEntity):
    """Climate entity for Haier Home AC devices."""

    _attr_name = None
    # Enables icon/state translations lookup under
    # `entity.climate.haier_climate.*` in icons.json / translations/*.json.
    # `_attr_name = None` keeps the entity name as the device name; no
    # translated name is provided under this key, so naming is unaffected.
    _attr_translation_key = "haier_climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    # Opt in to the new TURN_ON/TURN_OFF feature model (see supported_features)
    # and skip HA's legacy backwards-compatibility shim, which otherwise logs a
    # deprecation warning for climate entities exposing HVACMode.OFF.
    _enable_turn_on_off_backwards_compatibility = False

    # Raw operationMode code -> HA HVACMode name.
    #
    # Kept one-to-one on purpose: the raw codes "3" (fan_only) and "5" (heat)
    # were dropped because no currently supported AC model uses them (their
    # operationMode enums use "6" for fan_only and "4" for heat). Removing the
    # duplicate targets keeps hvac_modes free of duplicate HVACMode entries and
    # makes reverse-mapping unambiguous.
    #
    # If a future device exposes "3"/"5" in its operationMode enum, re-add them
    # here; note hvac_modes would then need explicit de-duplication.
    MODE_NAME_MAP: dict[str, str] = {
        "0": "auto",
        "1": "cool",
        "2": "dry",
        "4": "heat",
        "6": "fan_only",
    }

    # Raw windSpeed code -> stable HA fan_mode key.
    #
    # These keys have matching translations (translations/*.json,
    # strings.json) and icons (icons.json), so they render as localized
    # labels with proper icons. Codes NOT listed here are still surfaced via
    # a dynamic fallback (see _fan_mode_map) using the cloud enum's ``desc``,
    # so a model reporting an unknown speed is not silently dropped.
    FAN_MODE_MAP: dict[str, str] = {
        "1": "high",
        "2": "medium",
        "3": "low",
        "4": "quiet",
        "5": "auto",
        "6": "fast",
        "7": "mid_high",
        "8": "mid_low",
    }

    # Display order for the fan-mode picker. ``auto`` is not an airflow
    # magnitude, so it is pinned to the top; the remaining known speeds are
    # ordered strongest -> weakest (independent of raw windSpeed code order).
    # Modes not listed here (e.g. dynamic desc-fallback speeds) are appended
    # after these, preserving their original enum order.
    FAN_MODE_ORDER: list[str] = [
        "auto",
        "fast",
        "high",
        "mid_high",
        "medium",
        "mid_low",
        "low",
        "quiet",
    ]

    def __init__(
        self, coordinator: HaierCoordinator, device: HaierDevice, description: Any | None = None
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, device, description)
        self._attr_unique_id = f"haier_home_{coordinator.region}_{device.device_id}_climate"

        # Pending mode-switch tracking. When the user switches to a non-off
        # mode we send onOffStatus + operationMode together, but the device
        # may report these in separate messages. To avoid flickering through
        # an intermediate "on + stale mode" state, we keep reporting the
        # pre-command mode until the device confirms the requested one (or the
        # confirmation window elapses).
        self._pending_target_mode: str | None = None
        self._pre_command_hvac_mode: HVACMode | None = None
        self._pending_unsub: Callable[[], None] | None = None

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current HVAC mode.

        While a mode switch is awaiting confirmation, keep reporting the
        pre-command mode instead of the (possibly inconsistent) intermediate
        state the device reports before it has applied both ``onOffStatus``
        and ``operationMode``. Once the device's returned data confirms the
        requested mode -- or the confirmation window elapses -- the live
        device state is reported again.
        """
        if self._pending_target_mode is not None:
            if self._is_mode_switch_confirmed():
                self._clear_pending_mode_switch()
            else:
                return self._pre_command_hvac_mode

        return self._live_hvac_mode()

    def _live_hvac_mode(self) -> HVACMode | None:
        """Return the HVAC mode derived directly from live device state."""
        on_off = self.get_value("onOffStatus")
        if on_off in ("0", "false", False):
            return HVACMode.OFF

        mode_value = self.get_value("operationMode")
        if mode_value is None:
            return None

        mode_name = self.MODE_NAME_MAP.get(str(mode_value))
        if mode_name is None:
            return None
        return HVACMode(mode_name)

    def _is_mode_switch_confirmed(self) -> bool:
        """Return True once the device data reflects the requested mode.

        Confirmation requires the unit to be on *and* the reported
        ``operationMode`` to match the requested target, i.e. the combined
        power-on + mode command has been fully applied.
        """
        on_off = self.get_value("onOffStatus")
        if on_off in ("0", "false", False):
            return False
        current_mode = self.get_value("operationMode")
        return str(current_mode) == str(self._pending_target_mode)

    def _arm_mode_switch_timeout(self) -> None:
        """(Re)start the pending mode-switch confirmation timeout."""
        self._cancel_pending_timer()
        if self.hass is not None:
            self._pending_unsub = async_call_later(
                self.hass,
                _MODE_SWITCH_CONFIRM_TIMEOUT,
                self._on_mode_switch_timeout,
            )

    @callback
    def _on_mode_switch_timeout(self, _now: Any) -> None:
        """Give up waiting for confirmation and report the live state."""
        self._pending_unsub = None
        if self._pending_target_mode is not None:
            _LOGGER.debug(
                "Mode switch confirmation timed out for device %s; falling back to live state",
                self._device.device_id,
            )
            self._clear_pending_mode_switch()
            self.async_write_ha_state()

    def _clear_pending_mode_switch(self) -> None:
        """Clear any pending mode-switch tracking state."""
        self._pending_target_mode = None
        self._pre_command_hvac_mode = None
        self._cancel_pending_timer()

    def _cancel_pending_timer(self) -> None:
        """Cancel the pending confirmation timeout, if scheduled."""
        if self._pending_unsub is not None:
            self._pending_unsub()
            self._pending_unsub = None

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available HVAC modes."""
        modes: list[HVACMode] = [HVACMode.OFF]

        attr = self._device.get_attribute("operationMode")
        if attr is not None and attr.is_enum:
            for v in attr.get_enum_values():
                mode_name = self.MODE_NAME_MAP.get(str(v))
                if mode_name is not None:
                    modes.append(HVACMode(mode_name))
        else:
            for mode_name in self.MODE_NAME_MAP.values():
                modes.append(HVACMode(mode_name))

        return modes

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action, derived from hvac_mode.

        Haier AC devices do not expose a separate running/compressor state
        attribute, so the action is inferred directly from the mode. This
        mirrors the behavior of other HA climate integrations without a
        dedicated running-state signal.
        """
        mode = self.hvac_mode
        if mode is None:
            return None

        # AUTO is intentionally omitted: in auto mode the unit decides between
        # cooling and heating on its own, and without a compressor/running-state
        # signal we cannot know which one is active. Reporting IDLE would falsely
        # suggest the unit is doing nothing, so we return None (unknown) instead.
        return {
            HVACMode.OFF: HVACAction.OFF,
            HVACMode.COOL: HVACAction.COOLING,
            HVACMode.HEAT: HVACAction.HEATING,
            HVACMode.DRY: HVACAction.DRYING,
            HVACMode.FAN_ONLY: HVACAction.FAN,
        }.get(mode)

    def _target_temp_step(self) -> DataStep | None:
        """Return the targetTemperature DataStep, or None if unavailable.

        Thin wrapper over the shared base helper so the climate-specific
        attribute name lives in one place.
        """
        return self._get_data_step("targetTemperature")

    @property
    def target_temperature(self) -> float | None:
        """Return the current target temperature.

        The value the cloud reports shares the scale of the attribute's
        min/max/step, so it is used as reported. A value reported outside
        those bounds is treated as "no setpoint" (``None``) rather than shown
        verbatim.
        """
        return self.get_number_value("targetTemperature")

    def _inward_bound(self, celsius: float, *, is_min: bool) -> float:
        """Round a native (Celsius) bound *inward* on the display unit's grid.

        HA displays the min/max in the user's unit system, rounding to whole
        Fahrenheit via symmetric round(). For a Celsius min of 23.0 that yields
        23 C -> 73.4 F -> round -> 73 F, but 73 F converts back to 22.78 C,
        below the true 23.0 C minimum. HA validates the incoming setpoint
        against the native bound *before* the entity runs, so the user can pick
        the displayed 73 F only to have it rejected ("22.77... is not valid").

        To keep every displayed/selectable value round-trip valid, the bound is
        rounded *inward* on the display grid -- ceil for the min, floor for the
        max -- then converted back to the native unit and returned. So
        23.0 C -> 73.4 F -> ceil -> 74 F -> 23.33 C is returned as the min:
        HA then shows 74 F (74.0 rounds to 74) and 74 F round-trips to 23.33 C,
        which passes validation and is snapped back onto the device's 1 C grid
        by DataStep._quantize on the way out.

        The returned value is always in the entity's native unit, so HA still
        performs exactly one display conversion -- there is no double convert.
        When the system unit matches the native unit (both Celsius) the value is
        returned unchanged.
        """
        if self.hass is None:
            return celsius

        system_unit = self.hass.config.units.temperature_unit
        if system_unit == self.temperature_unit:
            return celsius

        display = TemperatureConverter.convert(celsius, self.temperature_unit, system_unit)
        display = math.ceil(display) if is_min else math.floor(display)
        return TemperatureConverter.convert(display, system_unit, self.temperature_unit)

    @property
    def min_temp(self) -> float:
        """Return the minimum target temperature.

        Rounded inward (up) on the display unit's grid so the lowest selectable
        value round-trips back within the device's native range. See
        :meth:`_inward_bound`.
        """
        value = self.get_number_min("targetTemperature")
        if value is None:
            return -1
        return self._inward_bound(value, is_min=True)

    @property
    def max_temp(self) -> float:
        """Return the maximum target temperature.

        Rounded inward (down) on the display unit's grid so the highest
        selectable value round-trips back within the device's native range. See
        :meth:`_inward_bound`.
        """
        value = self.get_number_max("targetTemperature")
        if value is None:
            return -1.0
        return self._inward_bound(value, is_min=False)

    @property
    def target_temperature_step(self) -> float | None:
        """Return the temperature step.

        HA's climate component converts the min/max/current/target values to
        the user's system unit for display, but it forwards
        ``target_temperature_step`` verbatim, without any unit conversion (see
        ``ClimateEntity.capability_attributes``). Since this entity always
        reports in Celsius, a Fahrenheit system would otherwise show the raw
        Celsius step (e.g. 0.5) as a 0.5 F step -- finer than the device's real
        resolution, which produces the half-degree jitter on +/-.

        So when the system unit differs from the entity unit we convert the
        step as a temperature *interval* (delta), which uses the pure scale
        ratio without the 0-degree floor offset. For Fahrenheit we additionally
        round to a whole degree (never below 1) to match HA's whole-degree
        Fahrenheit precision and the device's granularity, giving
        0.5 C -> 1 F and 1.0 C -> 2 F.
        """
        step = self.get_number_step("targetTemperature")
        if step is None:
            return None

        if self.hass is None:
            return step

        system_unit = self.hass.config.units.temperature_unit
        if system_unit == self.temperature_unit:
            return step

        delta = TemperatureDeltaConverter.convert(step, self.temperature_unit, system_unit)
        if system_unit == UnitOfTemperature.FAHRENHEIT:
            return float(max(round(delta), 1))
        return delta

    @property
    def current_temperature(self) -> float | None:
        """Return the current indoor temperature.

        The reading is surfaced regardless of power state so the card keeps
        showing the current temperature even while the unit is off (the arc is
        greyed by HA, but the value, the +/- controls and the fan mode remain
        visible). When the device is off it may stop actively refreshing
        ``indoorTemperature``; in that case the last reported value is shown.
        """
        value = self.get_value("indoorTemperature")
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):  # fmt: skip
            return None

    def _fan_mode_map(self) -> dict[str, str]:
        """Build this device's raw windSpeed code -> HA fan_mode value.

        Preference order per code:
        1. ``FAN_MODE_MAP`` — stable keys with translations + icons.
        2. The cloud enum entry's ``desc`` — a dynamic fallback so speeds the
           model reports but we haven't statically mapped are still shown
           (rendered as the raw desc text, without a custom icon).
        3. ``speed_<code>`` — last resort when the cloud provides no desc.

        The mapping is keyed by raw code and preserves the enum order, so
        ``fan_modes`` and the currently selected ``fan_mode`` stay consistent
        and reverse-mapping in :meth:`async_set_fan_mode` is unambiguous.
        """
        attr = self._device.get_attribute("windSpeed")
        if attr is None or not attr.is_enum:
            # No enum metadata: fall back to the full static map.
            return dict(self.FAN_MODE_MAP)

        mapping: dict[str, str] = {}
        for item in attr.get_enum_items():
            code = str(item.data)
            name = self.FAN_MODE_MAP.get(code)
            if name is None:
                desc = (item.desc or "").strip()
                name = desc if desc else f"speed_{code}"
            mapping[code] = name
        return mapping

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode."""
        value = self.get_value("windSpeed")
        if value is None:
            return None
        return self._fan_mode_map().get(str(value))

    @property
    def fan_modes(self) -> list[str]:
        """Return the list of available fan modes."""
        mapping = self._fan_mode_map()
        if not mapping:
            return list(self.FAN_MODE_MAP.values())

        # Preserve enum order while dropping any duplicate display values
        # (e.g. two codes sharing the same desc) to keep the picker clean.
        modes: list[str] = []
        for name in mapping.values():
            if name not in modes:
                modes.append(name)

        # Reorder to the intended strongest->weakest display order. Known
        # modes follow FAN_MODE_ORDER; anything else keeps its relative enum
        # order and is appended after the known modes. ``enumerate`` provides a
        # stable tiebreaker so unlisted modes don't get reshuffled.
        rank = {name: i for i, name in enumerate(self.FAN_MODE_ORDER)}
        tail = len(self.FAN_MODE_ORDER)
        return sorted(
            modes,
            key=lambda name, m=modes: (rank.get(name, tail + m.index(name)),),
        )

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the supported features."""
        # Power on/off is always available: hvac_modes always includes OFF and
        # async_set_hvac_mode drives it via the onOffStatus command.
        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF

        if self.is_writable("targetTemperature"):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE

        if self.is_writable("windSpeed"):
            features |= ClimateEntityFeature.FAN_MODE

        return features

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            _LOGGER.debug("Setting HVAC mode to OFF for device %s", self._device.device_id)
            self._clear_pending_mode_switch()
            await self.send_command(onOffStatus="false")
            return

        value = self._resolve_operation_mode_value(hvac_mode.value)
        if value is not None:
            _LOGGER.debug(
                "Setting HVAC mode to %s (operationMode=%s) for device %s",
                hvac_mode.value,
                value,
                self._device.device_id,
            )
            # Capture the currently displayed mode before arming the pending
            # switch so the UI holds that state until the device's returned
            # data confirms the new mode, instead of flickering through the
            # intermediate "on + stale mode" state.
            self._pre_command_hvac_mode = self.hvac_mode
            self._pending_target_mode = value
            self._arm_mode_switch_timeout()
            await self.send_command(onOffStatus="true", operationMode=value)
        else:
            _LOGGER.warning(
                "Could not resolve operation mode %s for device %s",
                hvac_mode.value,
                self._device.device_id,
            )

    def _resolve_operation_mode_value(self, mode_name: str) -> str | None:
        """Resolve a hvac_mode name to a raw operationMode value.

        MODE_NAME_MAP is currently one-to-one, but different AC models may
        use different raw codes for the same logical mode. To stay robust if
        the map ever becomes many-to-one again, prefer raw values that are
        present in this device's own operationMode enum, so we always send a
        value the device actually supports rather than a code it may reject.
        """
        attr = self._device.get_attribute("operationMode")
        if attr is not None and attr.is_enum:
            for v in attr.get_enum_values():
                if self.MODE_NAME_MAP.get(str(v)) == mode_name:
                    return str(v)
            return None

        # No enum metadata available; fall back to the static reverse map.
        reverse_map = {v: k for k, v in self.MODE_NAME_MAP.items()}
        return reverse_map.get(mode_name)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature.

        The requested value is sent on the scale the cloud published for the
        attribute; only the declared ``data_type`` (and an out-of-range
        ``fallback``, when present) affect the formatting.
        """
        temperature = kwargs.get("temperature")
        if temperature is None:
            return

        command = self.to_command_value("targetTemperature", float(temperature))

        _LOGGER.debug(
            "Setting target temperature to %s (command=%s) for device %s",
            temperature,
            command,
            self._device.device_id,
        )

        await self.send_command(targetTemperature=command)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan mode."""
        # Reverse the device's dynamic map so both statically-mapped and
        # desc-fallback modes resolve back to the correct raw windSpeed code.
        reverse_map = {v: k for k, v in self._fan_mode_map().items()}
        value = reverse_map.get(fan_mode)
        if value is not None:
            _LOGGER.debug(
                "Setting fan mode to %s (windSpeed=%s) for device %s",
                fan_mode,
                value,
                self._device.device_id,
            )
            await self.send_command(windSpeed=value)
        else:
            _LOGGER.warning(
                "Could not resolve fan mode %s for device %s",
                fan_mode,
                self._device.device_id,
            )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the pending mode-switch timer before removal."""
        self._cancel_pending_timer()
        await super().async_will_remove_from_hass()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities from a config entry."""
    _LOGGER.debug("Setting up climate platform")

    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        _LOGGER.error("No coordinator data found for entry %s", entry.entry_id)
        return

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    _LOGGER.debug("Coordinator has %d devices", len(coordinator.devices))

    entities = []
    for device in coordinator.devices.values():
        _LOGGER.debug(
            "Device: %s, type=%s, name=%s", device.device_id, device.device_type, device.device_name
        )
        if device.device_type == "AC":
            _LOGGER.debug("Creating climate entity for device %s", device.device_id)
            entities.append(
                HaierDeviceEntity.create(coordinator, device, description=None, platform="climate")
            )

    _LOGGER.debug("Adding %d climate entities", len(entities))
    async_add_entities(entities)
