"""Tests for climate entity logic."""

import pytest


class TestClimateModeMaps:
    """Test mode mapping logic."""

    def test_mode_name_map_values(self):
        """Test MODE_NAME_MAP contains expected modes."""
        from custom_components.haier_home.climate import HaierClimateEntity

        assert HaierClimateEntity.MODE_NAME_MAP == {
            "0": "auto",
            "1": "cool",
            "2": "dry",
            "4": "heat",
            "6": "fan_only",
        }

    def test_fan_mode_map_values(self):
        """Test FAN_MODE_MAP contains expected modes."""
        from custom_components.haier_home.climate import HaierClimateEntity

        assert HaierClimateEntity.FAN_MODE_MAP == {
            "1": "high",
            "2": "medium",
            "3": "low",
            "4": "quiet",
            "5": "auto",
            "6": "fast",
            "7": "mid_high",
            "8": "mid_low",
        }


class TestResolveOperationModeValue:
    """Regression tests for many-to-one MODE_NAME_MAP resolution.

    MODE_NAME_MAP maps both "4" and "5" to "heat" (different AC models use
    different raw codes for the same logical mode). A naive reverse-mapping
    of the whole table always resolves "heat" to "5" (the last entry
    written), which breaks devices whose operationMode enum only contains
    "4". _resolve_operation_mode_value must instead pick the raw value that
    the device's own operationMode enum actually supports.
    """

    def test_resolves_to_value_supported_by_device_enum(self, mock_ac_device, mock_coordinator):
        """Device enum only has "4" for heat; must not resolve to "5"."""
        from custom_components.haier_home.climate import HaierClimateEntity

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        assert entity._resolve_operation_mode_value("heat") == "4"

    def test_resolves_fan_only_to_value_supported_by_device_enum(
        self, mock_ac_device, mock_coordinator
    ):
        """Device enum only has "6" for fan_only; must not resolve to "3"."""
        from custom_components.haier_home.climate import HaierClimateEntity

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        assert entity._resolve_operation_mode_value("fan_only") == "6"

    def test_returns_none_for_unsupported_mode(self, mock_ac_device, mock_coordinator):
        """Mode not present in the device's enum resolves to None."""
        from custom_components.haier_home.climate import HaierClimateEntity

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        assert entity._resolve_operation_mode_value("nonexistent_mode") is None


class TestACDeviceAttributes:
    """Test AC device attribute behavior."""

    def test_device_type_is_ac(self, mock_ac_device):
        """Test device type mapping."""
        assert mock_ac_device.device_type == "AC"

    def test_target_temperature_default(self, mock_ac_device):
        """Test default target temperature."""
        assert mock_ac_device.get_value("targetTemperature") == "24"

    def test_operation_mode_default(self, mock_ac_device):
        """Test default operation mode (cool)."""
        assert mock_ac_device.get_value("operationMode") == "1"

    def test_wind_speed_default(self, mock_ac_device):
        """Test default wind speed (auto)."""
        assert mock_ac_device.get_value("windSpeed") == "5"

    def test_indoor_temperature_default(self, mock_ac_device):
        """Test indoor temperature."""
        assert mock_ac_device.get_value("indoorTemperature") == "25"

    def test_on_off_status_default(self, mock_ac_device):
        """Test default on/off status."""
        assert mock_ac_device.get_value("onOffStatus") == "true"

    def test_update_attribute_value(self, mock_ac_device):
        """Test attribute update."""
        mock_ac_device.attributes["targetTemperature"].update({"value": "26"})
        assert mock_ac_device.get_value("targetTemperature") == "26"

    def test_temperature_range(self, mock_ac_device):
        """Test temperature attribute range."""
        attr = mock_ac_device.get_attribute("targetTemperature")
        assert attr.is_numeric
        assert attr.value_range.data_step.min_value == "16"
        assert attr.value_range.data_step.max_value == "30"
        assert attr.value_range.data_step.step == "0.5"

    def test_operation_mode_is_enum(self, mock_ac_device):
        """Test operation mode is enum type."""
        attr = mock_ac_device.get_attribute("operationMode")
        assert attr.is_enum
        assert "0" in attr.get_enum_values()
        assert "1" in attr.get_enum_values()

    def test_indoor_temperature_not_writable(self, mock_ac_device):
        """Test indoor temperature is read-only."""
        attr = mock_ac_device.get_attribute("indoorTemperature")
        assert attr.readable
        assert not attr.writable


