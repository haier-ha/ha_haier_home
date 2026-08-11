"""Tests for device.py - data models and parsing logic."""

from __future__ import annotations

from custom_components.haier_home.device import (
    Attribute,
    HaierDevice,
    Transform,
    build_area_name_candidates,
    build_suggested_area,
    build_value_range,
    create_device_from_api_record,
    parse_digital_model,
)


class TestTransform:
    """Test that ``transform`` is parsed but never applied.

    The coefficients below are the ones the cloud publishes for an AC's
    ``targetTemperature`` while ``operationMode=0`` (auto). Applying them
    turned the reported 26 into 0 in the UI and a requested 23 into 49, which
    the cloud rejected against its own ``maxValue`` of 29.
    """

    AUTO_MODE_STEP = {
        "type": "STEP",
        "dataStep": {
            "dataType": "double",
            "minValue": "23.0000",
            "maxValue": "29.0000",
            "step": "1.0000",
            "transform": {"k": "1.0000", "c": "26.0000"},
        },
    }

    def test_transform_is_parsed(self):
        """The coefficients stay available on the parsed model."""
        vr = build_value_range(self.AUTO_MODE_STEP)
        assert vr is not None
        assert vr.data_step is not None
        assert vr.data_step.transform == Transform(k=1.0, c=26.0)

    def test_command_value_ignores_transform(self):
        """A requested value is sent unchanged, not shifted by ``c``."""
        vr = build_value_range(self.AUTO_MODE_STEP)
        assert vr is not None
        assert vr.data_step is not None
        assert vr.data_step.to_command_value(23) == "23"
        assert vr.data_step.to_command_value(29) == "29"


class TestCommandValueQuantization:
    """Off-grid UI values are snapped to the device's min/step grid.

    Reproduces the Fahrenheit case: HA converts the user's Fahrenheit choice
    back to the entity's native Celsius scale, yielding off-grid values like
    84 F -> 28.888... C. These must be rounded to the device's 0.5 C grid
    before being sent, or the device receives an illegal setpoint.
    """

    HALF_STEP = {
        "type": "STEP",
        "dataStep": {
            "dataType": "double",
            "minValue": "16.0000",
            "maxValue": "30.0000",
            "step": "0.5000",
        },
    }

    def _step(self):
        vr = build_value_range(self.HALF_STEP)
        assert vr is not None and vr.data_step is not None
        return vr.data_step

    def test_fahrenheit_converted_values_snap_to_grid(self):
        step = self._step()
        # 84 F -> 28.888..C -> nearest 0.5 grid point 29.0
        assert step.to_command_value(28.88888888888889) == "29"
        # 83.5 F -> 28.611..C -> 28.5
        assert step.to_command_value(28.61111111111111) == "28.5"
        # 83 F -> 28.333..C -> 28.5
        assert step.to_command_value(28.333333333333332) == "28.5"

    def test_on_grid_values_unchanged(self):
        step = self._step()
        assert step.to_command_value(28.5) == "28.5"
        assert step.to_command_value(26) == "26"

    def test_out_of_range_is_clamped_without_fallback(self):
        step = self._step()
        assert step.to_command_value(35) == "30"
        assert step.to_command_value(10) == "16"

    def test_no_binary_float_noise(self):
        step = self._step()
        # Must be "28.5", never "28.500000000000004".
        assert step.to_command_value(28.5000001) == "28.5"

    def test_integer_type_rounds_to_whole(self):
        vr = build_value_range(
            {
                "type": "STEP",
                "dataStep": {
                    "dataType": "Integer",
                    "minValue": "16",
                    "maxValue": "30",
                    "step": "1",
                },
            }
        )
        assert vr is not None and vr.data_step is not None
        assert vr.data_step.to_command_value(28.888888) == "29"

    def test_fallback_still_honored_when_out_of_range(self):
        vr = build_value_range(
            {
                "type": "STEP",
                "dataStep": {
                    "dataType": "double",
                    "minValue": "16.0000",
                    "maxValue": "30.0000",
                    "step": "0.5000",
                    "fallback": "16",
                },
            }
        )
        assert vr is not None and vr.data_step is not None
        # Genuinely out of range with a configured fallback -> fallback wins.
        assert vr.data_step.to_command_value(99) == "16"
        # In-range but off-grid still snaps.
        assert vr.data_step.to_command_value(28.888888) == "29"


