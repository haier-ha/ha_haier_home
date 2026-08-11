"""Mock data module for independent development testing.

Provides complete implementations of Attribute, ValueRange, UhomeDevice,
MockCoordinator, and MockClient to allow platform layer development
before Developer A's modules are delivered.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from custom_components.haier_home.const import DEVICE_TYPE_MAP

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task 1.2: ValueRange dataclass
# ---------------------------------------------------------------------------


@dataclass
class Transform:
    """The raw ``dataStep.transform`` coefficients, never applied.

    Mirrors device.Transform: parsed for visibility only, because reported
    values, the declared bounds and command values all share one scale.
    """

    k: float
    c: float


@dataclass
class DataListItem:
    """A single ``LIST`` entry: ``data`` value plus optional ``code``/``desc``."""

    data: str
    code: str | None = None
    desc: str | None = None


@dataclass
class DataStep:
    """A ``STEP`` range (cloud ``dataStep``). Mirrors device.DataStep."""

    data_type: str | None = None  # "Integer" | "Double"
    step: str | None = None
    min_value: str | None = None
    max_value: str | None = None
    transform: Transform | None = None
    fallback: str | None = None

    def to_command_value(self, display_value: float) -> str:
        """Convert a UI value into the command string to send.

        No linear conversion is applied; ``transform`` is ignored.
        """
        if self.fallback is not None and self.out_of_range(display_value):
            return self.fallback
        return self._coerce(display_value)

    def _coerce(self, value: float) -> str:
        """Format ``value`` as a command string honoring ``data_type``."""
        if self.data_type == "Integer":
            return str(int(round(value)))
        if float(value).is_integer():
            return str(int(value))
        return str(value)

    def out_of_range(self, value: float) -> bool:
        """Return True if ``value`` is outside the declared bounds."""
        try:
            if self.min_value is not None and value < float(self.min_value):
                return True
            if self.max_value is not None and value > float(self.max_value):
                return True
        except (ValueError, TypeError):  # fmt: skip
            return False
        return False


@dataclass
class DataTime:
    """A ``TIME`` range (cloud ``dataTime``). Mirrors device.DataTime."""

    format: str | None = None
    min_hour: int | None = None
    max_hour: int | None = None
    min_minute: int | None = None
    max_minute: int | None = None
    min_second: int | None = None
    max_second: int | None = None


@dataclass
class DataDate:
    """A ``DATE`` range (cloud ``dataDate``). Mirrors device.DataDate."""

    format: str | None = None
    begin_date: str | None = None
    end_date: str | None = None


@dataclass
class ValueRange:
    """Represents the valid range of an attribute value.

    Mirrors the cloud ``valueRange`` object (see device.ValueRange). Exactly
    one sub-object is populated depending on ``type`` ("NONE"/"LIST"/"STEP"/
    "TIME"/"DATE").
    """

    type: str  # "NONE" | "LIST" | "STEP" | "TIME" | "DATE"
    data_list: list[DataListItem] | None = None
    data_step: DataStep | None = None
    data_time: DataTime | None = None
    data_date: DataDate | None = None


def _build_transform(step_data: dict) -> Transform | None:
    """Build a Transform from a ``dataStep.transform`` object, or None."""
    transform_data = step_data.get("transform")
    if not isinstance(transform_data, dict):
        return None
    try:
        k = float(transform_data["k"])
        c = float(transform_data["c"])
    except (KeyError, ValueError, TypeError):  # fmt: skip
        return None
    if k == 0:
        return None
    return Transform(k=k, c=c)


def _build_data_list(raw_list: list | None) -> list[DataListItem]:
    """Build DataListItem entries from a raw ``dataList`` array."""
    items: list[DataListItem] = []
    for item in raw_list or []:
        if isinstance(item, dict):
            items.append(
                DataListItem(
                    data=item.get("data", ""),
                    code=item.get("code"),
                    desc=item.get("desc"),
                )
            )
    return items


def _build_data_step(vr: dict) -> DataStep:
    """Build a DataStep from a ``valueRange`` payload (dataStep nested)."""
    step_data = vr.get("dataStep") or {}
    return DataStep(
        data_type=step_data.get("dataType"),
        step=step_data.get("step", vr.get("step")),
        min_value=step_data.get("minValue", vr.get("minValue")),
        max_value=step_data.get("maxValue", vr.get("maxValue")),
        transform=_build_transform(step_data),
        fallback=step_data.get("fallback", vr.get("fallback")),
    )


def _build_data_time(raw: dict | None) -> DataTime:
    """Build a DataTime from a raw ``dataTime`` object."""
    raw = raw or {}
    return DataTime(
        format=raw.get("format"),
        min_hour=raw.get("minHour"),
        max_hour=raw.get("maxHour"),
        min_minute=raw.get("minMinute"),
        max_minute=raw.get("maxMinute"),
        min_second=raw.get("minSecond"),
        max_second=raw.get("maxSecond"),
    )


def _build_data_date(raw: dict | None) -> DataDate:
    """Build a DataDate from a raw ``dataDate`` object."""
    raw = raw or {}
    return DataDate(
        format=raw.get("format"),
        begin_date=raw.get("beginDate"),
        end_date=raw.get("endDate"),
    )


def _build_value_range(vr: dict | None) -> ValueRange | None:
    """Parse a raw ``valueRange`` payload into a ValueRange.

    Mirrors device.build_value_range so mock data behaves like production.
    """
    if not vr:
        return None

    vr_type = vr.get("type", "")
    if vr_type == "STEP":
        return ValueRange(type="STEP", data_step=_build_data_step(vr))
    if vr_type == "LIST":
        return ValueRange(type="LIST", data_list=_build_data_list(vr.get("dataList")))
    if vr_type == "TIME":
        return ValueRange(type="TIME", data_time=_build_data_time(vr.get("dataTime")))
    if vr_type == "DATE":
        return ValueRange(type="DATE", data_date=_build_data_date(vr.get("dataDate")))
    if vr_type == "NONE":
        return ValueRange(type="NONE")
    return None


# ---------------------------------------------------------------------------
# Task 1.3: Attribute dataclass
# ---------------------------------------------------------------------------


@dataclass
class Attribute:
    """Represents a single device attribute with value and metadata."""

    name: str
    desc: str
    readable: bool
    writable: bool
    operation_type: str | None
    default_value: str
    invisible: bool
    value_range: ValueRange | None

    _current_value: Any = field(init=False, default=None, repr=False)

    @property
    def current_value(self) -> Any:
        """Return current value, falling back to default_value."""
        if self._current_value is not None:
            return self._current_value
        return self.default_value

    @property
    def is_bool(self) -> bool:
        """True if LIST type with exactly 2 values: true/false or 0/1."""
        if self.value_range is None or self.value_range.type != "LIST":
            return False
        data_list = self.value_range.data_list
        if data_list is None or len(data_list) != 2:
            return False
        values = sorted(item.data for item in data_list)
        return values == ["false", "true"] or values == ["0", "1"]

    @property
    def is_enum(self) -> bool:
        """True if LIST type and not a boolean attribute."""
        if self.value_range is None or self.value_range.type != "LIST":
            return False
        return not self.is_bool

    @property
    def is_numeric(self) -> bool:
        """True if STEP type."""
        if self.value_range is None:
            return False
        return self.value_range.type == "STEP"

    def get_enum_values(self) -> list[str]:
        """Return list of data values from data_list."""
        if self.value_range is None or self.value_range.data_list is None:
            return []
        return [item.data for item in self.value_range.data_list]

    def get_enum_items(self) -> list[DataListItem]:
        """Get the full enum entries (data/code/desc)."""
        if self.value_range is None or self.value_range.data_list is None:
            return []
        return list(self.value_range.data_list)

    def update(self, raw: dict) -> None:
        """Update current value and optionally value_range from raw dict."""
        if "value" in raw:
            self._current_value = raw["value"]
        if "valueRange" in raw:
            self.value_range = _build_value_range(raw["valueRange"])


# ---------------------------------------------------------------------------
# Task 1.4: UhomeDevice class
# ---------------------------------------------------------------------------


class UhomeDevice:
    """Represents a single Haier smart device."""

    def __init__(
        self,
        device_id: str,
        pid: str,
        app_type_code: str,
        attributes: dict[str, Attribute],
        *,
        device_name: str | None = None,
        suggested_area: str | None = None,
        family_id: str | None = None,
    ) -> None:
        self.device_id = device_id
        self.pid = pid
        self.device_type: str = DEVICE_TYPE_MAP.get(app_type_code, "UNKNOWN")
        self.attributes = attributes
        self.device_name = device_name or device_id
        self.suggested_area = suggested_area
        self.family_id = family_id
        self._online: bool = False

    def get_value(self, name: str) -> Any:
        """Get the current value of an attribute by name."""
        attr = self.attributes.get(name)
        if attr is None:
            return None
        return attr.current_value

    def get_attribute(self, name: str) -> Attribute | None:
        """Get an Attribute object by name."""
        return self.attributes.get(name)

    def set_online(self, online: bool) -> None:
        """Set device online status."""
        self._online = online

    def async_on_message(self, message: dict) -> None:
        """Process incoming message data and update attributes."""
        data = message.get("data", [])
        for item in data:
            attr_name = item.get("name")
            if attr_name and attr_name in self.attributes:
                self.attributes[attr_name].update(item)


# ---------------------------------------------------------------------------
# Task 1.5: MockCoordinator class
# ---------------------------------------------------------------------------


class MockCoordinator:
    """Mock coordinator for testing without real WebSocket connection."""

    def __init__(self, area: str, devices: dict[str, UhomeDevice]) -> None:
        self._area = area
        self._region = area  # region defaults to area value
        self._devices = devices
        self._connected = True
        self._listeners: list[Callable] = []

    @property
    def devices(self) -> dict[str, UhomeDevice]:
        """Return all managed devices."""
        return self._devices

    @property
    def area(self) -> str:
        """Return area/family name."""
        return self._area

    @property
    def region(self) -> str:
        """Return region (e.g. 'cn', 'eu')."""
        return self._region

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._connected

    def async_add_listener(self, callback: Callable) -> Callable:
        """Register a listener callback. Returns an unsubscribe function."""
        self._listeners.append(callback)

        def _unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return _unsubscribe

    async def async_send_command(self, device_id: str, commands: dict) -> None:
        """Log the command (mock implementation)."""
        _LOGGER.debug(
            "MockCoordinator: send_command device=%s commands=%s",
            device_id,
            commands,
        )

    def _notify_listeners(self) -> None:
        """Call all registered listeners."""
        for listener in self._listeners:
            listener()


# ---------------------------------------------------------------------------
# Task 1.6: MockClient class
# ---------------------------------------------------------------------------


class MockClient:
    """Mock API client for testing without real network calls."""

    async def async_get_families(self) -> dict[str, list[dict[str, Any]]]:
        """Return mock family list matching API structure."""
        return {
            "createfamilies": [
                {
                    "familyId": "mock_family_001",
                    "familyName": "我的家",
                    "isDefault": 1,
                    "floorInfos": None,
                },
                {
                    "familyId": "mock_family_002",
                    "familyName": "青岛家庭",
                    "isDefault": 0,
                    "floorInfos": None,
                },
            ],
            "joinfamilies": [
                {
                    "familyId": "mock_family_003",
                    "familyName": "加入的家庭",
                    "isDefault": 0,
                    "floorInfos": None,
                },
            ],
        }

    async def async_get_devices(self, family_ids: list[str] | None = None) -> dict:
        """Return mock device list matching API structure."""
        devices = [
            {
                "device_id": "mock_ac_001",
                "device_name": "客厅空调",
                "pid": "test_pid_001",
                "app_type_code": "A177",
                "online": True,
                "familyId": "mock_family_001",
                "room_name": "Living Room",
            },
        ]

        if family_ids:
            devices = [d for d in devices if d.get("familyId") in family_ids]

        return {"deviceInfos": devices}

    async def async_get_scenes(self, family_ids: list[str]) -> list[dict]:
        """Return mock scene list matching the real API field names.

        Real API scene objects use ``sceneId``/``sceneName``. Note the real
        payload does NOT include ``familyName`` — that absence is a known bug
        to investigate later (the scene device label currently falls back to
        the family id).
        """
        return [
            {
                "sceneId": "scene_001",
                "sceneName": "回家模式",
                "family_id": family_ids[0] if family_ids else "",
                "enabled": True,
                "isOpen": 1,
            },
            {
                "sceneId": "scene_002",
                "sceneName": "离家模式",
                "family_id": family_ids[0] if family_ids else "",
                "enabled": True,
                "isOpen": 1,
            },
        ]

    async def async_trigger_scene(self, scene_id: str) -> None:
        """Log scene trigger (mock implementation)."""
        _LOGGER.debug("MockClient: trigger_scene scene_id=%s", scene_id)

    async def execute_scene(self, family_id: str, scene_id: str) -> None:
        """Log scene execution (mock implementation).

        Mirrors ``HaierHttpClient.execute_scene`` so the scene platform can be
        exercised end-to-end against the mock client.
        """
        _LOGGER.debug("MockClient: execute_scene family_id=%s scene_id=%s", family_id, scene_id)

    async def async_get_eula(self, language: str) -> str:
        """Return mock EULA text based on language."""
        if language.startswith("zh"):
            return """# 海尔智家集成使用风险告知与免责声明