class TestHaierClimateEntityProperties:
    """Test HaierClimateEntity properties."""

    def test_hvac_mode_off(self, mock_ac_device, mock_coordinator):
        """Test hvac_mode returns OFF when device is off."""
        from homeassistant.components.climate import HVACMode

        from custom_components.haier_home.climate import HaierClimateEntity

        mock_ac_device.attributes["onOffStatus"].update({"value": "false"})
        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)

        # Verify hvac_mode returns the correct OFF mode
        assert entity.hvac_mode == HVACMode.OFF

    def test_hvac_mode_cool(self, mock_ac_device, mock_coordinator):
        """Test hvac_mode returns COOL when device is in cool mode."""
        from homeassistant.components.climate import HVACMode

        from custom_components.haier_home.climate import HaierClimateEntity

        mock_ac_device.attributes["onOffStatus"].update({"value": "true"})
        mock_ac_device.attributes["operationMode"].update({"value": "1"})
        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)

        # Verify hvac_mode returns the correct COOL mode
        assert entity.hvac_mode == HVACMode.COOL

    def test_hvac_mode_heat(self, mock_ac_device, mock_coordinator):
        """Test hvac_mode returns HEAT when device is in heat mode."""
        from homeassistant.components.climate import HVACMode

        from custom_components.haier_home.climate import HaierClimateEntity

        mock_ac_device.attributes["onOffStatus"].update({"value": "true"})
        mock_ac_device.attributes["operationMode"].update({"value": "4"})
        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)

        # Verify hvac_mode returns the correct HEAT mode
        assert entity.hvac_mode == HVACMode.HEAT

    def test_hvac_modes_with_enum(self, mock_ac_device, mock_coordinator):
        """Test hvac_modes returns correct modes from enum."""
        from homeassistant.components.climate import HVACMode

        from custom_components.haier_home.climate import HaierClimateEntity

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        modes = entity.hvac_modes

        # Verify all expected modes are present
        assert HVACMode.OFF in modes
        assert HVACMode.COOL in modes
        assert HVACMode.HEAT in modes

    def test_fan_mode(self, mock_ac_device, mock_coordinator):
        """Test fan_mode returns correct value."""
        from custom_components.haier_home.climate import HaierClimateEntity

        mock_ac_device.attributes["windSpeed"].update({"value": "1"})  # high
        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)

        assert entity.fan_mode == "high"

    def test_fan_modes(self, mock_ac_device, mock_coordinator):
        """Test fan_modes returns correct modes."""
        from custom_components.haier_home.climate import HaierClimateEntity

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        modes = entity.fan_modes

        assert "high" in modes
        assert "medium" in modes
        assert "low" in modes

        # Displayed strongest -> weakest, with ``auto`` pinned to the top.
        # (Mock enum exposes codes 1/2/3/5/7/8; 4=quiet and 6=fast absent.)
        assert modes == ["auto", "high", "mid_high", "medium", "mid_low", "low"]

    def test_supported_features(self, mock_ac_device, mock_coordinator):
        """Test supported_features returns correct features."""
        from custom_components.haier_home.climate import HaierClimateEntity

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        features = entity.supported_features

        # Just verify it returns something (ClimateEntityFeature is mocked)
        assert features is not None

    def test_current_temperature_when_on(self, mock_ac_device, mock_coordinator):
        """Current temperature is reported while the unit is on."""
        from custom_components.haier_home.climate import HaierClimateEntity

        mock_ac_device.attributes["onOffStatus"].update({"value": "true"})
        mock_ac_device.attributes["indoorTemperature"].update({"value": "25"})
        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)

        assert entity.current_temperature == 25.0

    def test_current_temperature_reported_when_off(self, mock_ac_device, mock_coordinator):
        """Current temperature stays visible even while the unit is off.

        The card should keep showing the current temperature when the unit is
        off (the arc is greyed by HA, but the value remains visible), so the
        last reported indoorTemperature is surfaced regardless of power state.
        """
        from custom_components.haier_home.climate import HaierClimateEntity

        mock_ac_device.attributes["onOffStatus"].update({"value": "false"})
        mock_ac_device.attributes["indoorTemperature"].update({"value": "25"})
        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)

        assert entity.current_temperature == 25.0


class TestHaierClimateEntityCommands:
    """Test HaierClimateEntity command methods."""

    @pytest.mark.asyncio
    async def test_async_set_temperature(self, mock_ac_device, mock_coordinator):
        """Test async_set_temperature sends correct command."""
        from unittest.mock import AsyncMock

        from custom_components.haier_home.climate import HaierClimateEntity

        mock_coordinator.async_send_command = AsyncMock()

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        await entity.async_set_temperature(temperature=26)

        mock_coordinator.async_send_command.assert_called_once_with(
            mock_ac_device.device_id, {"targetTemperature": "26"}
        )