class TestBuildValueRange:
    """Test build_value_range function."""

    def test_build_step_range(self):
        """Test building STEP type ValueRange."""
        vr = build_value_range(
            {
                "type": "STEP",
                "dataStep": {
                    "dataType": "Double",
                    "minValue": "16",
                    "maxValue": "30",
                    "step": "0.5",
                },
            }
        )
        assert vr is not None
        assert vr.type == "STEP"
        assert vr.data_step is not None
        assert vr.data_step.min_value == "16"
        assert vr.data_step.max_value == "30"

    def test_build_list_range(self):
        """Test building LIST type ValueRange."""
        vr = build_value_range(
            {
                "type": "LIST",
                "dataList": [
                    {"data": "0", "desc": "auto"},
                    {"data": "1", "desc": "cool"},
                ],
            }
        )
        assert vr is not None
        assert vr.type == "LIST"
        assert vr.data_list is not None
        assert len(vr.data_list) == 2
        assert vr.data_list[0].data == "0"

    def test_build_time_range(self):
        """Test building TIME type ValueRange."""
        vr = build_value_range(
            {
                "type": "TIME",
                "dataTime": {"format": "HH:mm", "minHour": 0, "maxHour": 23},
            }
        )
        assert vr is not None
        assert vr.type == "TIME"

    def test_build_date_range(self):
        """Test building DATE type ValueRange."""
        vr = build_value_range(
            {
                "type": "DATE",
                "dataDate": {"format": "yyyyMMdd"},
            }
        )
        assert vr is not None
        assert vr.type == "DATE"

    def test_build_none_range(self):
        """Test building NONE type ValueRange."""
        vr = build_value_range({"type": "NONE"})
        assert vr is not None
        assert vr.type == "NONE"

    def test_build_invalid_type(self):
        """Test building unknown type returns None."""
        vr = build_value_range({"type": "UNKNOWN"})
        assert vr is None

    def test_build_null_input(self):
        """Test building with None returns None."""
        vr = build_value_range(None)
        assert vr is None


class TestParseDigitalModel:
    """Test parse_digital_model function."""

    def test_parse_digital_model_with_list(self):
        """Test parsing digital model from list format."""
        digital_model = [
            {
                "name": "onOffStatus",
                "desc": "开关",
                "readable": True,
                "writable": True,
                "value": "true",
                "valueRange": {
                    "type": "LIST",
                    "dataList": [
                        {"data": "false"},
                        {"data": "true"},
                    ],
                },
            }
        ]
        attrs = parse_digital_model(digital_model)
        assert "onOffStatus" in attrs
        assert attrs["onOffStatus"].current_value == "true"
        assert attrs["onOffStatus"].is_bool is True

    def test_parse_digital_model_with_attributes_key(self):
        """Test parsing digital model with attributes key."""
        digital_model = {
            "attributes": [
                {
                    "name": "targetTemperature",
                    "desc": "目标温度",
                    "readable": True,
                    "writable": True,
                    "value": "24",
                    "valueRange": {
                        "type": "STEP",
                        "dataStep": {"minValue": "16", "maxValue": "30"},
                    },
                }
            ]
        }
        attrs = parse_digital_model(digital_model)
        assert "targetTemperature" in attrs
        assert attrs["targetTemperature"].is_numeric is True

    def test_parse_digital_model_with_data_attributes(self):
        """Test parsing digital model with data.attributes key."""
        digital_model = {
            "data": {
                "attributes": [
                    {
                        "name": "operationMode",
                        "value": "1",
                    }
                ]
            }
        }
        attrs = parse_digital_model(digital_model)
        assert "operationMode" in attrs

    def test_parse_digital_model_empty(self):
        """Test parsing empty digital model."""
        attrs = parse_digital_model({})
        assert attrs == {}


