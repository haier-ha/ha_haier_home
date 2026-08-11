"""Base entity module for the Haier Home integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Values that a boolean-style device attribute may report as "on". Haier
# models express booleans either as "0"/"1" (LIST) or "false"/"true"; the
# native bool True is accepted for safety when values are pre-parsed.
_BOOL_TRUE_VALUES: frozenset = frozenset({"1", "true", "on", True})

if TYPE_CHECKING:
    from collections.abc import Callable

    from .device import Attribute, DataListItem, DataStep


class HaierDeviceEntity(Entity):
    """Base entity class for all Haier Home device entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    # Class-level registries for entity resolution
    _specific_registry: ClassVar[dict[tuple[str, str], type[HaierDeviceEntity]]] = {}
    _generic_registry: ClassVar[dict[tuple[str, str], type[HaierDeviceEntity]]] = {}
    _platform_registry: ClassVar[dict[str, type[HaierDeviceEntity]]] = {}

    # ------------------------------------------------------------------
    # Task 2.2: register(pid, platform) classmethod decorator
    # ------------------------------------------------------------------

    @classmethod
    def register(
        cls, pid: str | list[str], platform: str
    ) -> Callable[[type[HaierDeviceEntity]], type[HaierDeviceEntity]]:
        """Register an entity class for specific pid(s) and platform.

        If pid is a single string, registers in _specific_registry.
        If pid is a list, registers each pid in _generic_registry.
        """

        def decorator(entity_cls: type[HaierDeviceEntity]) -> type[HaierDeviceEntity]:
            if isinstance(pid, list):
                for p in pid:
                    cls._generic_registry[(p, platform)] = entity_cls
            else:
                cls._specific_registry[(pid, platform)] = entity_cls
            return entity_cls

        return decorator

    # ------------------------------------------------------------------
    # Task 2.3: register_platform(platform) classmethod decorator
    # ------------------------------------------------------------------

    @classmethod
    def register_platform(
        cls, platform: str
    ) -> Callable[[type[HaierDeviceEntity]], type[HaierDeviceEntity]]:
        """Register an entity class as a fallback for an entire platform."""

        def decorator(entity_cls: type[HaierDeviceEntity]) -> type[HaierDeviceEntity]:
            cls._platform_registry[platform] = entity_cls
            return entity_cls

        return decorator

    # ------------------------------------------------------------------
    # Task 2.4: create() classmethod with lookup priority
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        coordinator: Any,
        device: Any,
        description: Any,
        platform: str,
    ) -> HaierDeviceEntity:
        """Create an entity instance using registry lookup priority.

        Lookup order:
        1. _specific_registry[(device.pid, platform)]
        2. _generic_registry[(device.pid, platform)]
        3. _platform_registry[platform]
        4. HaierDeviceEntity itself
        """
        key = (device.pid, platform)
        entity_cls = (
            cls._specific_registry.get(key)
            or cls._generic_registry.get(key)
            or cls._platform_registry.get(platform)
            or cls
        )
        return entity_cls(coordinator, device, description)

    # ------------------------------------------------------------------
    # Task 2.5: __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        coordinator: Any,
        device: Any,
        description: Any = None,
    ) -> None:
        """Initialize the HaierDeviceEntity.

        Args:
            coordinator: The coordinator instance.
            device: The HaierDevice instance.
            description: Optional entity description (e.g. EntityDescription).
        """
        super().__init__()
        self._coordinator = coordinator
        self._device = device
        # Only set when provided; assigning None breaks HA's entity.name
        # resolution (it checks hasattr(entity_description) then accesses
        # entity_description.device_class).
        if description is not None:
            self.entity_description = description

        # Determine the key portion of unique_id
        if description is not None and hasattr(description, "key"):
            key = description.key
        else:
            key = "device"

        self._attr_unique_id = f"haier_home_{coordinator.region}_{device.device_id}_{key}"

        # Note: the device's area is provided via DeviceInfo.suggested_area in
        # the device_info property (HA derives area from the device, not the
        # entity). See build_suggested_area() for how it is composed.

        self._unsub_listener: Callable | None = None
        # Unsubscribe handle for core config (unit system, etc.) updates.
        self._unsub_config: Callable | None = None

    # ------------------------------------------------------------------
    # Task 2.6: available property
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Return True if the device is online and coordinator is connected."""
        return self._device.online and self._coordinator.connected

    # ------------------------------------------------------------------
    # Task 2.6: device_info property
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.device_id)},
            name=self._device.device_name,
            manufacturer="Haier",
            model=self._device.pid,
            suggested_area=self._device.suggested_area,
        )

    # ------------------------------------------------------------------
    # Task 2.7: get_value(name)
    # ------------------------------------------------------------------

    def get_value(self, name: str) -> Any:
        """Get the current value of a device attribute by name."""
        return self._device.get_value(name)

    # ------------------------------------------------------------------
    # Shared valueRange helpers (usable by climate / number / select /
    # switch / binary_sensor). These centralize the read/write conversions
    # that every platform would otherwise re-implement against the digital
    # model (device.Attribute / ValueRange).
    #
    # Deliberately NOT placed here (see design notes): semantic maps such as
    # climate's MODE_NAME_MAP / FAN_MODE_MAP and the HVACAction mapping. Those
    # encode HVAC-domain meaning that other platforms do not share and that
    # varies per-PID (a Level 3 override point), so they belong on the climate
    # platform/extension classes, not the integration-wide base.
    # ------------------------------------------------------------------

    def get_attribute(self, name: str) -> Attribute | None:
        """Return the full :class:`Attribute` (capability model + value)."""
        return self._device.get_attribute(name)

    def _get_data_step(self, name: str) -> DataStep | None:
        """Return the STEP range (``data_step``) for ``name`` if numeric."""
        attr = self._device.get_attribute(name)
        if attr is None or attr.value_range is None or not attr.is_numeric:
            return None
        return attr.value_range.data_step

    def get_number_value(self, name: str) -> float | None:
        """Read a numeric attribute as a number.

        The cloud reports the value on the same scale as the attribute's
        ``minValue``/``maxValue``/``step``, so it is returned as-is; any
        declared ``transform`` is deliberately not applied (see
        :class:`~..device.Transform`).

        Returns ``None`` when the attribute is missing, not coercible to a
        number, or reported outside its own declared bounds. The last case
        covers sentinel values the cloud uses for "not applicable right now"
        (e.g. a ``0`` setpoint under a 16-30 range): surfacing them as real
        readings would show a bogus value in the UI.
        """
        value = self.get_value(name)
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (ValueError, TypeError):  # fmt: skip
            return None
        step = self._get_data_step(name)
        if step is not None and step.out_of_range(number):
            _LOGGER.debug(
                "Ignoring out-of-range value for %s on device %s: %s not in [%s, %s]",
                name,
                self._device.device_id,
                value,
                step.min_value,
                step.max_value,
            )
            return None
        return number

    def get_number_min(self, name: str) -> float | None:
        """Return the lower bound from ``valueRange.dataStep``."""
        step = self._get_data_step(name)
        if step is None or step.min_value is None:
            return None
        try:
            return float(step.min_value)
        except (ValueError, TypeError):  # fmt: skip
            return None

    def get_number_max(self, name: str) -> float | None:
        """Return the upper bound from ``valueRange.dataStep``."""
        step = self._get_data_step(name)
        if step is None or step.max_value is None:
            return None
        try:
            return float(step.max_value)
        except (ValueError, TypeError):  # fmt: skip
            return None

    def get_number_step(self, name: str) -> float | None:
        """Return the step from ``valueRange.dataStep``."""
        step = self._get_data_step(name)
        if step is None or step.step is None:
            return None
        try:
            return float(step.step)
        except (ValueError, TypeError):  # fmt: skip
            return None

    def to_command_value(self, name: str, display_value: float) -> str:
        """Convert a UI value to the command string for ``name``.

        Honors the attribute's out-of-range ``fallback`` and ``data_type``
        when a STEP range is defined; otherwise the value is sent through
        unchanged (stringified). No linear conversion is applied.
        """
        step = self._get_data_step(name)
        if step is not None:
            return step.to_command_value(float(display_value))
        return str(display_value)

    def get_enum_options(self, name: str) -> list[str]:
        """Return the raw enum values (``data``) for a LIST attribute."""
        attr = self._device.get_attribute(name)
        if attr is None or not attr.is_enum:
            return []
        return attr.get_enum_values()

    def get_enum_items(self, name: str) -> list[DataListItem]:
        """Return full enum entries (``data``/``code``/``desc``) for ``name``."""
        attr = self._device.get_attribute(name)
        if attr is None or not attr.is_enum:
            return []
        return attr.get_enum_items()

    def get_bool_value(self, name: str) -> bool | None:
        """Read a boolean-style attribute.

        Returns ``None`` when the attribute has no value yet, otherwise
        ``True`` when the raw value is one of the recognized truthy tokens
        ("1"/"true"/"on"). Works for both "0"/"1" and "false"/"true" models.
        """
        value = self.get_value(name)
        if value is None or value == "":
            return None
        return value in _BOOL_TRUE_VALUES

    def is_writable(self, name: str) -> bool:
        """Return True when ``name`` exists and is writable."""
        attr = self._device.get_attribute(name)
        return attr is not None and attr.writable

    async def async_set_bool(self, name: str, on: bool) -> None:
        """Write a boolean-style attribute using the device's token style.

        Sends "1"/"0" when the attribute's enum uses numeric tokens, else
        "true"/"false" (the more common Haier representation and the safe
        default when no enum metadata is available).
        """
        options = set(self.get_enum_options(name))
        if options and options <= {"0", "1"}:
            await self.send_command(**{name: "1" if on else "0"})
        else:
            await self.send_command(**{name: "true" if on else "false"})

    # ------------------------------------------------------------------
    # Task 2.8: send_command(**kwargs)
    # ------------------------------------------------------------------

    async def send_command(self, **kwargs: Any) -> None:
        """Send command to device via coordinator."""
        if self._device.device_id in self._coordinator.devices:
            _LOGGER.debug(
                "Sending command to device %s: %s",
                self._device.device_id,
                kwargs,
            )
            await self._coordinator.async_send_command(self._device.device_id, kwargs)
        else:
            _LOGGER.warning("Device %s not found in coordinator devices", self._device.device_id)

    # ------------------------------------------------------------------
    # Task 2.9: async_added_to_hass / async_will_remove_from_hass
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Register state update listener when entity is added to HA."""
        await super().async_added_to_hass()
        self._unsub_listener = self._coordinator.async_add_listener(self.async_write_ha_state)

        # Re-render on core config changes (e.g. unit-system switch between
        # Celsius/Fahrenheit). HA converts native values to the user's unit
        # system at state-write time and caches the result, but does not
        # re-write entity states when the unit system changes. Without this,
        # the displayed unit would only update on the next coordinator push
        # (e.g. after the user changes a mode). Refreshing here makes the
        # switch take effect immediately.
        if self.hass is not None:
            self._unsub_config = self.hass.bus.async_listen(
                EVENT_CORE_CONFIG_UPDATE, self._handle_core_config_update
            )

    async def _handle_core_config_update(self, _event: Any) -> None:
        """Re-write state so unit-system changes are reflected immediately."""
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister state update listener when entity is removed from HA."""
        if self._unsub_listener is not None:
            self._unsub_listener()
            self._unsub_listener = None
        if self._unsub_config is not None:
            self._unsub_config()
            self._unsub_config = None
