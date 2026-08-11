"""Tests for entity.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.haier_home.device import Attribute, build_value_range
from custom_components.haier_home.entity import _BOOL_TRUE_VALUES, HaierDeviceEntity


class TestHaierDeviceEntityRegistry:
    """Test entity registry decorators."""

    def test_register_specific_pid(self):
        """Test register decorator for specific pid."""

        @HaierDeviceEntity.register("pid_001", "climate")
        class TestEntity(HaierDeviceEntity):
            pass

        assert ("pid_001", "climate") in HaierDeviceEntity._specific_registry
        assert HaierDeviceEntity._specific_registry[("pid_001", "climate")] == TestEntity

    def test_register_generic_pid(self):
        """Test register decorator for generic pid list."""

        @HaierDeviceEntity.register(["pid_001", "pid_002"], "climate")
        class TestEntity(HaierDeviceEntity):
            pass

        assert ("pid_001", "climate") in HaierDeviceEntity._generic_registry
        assert ("pid_002", "climate") in HaierDeviceEntity._generic_registry
        assert HaierDeviceEntity._generic_registry[("pid_001", "climate")] == TestEntity
        assert HaierDeviceEntity._generic_registry[("pid_002", "climate")] == TestEntity

    def test_register_platform(self):
        """Test register_platform decorator."""

        @HaierDeviceEntity.register_platform("climate")
        class TestEntity(HaierDeviceEntity):
            pass

        assert "climate" in HaierDeviceEntity._platform_registry
        assert HaierDeviceEntity._platform_registry["climate"] == TestEntity


class TestHaierDeviceEntityCreate:
    """Test create classmethod."""

    def test_create_specific_registry_match(self):
        """Test create returns specific registry entity."""

        @HaierDeviceEntity.register("pid_specific", "climate")
        class SpecificEntity(HaierDeviceEntity):
            pass

        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.pid = "pid_specific"

        entity = HaierDeviceEntity.create(mock_coordinator, mock_device, None, "climate")

        assert isinstance(entity, SpecificEntity)

    def test_create_generic_registry_match(self):
        """Test create returns generic registry entity."""

        @HaierDeviceEntity.register(["pid_generic"], "climate")
        class GenericEntity(HaierDeviceEntity):
            pass

        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.pid = "pid_generic"

        entity = HaierDeviceEntity.create(mock_coordinator, mock_device, None, "climate")

        assert isinstance(entity, GenericEntity)

    def test_create_platform_registry_match(self):
        """Test create returns platform registry entity."""

        @HaierDeviceEntity.register_platform("climate")
        class PlatformEntity(HaierDeviceEntity):
            pass

        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.pid = "pid_platform"

        entity = HaierDeviceEntity.create(mock_coordinator, mock_device, None, "climate")

        assert isinstance(entity, PlatformEntity)

    def test_create_fallback_to_base(self):
        """Test create falls back to HaierDeviceEntity."""

        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.pid = "pid_fallback"

        entity = HaierDeviceEntity.create(mock_coordinator, mock_device, None, "climate")

        assert isinstance(entity, HaierDeviceEntity)


class TestHaierDeviceEntityInit:
    """Test __init__ method."""

    def test_init_with_description(self):
        """Test initialization with description."""
        mock_coordinator = MagicMock()
        mock_coordinator.region = "living_room"
        mock_device = MagicMock()
        mock_device.device_id = "device_001"
        mock_device.device_name = "Test Device"
        mock_device.pid = "pid_001"
        mock_device.suggested_area = "Living Room"

        mock_description = MagicMock()
        mock_description.key = "test_key"

        entity = HaierDeviceEntity(mock_coordinator, mock_device, mock_description)

        assert entity._coordinator == mock_coordinator
        assert entity._device == mock_device
        assert entity.entity_description == mock_description
        assert entity._attr_unique_id == "haier_home_living_room_device_001_test_key"

    def test_init_without_description(self):
        """Test initialization without description."""
        mock_coordinator = MagicMock()
        mock_coordinator.region = "living_room"
        mock_device = MagicMock()
        mock_device.device_id = "device_001"

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity._attr_unique_id == "haier_home_living_room_device_001_device"
        assert not hasattr(entity, "entity_description")


class TestHaierDeviceEntityProperties:
    """Test properties."""

    def test_available(self):
        """Test available property."""
        mock_coordinator = MagicMock()
        mock_coordinator.connected = True
        mock_device = MagicMock()
        mock_device.online = True

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.available is True

    def test_available_offline(self):
        """Test available property when device is offline."""
        mock_coordinator = MagicMock()
        mock_coordinator.connected = True
        mock_device = MagicMock()
        mock_device.online = False

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.available is False

    def test_available_disconnected(self):
        """Test available property when coordinator is disconnected."""
        mock_coordinator = MagicMock()
        mock_coordinator.connected = False
        mock_device = MagicMock()
        mock_device.online = True

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.available is False

    def test_device_info(self):
        """Test device_info property."""
        from homeassistant.helpers.device_registry import DeviceInfo

        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.device_id = "device_001"
        mock_device.device_name = "Test Device"
        mock_device.pid = "pid_001"
        mock_device.suggested_area = "Living Room"

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.device_info == DeviceInfo(
            identifiers={("haier_home", "device_001")},
            name="Test Device",
            manufacturer="Haier",
            model="pid_001",
            suggested_area="Living Room",
        )


class TestHaierDeviceEntityValueHelpers:
    """Test value helper methods."""

    def test_get_value(self):
        """Test get_value method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.get_value = MagicMock(return_value="test_value")

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_value("test_attr") == "test_value"

    def test_get_attribute(self):
        """Test get_attribute method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_attribute = MagicMock()
        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_attribute("test_attr") == mock_attribute

    def test_get_number_value(self):
        """Test get_number_value method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.get_value = MagicMock(return_value="25")
        mock_device.get_attribute = MagicMock(return_value=None)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_number_value("test_attr") == 25.0

    def test_get_number_value_with_step(self):
        """A STEP attribute's value is returned as reported.

        Regression guard for the auto-mode payload where the cloud publishes
        ``transform {k:1, c:26}`` alongside ``value "26.0000"``: converting
        turned the setpoint into 0.
        """
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.get_value = MagicMock(return_value="26.0000")

        mock_attribute = Attribute(
            name="targetTemperature",
            writable=True,
            current_value="26.0000",
            value_range=build_value_range(
                {
                    "type": "STEP",
                    "dataStep": {
                        "dataType": "double",
                        "minValue": "23.0000",
                        "maxValue": "29.0000",
                        "step": "1.0000",
                        "transform": {"k": "1.0000", "c": "26.0000"},
                    },
                }
            ),
        )

        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_number_value("targetTemperature") == 26.0
        assert entity.get_number_min("targetTemperature") == 23.0
        assert entity.get_number_max("targetTemperature") == 29.0
        assert entity.get_number_step("targetTemperature") == 1.0
        assert entity.to_command_value("targetTemperature", 23.0) == "23"

    @staticmethod
    def _numeric_entity(value: str, **step: str):
        """Build an entity whose single attribute has a STEP range."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.get_value = MagicMock(return_value=value)
        mock_device.get_attribute = MagicMock(
            return_value=Attribute(
                name="targetTemperature",
                current_value=value,
                value_range=build_value_range({"type": "STEP", "dataStep": step}),
            )
        )
        return HaierDeviceEntity(mock_coordinator, mock_device)

    @pytest.mark.parametrize("value", ["0", "15.5", "30.5", "-1"])
    def test_get_number_value_out_of_range_is_none(self, value):
        """Values outside the declared bounds are dropped, not shown.

        The cloud uses such values as "not applicable right now" sentinels;
        ``0`` under a 16-30 range is the observed case.
        """
        entity = self._numeric_entity(value, minValue="16.0", maxValue="30.0", step="0.5")

        assert entity.get_number_value("targetTemperature") is None

    @pytest.mark.parametrize("value", ["16.0", "23.5", "30.0"])
    def test_get_number_value_within_range_is_kept(self, value):
        """Values on the bounds and in between are returned as reported."""
        entity = self._numeric_entity(value, minValue="16.0", maxValue="30.0", step="0.5")

        assert entity.get_number_value("targetTemperature") == float(value)

    def test_get_number_value_without_bounds_is_kept(self):
        """With no bounds declared there is nothing to range-check against."""
        entity = self._numeric_entity("0", step="0.5")

        assert entity.get_number_value("targetTemperature") == 0.0

    def test_get_number_value_with_unparseable_bounds_is_kept(self):
        """A malformed bound must not hide an otherwise usable value."""
        entity = self._numeric_entity("26.0", minValue="low", maxValue="high")

        assert entity.get_number_value("targetTemperature") == 26.0

    def test_get_number_value_invalid(self):
        """Test get_number_value with invalid value."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.get_value = MagicMock(return_value="not_a_number")

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_number_value("test_attr") is None

    def test_get_number_min(self):
        """Test get_number_min method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()

        mock_step = MagicMock()
        mock_step.min_value = "16"

        mock_attribute = MagicMock()
        mock_attribute.value_range = MagicMock()
        mock_attribute.value_range.data_step = mock_step
        mock_attribute.is_numeric = True

        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_number_min("test_attr") == 16.0

    def test_get_number_max(self):
        """Test get_number_max method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()

        mock_step = MagicMock()
        mock_step.max_value = "30"

        mock_attribute = MagicMock()
        mock_attribute.value_range = MagicMock()
        mock_attribute.value_range.data_step = mock_step
        mock_attribute.is_numeric = True

        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_number_max("test_attr") == 30.0

    def test_get_number_step(self):
        """Test get_number_step method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()

        mock_step = MagicMock()
        mock_step.step = "1"

        mock_attribute = MagicMock()
        mock_attribute.value_range = MagicMock()
        mock_attribute.value_range.data_step = mock_step
        mock_attribute.is_numeric = True

        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_number_step("test_attr") == 1.0

    def test_to_command_value(self):
        """Test to_command_value method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()

        mock_step = MagicMock()
        mock_step.to_command_value = MagicMock(return_value="50")

        mock_attribute = MagicMock()
        mock_attribute.value_range = MagicMock()
        mock_attribute.value_range.data_step = mock_step
        mock_attribute.is_numeric = True

        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.to_command_value("test_attr", 25.0) == "50"

    def test_get_enum_options(self):
        """Test get_enum_options method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()

        mock_attribute = MagicMock()
        mock_attribute.is_enum = True
        mock_attribute.get_enum_values = MagicMock(return_value=["option1", "option2"])

        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_enum_options("test_attr") == ["option1", "option2"]

    def test_get_enum_options_not_enum(self):
        """Test get_enum_options for non-enum attribute."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()

        mock_attribute = MagicMock()
        mock_attribute.is_enum = False

        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_enum_options("test_attr") == []

    def test_get_enum_items(self):
        """Test get_enum_items method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()

        mock_attribute = MagicMock()
        mock_attribute.is_enum = True
        mock_attribute.get_enum_items = MagicMock(return_value=[("data1", "code1", "desc1")])

        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_enum_items("test_attr") == [("data1", "code1", "desc1")]

    def test_get_bool_value(self):
        """Test get_bool_value method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.get_value = MagicMock(return_value="1")

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_bool_value("test_attr") is True

    def test_get_bool_value_false(self):
        """Test get_bool_value returns False."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.get_value = MagicMock(return_value="0")

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_bool_value("test_attr") is False

    def test_get_bool_value_none(self):
        """Test get_bool_value returns None for empty value."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.get_value = MagicMock(return_value=None)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.get_bool_value("test_attr") is None

    def test_is_writable(self):
        """Test is_writable method."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()

        mock_attribute = MagicMock()
        mock_attribute.writable = True

        mock_device.get_attribute = MagicMock(return_value=mock_attribute)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.is_writable("test_attr") is True

    def test_is_writable_not_found(self):
        """Test is_writable returns False when attribute not found."""
        mock_coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.get_attribute = MagicMock(return_value=None)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        assert entity.is_writable("test_attr") is False


class TestHaierDeviceEntitySendCommand:
    """Test send_command method."""

    @pytest.mark.asyncio
    async def test_send_command_device_found(self):
        """Test send_command when device is in coordinator."""
        mock_coordinator = MagicMock()
        mock_coordinator.devices = {"device_001"}
        mock_coordinator.async_send_command = AsyncMock()

        mock_device = MagicMock()
        mock_device.device_id = "device_001"

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        await entity.send_command(power="true", temperature="25")

        mock_coordinator.async_send_command.assert_called_once_with(
            "device_001", {"power": "true", "temperature": "25"}
        )

    @pytest.mark.asyncio
    async def test_send_command_device_not_found(self):
        """Test send_command when device is not in coordinator."""
        mock_coordinator = MagicMock()
        mock_coordinator.devices = {"device_002"}

        mock_device = MagicMock()
        mock_device.device_id = "device_001"

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        # Should not raise, just log warning
        await entity.send_command(power="true")

        mock_coordinator.async_send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_set_bool_numeric_tokens(self):
        """Test async_set_bool with numeric tokens."""
        mock_coordinator = MagicMock()
        mock_coordinator.devices = {"device_001"}
        mock_coordinator.async_send_command = AsyncMock()

        mock_device = MagicMock()
        mock_device.device_id = "device_001"
        mock_device.get_attribute = MagicMock(return_value=None)
        mock_device.get_value = MagicMock(return_value=None)

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        # Mock get_enum_options to return numeric tokens
        entity.get_enum_options = MagicMock(return_value=["0", "1"])

        await entity.async_set_bool("power", True)

        mock_coordinator.async_send_command.assert_called_once_with("device_001", {"power": "1"})

    @pytest.mark.asyncio
    async def test_async_set_bool_string_tokens(self):
        """Test async_set_bool with string tokens."""
        mock_coordinator = MagicMock()
        mock_coordinator.devices = {"device_001"}
        mock_coordinator.async_send_command = AsyncMock()

        mock_device = MagicMock()
        mock_device.device_id = "device_001"

        entity = HaierDeviceEntity(mock_coordinator, mock_device)

        # Mock get_enum_options to return string tokens
        entity.get_enum_options = MagicMock(return_value=["false", "true"])

        await entity.async_set_bool("power", True)

        mock_coordinator.async_send_command.assert_called_once_with("device_001", {"power": "true"})


class TestHaierDeviceEntityLifecycle:
    """Test lifecycle methods."""

    @pytest.mark.asyncio
    async def test_async_added_to_hass(self):
        """Test async_added_to_hass."""
        mock_coordinator = MagicMock()
        mock_coordinator.async_add_listener = MagicMock(return_value=lambda: None)

        mock_device = MagicMock()

        entity = HaierDeviceEntity(mock_coordinator, mock_device)
        entity.async_write_ha_state = MagicMock()

        await entity.async_added_to_hass()

        assert entity._unsub_listener is not None
        mock_coordinator.async_add_listener.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_will_remove_from_hass(self):
        """Test async_will_remove_from_hass."""
        mock_coordinator = MagicMock()

        mock_device = MagicMock()

        entity = HaierDeviceEntity(mock_coordinator, mock_device)
        mock_unsub = MagicMock()
        entity._unsub_listener = mock_unsub

        await entity.async_will_remove_from_hass()

        mock_unsub.assert_called_once()
        assert entity._unsub_listener is None


class TestBoolTrueValues:
    """Test _BOOL_TRUE_VALUES constant."""

    def test_bool_true_values_contains_expected_values(self):
        """Test _BOOL_TRUE_VALUES contains expected truthy values."""
        assert "1" in _BOOL_TRUE_VALUES
        assert "true" in _BOOL_TRUE_VALUES
        assert "on" in _BOOL_TRUE_VALUES
        assert True in _BOOL_TRUE_VALUES
        assert 1 in _BOOL_TRUE_VALUES

    def test_bool_true_values_not_contains_false_values(self):
        """Test _BOOL_TRUE_VALUES does not contain falsy values."""
        assert "0" not in _BOOL_TRUE_VALUES
        assert "false" not in _BOOL_TRUE_VALUES
        assert "off" not in _BOOL_TRUE_VALUES
        assert False not in _BOOL_TRUE_VALUES
        assert 0 not in _BOOL_TRUE_VALUES