class TestBuildSuggestedArea:
    """Test build_suggested_area function."""

    def test_family_and_room_mode(self):
        """Test family_and_room mode."""
        record = {
            "devFloorName": "一层",
            "roomName": "卧室",
        }
        area = build_suggested_area(record, family_name="我的家", room_sync_mode="family_and_room")
        assert area == "我的家 一层 卧室"

    def test_room_only_mode(self):
        """Test room_only mode."""
        record = {
            "devFloorName": "一层",
            "roomName": "卧室",
        }
        area = build_suggested_area(record, family_name="我的家", room_sync_mode="room_only")
        assert area == "一层 卧室"

    def test_family_only_mode(self):
        """Test family_only mode."""
        record = {}
        area = build_suggested_area(record, family_name="我的家", room_sync_mode="family_only")
        assert area == "我的家"

    def test_none_mode(self):
        """Test none mode returns None."""
        record = {}
        area = build_suggested_area(record, family_name="我的家", room_sync_mode="none")
        assert area is None

    def test_snake_case_fields(self):
        """Test snake_case field names."""
        record = {
            "dev_floor_name": "一层",
            "room_name": "卧室",
        }
        area = build_suggested_area(record, family_name="我的家", room_sync_mode="family_and_room")
        assert area == "我的家 一层 卧室"


class TestBuildAreaNameCandidates:
    """Test build_area_name_candidates function.

    These candidates are what lets the reload-time area reconciliation
    recognize an integration-managed area regardless of which mode originally
    produced it, so a mode change actually moves the device.
    """

    RECORD = {"devFloorName": "一层", "roomName": "客厅"}

    def test_includes_all_mode_variants(self):
        """All non-none modes contribute their generated name."""
        candidates = build_area_name_candidates(self.RECORD, family_name="接口01")
        assert candidates == ["接口01 一层 客厅", "一层 客厅", "接口01"]

    def test_room_only_scenario_still_lists_family_variant(self):
        """A family name is enough to list the family_and_room candidate.

        This is the exact regression: a device now in room_only mode must still
        recognize the "<family> <floor> <room>" area it was placed under before,
        which requires the family name to be available even in room_only.
        """
        candidates = build_area_name_candidates(self.RECORD, family_name="接口01")
        assert "接口01 一层 客厅" in candidates
        assert "一层 客厅" in candidates

    def test_no_family_name_drops_family_variants(self):
        """Without a family name only the room-only candidate is produced."""
        candidates = build_area_name_candidates(self.RECORD, family_name=None)
        assert candidates == ["一层 客厅"]

    def test_deduplicated_and_no_empty_entries(self):
        """Empty component records yield no candidates (no blank names)."""
        candidates = build_area_name_candidates({}, family_name=None)
        assert candidates == []

    def test_populated_on_created_device(self):
        """create_device_from_api_record wires candidates onto the device."""
        record = {
            "deviceId": "device_001",
            "apptypeCode": "A177",
            "pid": "test_pid",
            "devName": "客厅空调",
            "devFloorName": "一层",
            "roomName": "客厅",
            "familyId": "family_001",
        }
        device = create_device_from_api_record(
            record, room_sync_mode="room_only", family_name="接口01"
        )
        assert device is not None
        # Active mode is room_only, so that is the written area...
        assert device.suggested_area == "一层 客厅"
        # ...but the family_and_room variant is still recognized as managed.
        assert "接口01 一层 客厅" in device.managed_area_names
        assert "一层 客厅" in device.managed_area_names


class TestCreateDeviceFromApiRecord:
    """Test create_device_from_api_record function."""

    def test_create_ac_device(self):
        """Test creating AC device from API record."""
        record = {
            "deviceId": "device_001",
            "apptypeCode": "A177",
            "pid": "test_pid",
            "devName": "客厅空调",
            "familyId": "family_001",
            "online": True,
        }
        device = create_device_from_api_record(record)
        assert device is not None
        assert device.device_id == "device_001"
        assert device.device_type == "AC"
        assert device.device_name == "客厅空调"
        assert device.online is True

    def test_create_non_ac_device_returns_none(self):
        """Test creating non-AC device returns None."""
        record = {
            "deviceId": "device_001",
            "apptypeCode": "UNKNOWN",
            "pid": "test_pid",
        }
        device = create_device_from_api_record(record)
        assert device is None

    def test_create_device_without_device_id_returns_none(self):
        """Test creating device without device_id returns None."""
        record = {
            "apptypeCode": "A177",
            "pid": "test_pid",
        }
        device = create_device_from_api_record(record)
        assert device is None

    def test_create_device_with_snake_case_fields(self):
        """Test creating device with snake_case fields."""
        record = {
            "device_id": "device_001",
            "app_type_code": "A177",
            "pid": "test_pid",
            "device_name": "客厅空调",
            "online": False,
        }
        device = create_device_from_api_record(record)
        assert device is not None
        assert device.device_id == "device_001"
        assert device.device_name == "客厅空调"
        assert device.online is False