class TestHaierClimatePendingModeSwitch:
    """Regression tests for the OFF -> mode switch flicker guard.

    Switching from OFF to a running mode sends onOffStatus + operationMode
    together, but the device may report onOffStatus=true before it reports the
    new operationMode. Without a guard, hvac_mode would briefly return the
    stale previous mode (e.g. COOL) before settling on the requested one. The
    entity must instead keep reporting the pre-command state until the
    device's returned data confirms the requested mode.
    """

    @pytest.mark.asyncio
    async def test_holds_off_state_until_mode_confirmed(self, mock_ac_device, mock_coordinator):
        """OFF -> HEAT must not flicker through the stale COOL mode."""
        from unittest.mock import AsyncMock

        from homeassistant.components.climate import HVACMode

        from custom_components.haier_home.climate import HaierClimateEntity

        # Device is off, but still holds a stale operationMode of "1" (cool).
        mock_ac_device.attributes["onOffStatus"].update({"value": "false"})
        mock_ac_device.attributes["operationMode"].update({"value": "1"})
        mock_coordinator.async_send_command = AsyncMock()

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        assert entity.hvac_mode == HVACMode.OFF

        await entity.async_set_hvac_mode(HVACMode.HEAT)
        mock_coordinator.async_send_command.assert_called_once_with(
            mock_ac_device.device_id, {"onOffStatus": "true", "operationMode": "4"}
        )

        # Intermediate report: powered on, but operationMode still stale.
        mock_ac_device.attributes["onOffStatus"].update({"value": "true"})
        assert entity.hvac_mode == HVACMode.OFF  # pre-command state held

        # Confirmation report: operationMode now reflects the requested mode.
        mock_ac_device.attributes["operationMode"].update({"value": "4"})
        assert entity.hvac_mode == HVACMode.HEAT
        # Pending state is cleared once confirmed.
        assert entity._pending_target_mode is None

    @pytest.mark.asyncio
    async def test_holds_previous_mode_until_new_mode_confirmed(
        self, mock_ac_device, mock_coordinator
    ):
        """COOL -> HEAT holds COOL until the device confirms HEAT."""
        from unittest.mock import AsyncMock

        from homeassistant.components.climate import HVACMode

        from custom_components.haier_home.climate import HaierClimateEntity

        mock_ac_device.attributes["onOffStatus"].update({"value": "true"})
        mock_ac_device.attributes["operationMode"].update({"value": "1"})  # cool
        mock_coordinator.async_send_command = AsyncMock()

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        assert entity.hvac_mode == HVACMode.COOL

        await entity.async_set_hvac_mode(HVACMode.HEAT)
        # Before confirmation the previously displayed mode is held.
        assert entity.hvac_mode == HVACMode.COOL

        mock_ac_device.attributes["operationMode"].update({"value": "4"})
        assert entity.hvac_mode == HVACMode.HEAT

    @pytest.mark.asyncio
    async def test_turning_off_clears_pending_switch(self, mock_ac_device, mock_coordinator):
        """Setting OFF while a switch is pending clears the pending state."""
        from unittest.mock import AsyncMock

        from homeassistant.components.climate import HVACMode

        from custom_components.haier_home.climate import HaierClimateEntity

        mock_ac_device.attributes["onOffStatus"].update({"value": "false"})
        mock_coordinator.async_send_command = AsyncMock()

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        assert entity._pending_target_mode == "4"

        await entity.async_set_hvac_mode(HVACMode.OFF)
        assert entity._pending_target_mode is None
        mock_coordinator.async_send_command.assert_called_with(
            mock_ac_device.device_id, {"onOffStatus": "false"}
        )


class TestTargetTemperatureStepUnitConversion:
    """target_temperature_step must be converted to the system unit.

    HA's climate component converts min/max/current/target values to the
    user's system unit but forwards ``target_temperature_step`` verbatim.
    Since this entity always reports in Celsius, a Fahrenheit system would
    otherwise show the raw Celsius step (0.5) as a 0.5 F step -- finer than
    the device's real resolution. The step is therefore converted as a
    temperature interval and rounded to a whole Fahrenheit degree:
    0.5 C -> 1 F, 1.0 C -> 2 F.
    """

    def _entity_with_system_unit(self, mock_ac_device, mock_coordinator, unit):
        from types import SimpleNamespace

        from custom_components.haier_home.climate import HaierClimateEntity

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        entity.hass = SimpleNamespace(
            config=SimpleNamespace(units=SimpleNamespace(temperature_unit=unit))
        )
        return entity

    def test_step_unchanged_in_celsius_system(self, mock_ac_device, mock_coordinator):
        """Same unit as the entity: step is returned as-is."""
        from homeassistant.const import UnitOfTemperature

        entity = self._entity_with_system_unit(
            mock_ac_device, mock_coordinator, UnitOfTemperature.CELSIUS
        )
        assert entity.target_temperature_step == 0.5

    def test_half_degree_celsius_maps_to_one_fahrenheit(self, mock_ac_device, mock_coordinator):
        """A 0.5 C step is shown as a whole 1 F step in a Fahrenheit system."""
        from homeassistant.const import UnitOfTemperature

        entity = self._entity_with_system_unit(
            mock_ac_device, mock_coordinator, UnitOfTemperature.FAHRENHEIT
        )
        assert entity.target_temperature_step == 1.0

    def test_one_degree_celsius_maps_to_two_fahrenheit(self, mock_ac_device, mock_coordinator):
        """A 1.0 C step is shown as a whole 2 F step in a Fahrenheit system."""
        from homeassistant.const import UnitOfTemperature

        mock_ac_device.attributes["targetTemperature"].value_range.data_step.step = "1"
        entity = self._entity_with_system_unit(
            mock_ac_device, mock_coordinator, UnitOfTemperature.FAHRENHEIT
        )
        assert entity.target_temperature_step == 2.0

    def test_step_without_hass_returns_raw(self, mock_ac_device, mock_coordinator):
        """Before the entity is added to hass, the raw Celsius step is used."""
        from custom_components.haier_home.climate import HaierClimateEntity

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        assert entity.target_temperature_step == 0.5