## 风险提示

**1. 信息安全风险**

您的海尔智家用户信息与设备信息将会存储在您的 Home Assistant 系统中。

**2. 非官方支持**

此集成由开源社区独立维护，非海尔官方提供支持。

**3. 使用门槛**

此集成的部署、调试与运维需具备一定的智能家居技术能力与编程基础。

---

## 确认声明

我已悉知以上全部风险条款，并自愿承担因使用此集成所产生的一切相关风险与责任。
"""
        return """# Haier Home Integration Risk Disclosure and Disclaimer

## Risk Warning

**1. Information Security Risk**

Your Haier Home user information and device information will be stored in your Home Assistant system.

**2. Non-Official Support**

This integration is independently maintained by the open-source community and is not officially supported by Haier.

**3. Usage Threshold**

Deployment, debugging, and operation of this integration require certain smart home technical capabilities and programming foundation.

---

## Confirmation Statement

I acknowledge all the above risk terms and voluntarily assume all risks and responsibilities arising from the use of this integration.
"""


# ---------------------------------------------------------------------------
# Task 1.7: Factory functions
# ---------------------------------------------------------------------------


def _mock_ac_attributes() -> dict[str, Attribute]:
    """Return the standard attribute set for a mock AC device."""
    return {
        "onOffStatus": Attribute(
            name="onOffStatus",
            desc="开关机",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="true",
            invisible=False,
            value_range=ValueRange(
                type="LIST",
                data_list=[
                    DataListItem(data="false", desc="关机"),
                    DataListItem(data="true", desc="开机"),
                ],
            ),
        ),
        "operationMode": Attribute(
            name="operationMode",
            desc="运行模式",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="1",
            invisible=False,
            value_range=ValueRange(
                type="LIST",
                data_list=[
                    DataListItem(data="0", desc="auto"),
                    DataListItem(data="1", desc="cool"),
                    DataListItem(data="2", desc="dry"),
                    DataListItem(data="4", desc="heat"),
                    DataListItem(data="6", desc="fan_only"),
                ],
            ),
        ),
        "targetTemperature": Attribute(
            name="targetTemperature",
            desc="目标温度",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="24",
            invisible=False,
            value_range=ValueRange(
                type="STEP",
                data_step=DataStep(
                    data_type="Double",
                    min_value="16",
                    max_value="30",
                    step="0.5",
                ),
            ),
        ),
        "windSpeed": Attribute(
            name="windSpeed",
            desc="风速",
            readable=True,
            writable=True,
            operation_type=None,
            default_value="5",
            invisible=False,
            value_range=ValueRange(
                type="LIST",
                data_list=[
                    DataListItem(data="1", desc="high"),
                    DataListItem(data="2", desc="medium"),
                    DataListItem(data="3", desc="low"),
                    DataListItem(data="5", desc="auto"),
                    DataListItem(data="7", desc="mid_high"),
                    DataListItem(data="8", desc="mid_low"),
                ],
            ),
        ),
        "indoorTemperature": Attribute(
            name="indoorTemperature",
            desc="室内温度",
            readable=True,
            writable=False,
            operation_type=None,
            default_value="25",
            invisible=False,
            value_range=ValueRange(
                type="STEP",
                data_step=DataStep(
                    data_type="Double",
                    min_value="-20",
                    max_value="60",
                    step="0.1",
                ),
            ),
        ),
    }


def create_mock_ac_device(
    *,
    device_id: str = "mock_ac_001",
    device_name: str = "客厅空调",
    pid: str = "test_pid_001",
    app_type_code: str = "A177",
    suggested_area: str | None = "Living Room",
    family_id: str | None = "mock_family_001",
    online: bool = True,
) -> UhomeDevice:
    """Create a realistic mock AC device for testing."""
    device = UhomeDevice(
        device_id=device_id,
        pid=pid,
        app_type_code=app_type_code,
        attributes=_mock_ac_attributes(),
        device_name=device_name,
        suggested_area=suggested_area,
        family_id=family_id,
    )
    device.set_online(online)
    return device


def create_mock_coordinator(area: str = "cn") -> MockCoordinator:
    """Create a MockCoordinator with one AC device."""
    ac_device = create_mock_ac_device()
    devices = {ac_device.device_id: ac_device}
    return MockCoordinator(area=area, devices=devices)