class TestHaierDevice:
    """Test HaierDevice class."""

    def test_device_type_property(self):
        """Test device_type property."""
        device = HaierDevice(
            device_id="device_001",
            pid="test_pid",
            app_type_code="A177",
            attributes={},
        )
        assert device.device_type == "AC"

    def test_get_value(self):
        """Test get_value method."""
        attr = Attribute(
            name="targetTemperature",
            desc="目标温度",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="24",
            invisible=False,
            value_range=None,
        )
        device = HaierDevice(
            device_id="device_001",
            pid="test_pid",
            app_type_code="A177",
            attributes={"targetTemperature": attr},
        )
        assert device.get_value("targetTemperature") == "24"
        assert device.get_value("nonExistent") is None

    def test_set_online(self):
        """Test set_online method."""
        device = HaierDevice(
            device_id="device_001",
            pid="test_pid",
            app_type_code="A177",
            attributes={},
        )
        assert device.online is True
        device.set_online(False)
        assert device.online is False

    def test_async_on_message(self):
        """Test async_on_message method."""
        attr = Attribute(
            name="targetTemperature",
            desc="目标温度",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="24",
            invisible=False,
            value_range=None,
        )
        device = HaierDevice(
            device_id="device_001",
            pid="test_pid",
            app_type_code="A177",
            attributes={"targetTemperature": attr},
        )
        device.async_on_message({"data": [{"name": "targetTemperature", "value": "26"}]})
        assert device.get_value("targetTemperature") == "26"


class TestAttribute:
    """Test Attribute class."""

    def test_is_numeric(self):
        """Test is_numeric property."""
        from custom_components.haier_home.device import DataStep, ValueRange

        attr = Attribute(
            name="temp",
            desc="温度",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="24",
            invisible=False,
            value_range=ValueRange(type="STEP", data_step=DataStep()),
        )
        assert attr.is_numeric is True
        assert attr.is_enum is False
        assert attr.is_bool is False

    def test_is_enum(self):
        """Test is_enum property."""
        from custom_components.haier_home.device import DataListItem, ValueRange

        attr = Attribute(
            name="mode",
            desc="模式",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="0",
            invisible=False,
            value_range=ValueRange(
                type="LIST",
                data_list=[
                    DataListItem(data="0"),
                    DataListItem(data="1"),
                    DataListItem(data="2"),
                ],
            ),
        )
        assert attr.is_enum is True
        assert attr.is_bool is False

    def test_is_bool(self):
        """Test is_bool property."""
        from custom_components.haier_home.device import DataListItem, ValueRange

        attr = Attribute(
            name="onOff",
            desc="开关",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="false",
            invisible=False,
            value_range=ValueRange(
                type="LIST",
                data_list=[
                    DataListItem(data="false"),
                    DataListItem(data="true"),
                ],
            ),
        )
        assert attr.is_bool is True
        assert attr.is_enum is True  # bool is a special case of enum

    def test_get_enum_values(self):
        """Test get_enum_values method."""
        from custom_components.haier_home.device import DataListItem, ValueRange

        attr = Attribute(
            name="mode",
            desc="模式",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="0",
            invisible=False,
            value_range=ValueRange(
                type="LIST",
                data_list=[
                    DataListItem(data="0"),
                    DataListItem(data="1"),
                ],
            ),
        )
        assert attr.get_enum_values() == ["0", "1"]

    def test_update(self):
        """Test update method."""
        attr = Attribute(
            name="temp",
            desc="温度",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="24",
            invisible=False,
            value_range=None,
        )
        attr.update({"value": "26", "writable": False})
        assert attr.current_value == "26"
        assert attr.writable is False