class TestTargetTemperatureBoundInwardRounding:
    """min_temp/max_temp must round inward on the display unit's grid.

    HA rounds the displayed bounds to whole Fahrenheit with symmetric
    round(), so a native 23.0 C minimum shows as 73 F (73.4 -> round -> 73)
    but 73 F converts back to 22.78 C -- below the true minimum -- and HA
    rejects the setpoint before the entity runs. Rounding the min up (ceil)
    and the max down (floor) on the Fahrenheit grid, then converting back to
    Celsius, keeps every displayed/selectable value round-trip valid.
    """

    def _entity_with_bounds(self, mock_ac_device, mock_coordinator, unit):
        from types import SimpleNamespace

        from custom_components.haier_home.climate import HaierClimateEntity

        # Match the real device from the screenshot: 23.0 - 29.0 C.
        step = mock_ac_device.attributes["targetTemperature"].value_range.data_step
        step.min_value = "23.0"
        step.max_value = "29.0"

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        entity.hass = SimpleNamespace(
            config=SimpleNamespace(units=SimpleNamespace(temperature_unit=unit))
        )
        return entity

    def test_bounds_unchanged_in_celsius_system(self, mock_ac_device, mock_coordinator):
        """Same unit as the entity: native bounds are returned as-is."""
        from homeassistant.const import UnitOfTemperature

        entity = self._entity_with_bounds(
            mock_ac_device, mock_coordinator, UnitOfTemperature.CELSIUS
        )
        assert entity.min_temp == 23.0
        assert entity.max_temp == 29.0

    def test_min_rounds_up_in_fahrenheit_system(self, mock_ac_device, mock_coordinator):
        """23 C (73.4 F) -> ceil 74 F -> 23.33 C, so 74 F is selectable."""
        from homeassistant.const import UnitOfTemperature
        from homeassistant.util.unit_conversion import TemperatureConverter

        entity = self._entity_with_bounds(
            mock_ac_device, mock_coordinator, UnitOfTemperature.FAHRENHEIT
        )
        # Returned bound is native Celsius equivalent of 74 F.
        assert entity.min_temp == pytest.approx(
            TemperatureConverter.convert(
                74, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS
            )
        )
        # HA converts that Celsius back to Fahrenheit for display -> 74.
        assert (
            round(
                TemperatureConverter.convert(
                    entity.min_temp, UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT
                )
            )
            == 74
        )
        # And it never drops below the true native minimum.
        assert entity.min_temp >= 23.0

    def test_max_rounds_down_in_fahrenheit_system(self, mock_ac_device, mock_coordinator):
        """29 C (84.2 F) -> floor 84 F -> 28.89 C, so 84 F is selectable."""
        from homeassistant.const import UnitOfTemperature
        from homeassistant.util.unit_conversion import TemperatureConverter

        entity = self._entity_with_bounds(
            mock_ac_device, mock_coordinator, UnitOfTemperature.FAHRENHEIT
        )
        assert entity.max_temp == pytest.approx(
            TemperatureConverter.convert(
                84, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS
            )
        )
        assert (
            round(
                TemperatureConverter.convert(
                    entity.max_temp, UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT
                )
            )
            == 84
        )
        # And it never exceeds the true native maximum.
        assert entity.max_temp <= 29.0

    def test_bounds_without_hass_return_native(self, mock_ac_device, mock_coordinator):
        """Before the entity is added to hass, native Celsius bounds are used."""
        from custom_components.haier_home.climate import HaierClimateEntity

        step = mock_ac_device.attributes["targetTemperature"].value_range.data_step
        step.min_value = "23.0"
        step.max_value = "29.0"

        entity = HaierClimateEntity(mock_coordinator, mock_ac_device)
        assert entity.min_temp == 23.0
        assert entity.max_temp == 29.0
