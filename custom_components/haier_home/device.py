"""Device model module for Haier Home integration.

Contains core device models used in production code:
- ValueRange: Represents valid range of attribute values
- Attribute: Represents a device attribute with value and metadata
- HaierDevice: Represents a Haier device

Also provides helper functions for parsing device data from API responses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .const import DEVICE_TYPE_MAP, MANAGED_AREA_SYNC_MODES

_LOGGER = logging.getLogger(__name__)


def _resolve_device_type(app_type_code: str) -> str:
    """Resolve a Haier ``appTypeCode`` to an internal device type code.

    Wraps :data:`DEVICE_TYPE_MAP` so callers do not need to import it or
    remember the fallback token. Unknown codes yield ``"UNKNOWN"``.
    """
    return DEVICE_TYPE_MAP.get(app_type_code, "UNKNOWN")


@dataclass
class Transform:
    """The raw ``dataStep.transform`` coefficients (``k`` / ``c``), unapplied.

    The cloud spec describes a linear relation ``y = k * x + c``, but this
    integration deliberately **never applies it** in either direction: the
    reported value, the ``minValue``/``maxValue``/``step`` bounds and the
    value the cloud accepts in a command all live on the same scale, so any
    conversion shifts us off that scale and breaks both read and write.

    Observed evidence (AC ``targetTemperature`` while ``operationMode=0``,
    i.e. auto; the cloud attaches this range as a conditional modifier and
    omits it in the other modes)::

        "dataStep": {"dataType": "double", "minValue": "23.0000",
                     "maxValue": "29.0000", "step": "1.0000",
                     "transform": {"k": "1.0000", "c": "26.0000"}}
        "value": "26.0000"

    Applying the inverse on read turned the reported 26 into ``(26-26)/1 = 0``
    (HA showed a 0 °C setpoint); applying the forward direction on write
    turned a requested 23 into 49, which the cloud rejected with
    ``errRange {"max": "29"}`` / ``info "超出取值范围"`` — the very bounds it
    had just published. Keeping 26 and sending 23 unchanged is consistent
    with all three.

    The coefficients are still parsed so they remain visible for diagnostics
    and so a future spec clarification can be revisited from real payloads.
    """

    k: float
    c: float


@dataclass
class DataListItem:
    """A single entry of a ``LIST`` type ``dataList``.

    - ``data``: the selectable value, matching the device model doc.
    - ``code``: optional legacy six-digit code from the device-ID doc.
    - ``desc``: optional human-readable description.
    """

    data: str
    code: str | None = None
    desc: str | None = None


@dataclass
class DataStep:
    """A ``STEP`` type range (the cloud ``dataStep`` object).

    ``min_value``/``max_value``/``step`` are kept as strings as delivered by
    the cloud and are used as-is: reported values, these bounds and command
    values all share one scale (see :class:`Transform` for why the declared
    ``transform`` is parsed but never applied). ``fallback`` is substituted
    when a requested value falls outside the range.
    """

    data_type: str | None = None  # "Integer" | "Double"
    step: str | None = None
    min_value: str | None = None
    max_value: str | None = None
    transform: Transform | None = None
    fallback: str | None = None

    def to_command_value(self, display_value: float) -> str:
        """Convert a UI value into the command string to send.

        - Coerces to the declared ``data_type`` ("Integer" is rounded).
        - When the requested value is outside ``[min_value, max_value]`` and a
          ``fallback`` is configured, the fallback is sent verbatim (per the
          spec's compensation-overflow rule).

        No linear conversion is applied; ``transform`` is intentionally
        ignored (see :class:`Transform`).
        """
        if self.fallback is not None and self.out_of_range(display_value):
            return self.fallback
        return self._coerce(self._quantize(display_value))

    def _quantize(self, value: float) -> float:
        """Snap ``value`` onto the ``min_value``/``step`` grid and clamp it.

        The reported bounds and step define a discrete grid (e.g. 16-30 by
        0.5). A UI value may land off that grid -- most notably when HA is set
        to Fahrenheit and converts the user's choice back to the device's
        native Celsius scale (84 F -> 28.888... C). Sending such a value
        verbatim yields an illegal setpoint the device may reject or clamp
        unpredictably, so it is rounded to the nearest grid point and clamped
        to ``[min_value, max_value]``.

        Unparseable/absent step or bounds are skipped gracefully, leaving the
        value (or the applicable clamp) unchanged.
        """
        min_v = self._as_float(self.min_value)
        max_v = self._as_float(self.max_value)
        step = self._as_float(self.step)

        if step is not None and step > 0:
            base = min_v if min_v is not None else 0.0
            value = base + round((value - base) / step) * step
            # Round away binary-float noise (e.g. 28.500000000000004) while
            # preserving legitimate precision within typical step sizes.
            value = round(value, 6)

        if min_v is not None and value < min_v:
            value = min_v
        if max_v is not None and value > max_v:
            value = max_v
        return value

    @staticmethod
    def _as_float(raw: str | None) -> float | None:
        """Parse a bound/step string to float, or None if unusable."""
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):  # fmt: skip
            return None

    def _coerce(self, value: float) -> str:
        """Format ``value`` as a command string honoring ``data_type``.

        "Integer" is rounded to a whole number. For "Double" (or unspecified)
        a whole number is rendered without a trailing ``.0`` (e.g. ``26`` not
        ``26.0``) while fractional values keep their decimals (``28.5``).
        """
        if self.data_type == "Integer":
            return str(int(round(value)))
        if float(value).is_integer():
            return str(int(value))
        return str(value)

    def out_of_range(self, value: float) -> bool:
        """Return True if ``value`` is outside the declared bounds.

        Unparseable bounds are treated as "no bound" (returns False) so a
        malformed payload never hides an otherwise usable value.
        """
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
    """A ``TIME`` type range (the cloud ``dataTime`` object).

    ``format`` uses HH/mm/ss (or H/m/s) tokens, e.g. "HH:mm". The bounds are
    inclusive: hours 0-23, minutes/seconds 0-59.
    """

    format: str | None = None
    min_hour: int | None = None
    max_hour: int | None = None
    min_minute: int | None = None
    max_minute: int | None = None
    min_second: int | None = None
    max_second: int | None = None


@dataclass
class DataDate:
    """A ``DATE`` type range (the cloud ``dataDate`` object).

    ``format`` uses y/M/d tokens, e.g. "yyyyMMdd". ``begin_date``/``end_date``
    are strings matching that format.
    """

    format: str | None = None
    begin_date: str | None = None
    end_date: str | None = None


@dataclass
class ValueRange:
    """Represents the valid range of an attribute value.

    Mirrors the cloud ``valueRange`` object. Exactly one of the payload
    sub-objects is populated depending on ``type``:
    - "NONE": no constraint; all sub-objects are ``None``.
    - "LIST": ``data_list`` holds :class:`DataListItem` entries.
    - "STEP": ``data_step`` holds a :class:`DataStep`.
    - "TIME": ``data_time`` holds a :class:`DataTime`.
    - "DATE": ``data_date`` holds a :class:`DataDate`.

    Enums and booleans are represented as LIST per the spec.
    """

    type: str  # "NONE" | "LIST" | "STEP" | "TIME" | "DATE"
    data_list: list[DataListItem] | None = None
    data_step: DataStep | None = None
    data_time: DataTime | None = None
    data_date: DataDate | None = None


@dataclass
class Attribute:
    """Represents a single device attribute with value and metadata."""

    name: str
    desc: str | None = None
    readable: bool = True
    writable: bool = False
    operation_type: str | None = None
    default_value: str | None = None
    invisible: bool = False
    value_range: ValueRange | None = None
    current_value: str | None = None

    @property
    def is_numeric(self) -> bool:
        """Check if attribute value is numeric type."""
        return self.value_range is not None and self.value_range.type == "STEP"

    @property
    def is_enum(self) -> bool:
        """Check if attribute value is enum type."""
        return self.value_range is not None and self.value_range.type == "LIST"

    @property
    def is_bool(self) -> bool:
        """Check if attribute value is boolean type."""
        if not self.is_enum or self.value_range is None:
            return False
        values = {item.data for item in self.value_range.data_list or []}
        return values == {"0", "1"} or values == {"false", "true"}

    def get_enum_values(self) -> list[str]:
        """Get list of possible enum values."""
        if not self.is_enum or self.value_range is None:
            return []
        return [item.data for item in self.value_range.data_list or []]

    def get_enum_items(self) -> list[DataListItem]:
        """Get the full enum entries (``data``/``code``/``desc``).

        Unlike :meth:`get_enum_values`, this preserves each entry's
        human-readable ``desc`` so callers can fall back to it for codes that
        have no static mapping.
        """
        if not self.is_enum or self.value_range is None:
            return []
        return list(self.value_range.data_list or [])

    def update(self, item: dict) -> None:
        """Selectively update fields from a WebSocket ``data`` entry.

        Only keys present in ``item`` are applied; missing keys leave the
        current field unchanged. Recognized keys mirror the wire schema:

        - ``value``       -> ``current_value``
        - ``writable``    -> ``writable``
        - ``valueRange``  -> ``value_range`` (parsed via :func:`build_value_range`)

        Unknown keys are ignored, so future spec fields can be forwarded
        without breaking older clients.
        """
        if "value" in item:
            self.current_value = item["value"]
        if "writable" in item:
            self.writable = bool(item["writable"])
        if "valueRange" in item:
            parsed = build_value_range(item["valueRange"])
            if parsed is not None:
                self.value_range = parsed


@dataclass
class HaierDevice:
    """Represents a Haier device with its attributes."""

    device_id: str
    pid: str
    app_type_code: str
    attributes: dict[str, Attribute] = field(default_factory=dict)
    device_name: str | None = None
    suggested_area: str | None = None
    family_id: str | None = None
    # Every area name this integration could have generated for the device
    # across all room-sync modes. Used on reload to recognize an
    # integration-managed area and tell it apart from a user's custom one
    # (see build_area_name_candidates()).
    managed_area_names: list[str] = field(default_factory=list)
    _online: bool = True

    @property
    def device_type(self) -> str:
        """Get device type based on app_type_code."""
        return _resolve_device_type(self.app_type_code)

    def get_value(self, attr_name: str) -> str | None:
        """Get current value of an attribute.

        Returns ``None`` when the attribute is not defined on this device.
        The value's own default (``current_value``) is returned otherwise,
        falling back to ``default_value`` if current_value is None.
        """
        attr = self.attributes.get(attr_name)
        if attr is None:
            return None
        return attr.current_value if attr.current_value is not None else attr.default_value

    def get_attribute(self, attr_name: str) -> Attribute | None:
        """Get attribute object by name."""
        return self.attributes.get(attr_name)

    @property
    def online(self) -> bool:
        """Device online state.

        Updated by :meth:`set_online` when the coordinator observes an
        online/offline push or an attribute report.
        """
        return self._online

    def set_online(self, online: bool) -> None:
        """Set device online status."""
        self._online = online

    def async_on_message(self, message: dict) -> None:
        """Consume a normalized WebSocket update and refresh attributes.

        The message shape is intentionally decoupled from the wire format;
        the coordinator flattens the raw ``args.attributes`` payload into a
        uniform envelope before calling this method::

            {"data": [{"name": "indoorTemperature", "value": "26.5"}, ...]}

        Each entry is dispatched to :meth:`Attribute.update`, which applies
        fields selectively; unknown attribute names are ignored.

        The ``async_`` prefix follows the Home Assistant convention meaning
        "safe to call from the event loop"; the body itself is synchronous.

        Individual malformed entries (e.g. not a dict, or missing expected
        keys) are logged and skipped so one bad entry does not abort the
        rest of the batch.
        """
        for item in message.get("data") or []:
            try:
                name = item.get("name")
                attr = self.attributes.get(name) if name else None
                if attr is not None:
                    attr.update(item)
            except Exception:
                _LOGGER.warning("Failed to update attribute from item %s", item, exc_info=True)


def _build_transform(step_data: dict) -> Transform | None:
    """Build a :class:`Transform` from a ``dataStep.transform`` object.

    Returns ``None`` when the transform is absent or malformed (``k`` must be
    a non-zero number per the spec); callers then treat the value 1:1.
    """
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
    """Build :class:`DataListItem` entries from a raw ``dataList`` array."""
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


def _build_data_step(value_range_data: dict) -> DataStep:
    """Build a :class:`DataStep` from a ``valueRange`` payload.

    Numeric bounds live under ``dataStep``; older/HTTP payloads that put them
    at the top level are still accepted for backward compatibility.
    """
    step_data = value_range_data.get("dataStep") or {}
    return DataStep(
        data_type=step_data.get("dataType"),
        step=step_data.get("step", value_range_data.get("step")),
        min_value=step_data.get("minValue", value_range_data.get("minValue")),
        max_value=step_data.get("maxValue", value_range_data.get("maxValue")),
        transform=_build_transform(step_data),
        fallback=step_data.get("fallback", value_range_data.get("fallback")),
    )


def _build_data_time(raw: dict | None) -> DataTime:
    """Build a :class:`DataTime` from a raw ``dataTime`` object."""
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
    """Build a :class:`DataDate` from a raw ``dataDate`` object."""
    raw = raw or {}
    return DataDate(
        format=raw.get("format"),
        begin_date=raw.get("beginDate"),
        end_date=raw.get("endDate"),
    )


def build_value_range(value_range_data: dict | None) -> ValueRange | None:
    """Build a :class:`ValueRange` from a raw ``valueRange`` payload.

    Dispatches on ``type`` and populates the matching sub-object
    (``data_list``/``data_step``/``data_time``/``data_date``). ``NONE`` and
    unknown types yield a bare ValueRange with no constraints.
    """
    if not value_range_data:
        return None

    vr_type = value_range_data.get("type", "")
    if vr_type == "STEP":
        return ValueRange(type="STEP", data_step=_build_data_step(value_range_data))
    if vr_type == "LIST":
        return ValueRange(type="LIST", data_list=_build_data_list(value_range_data.get("dataList")))
    if vr_type == "TIME":
        return ValueRange(type="TIME", data_time=_build_data_time(value_range_data.get("dataTime")))
    if vr_type == "DATE":
        return ValueRange(type="DATE", data_date=_build_data_date(value_range_data.get("dataDate")))
    if vr_type == "NONE":
        return ValueRange(type="NONE")
    return None


def parse_digital_model(digital_model: dict) -> dict[str, Attribute]:
    """Parse device digital model from API into Attribute objects.

    Args:
        digital_model: Raw digital model data from API

    Returns:
        Dictionary of Attribute objects keyed by attribute name
    """
    attributes: dict[str, Attribute] = {}

    # Extract attribute list from different possible response structures
    # Priority: direct list > attributes > data.attributes > data.attrList > attrList
    if isinstance(digital_model, list):
        attr_list = digital_model
    else:
        attr_list = digital_model.get("attributes", [])
        if not attr_list:
            attr_list = digital_model.get("data", {}).get("attributes", [])
        if not attr_list:
            _LOGGER.warning("No attributes found in digital model")
            return attributes

    for attr_data in attr_list:
        name = attr_data.get("name", "")
        if not name:
            continue

        desc = attr_data.get("desc", name)
        readable = attr_data.get("readable", True)
        writable = attr_data.get("writable", False)
        operation_type = attr_data.get("operationType")
        default_value = attr_data.get("defaultValue", "")
        invisible = attr_data.get("invisible", False)
        current_value = attr_data.get("value", "")

        # Parse value range
        value_range = build_value_range(attr_data.get("valueRange", {}))

        attributes[name] = Attribute(
            name=name,
            desc=desc,
            readable=readable,
            writable=writable,
            operation_type=operation_type,
            default_value=default_value,
            invisible=invisible,
            value_range=value_range,
            current_value=current_value,
        )

    return attributes


def build_suggested_area(
    record: dict,
    family_name: str | None = None,
    room_sync_mode: str = "family_and_room",
) -> str | None:
    """Compute the HA suggested area for a device based on the sync mode.

    The "room" portion combines the floor and room names (e.g. "一层 卧室"),
    matching the option labels shown in the config flow:

    - ``none``             -> None (device is not assigned to any area)
    - ``family_and_room``  -> "<family> <floor> <room>"  (e.g. "我的家 一层 卧室")
    - ``room_only``        -> "<floor> <room>"            (e.g. "一层 卧室")
    - ``family_only``      -> "<family>"                  (e.g. "我的家")

    Args:
        record: Device record from API (supports snake_case and camelCase).
        family_name: Resolved family/home name for the device's familyId.
        room_sync_mode: One of the room sync modes selected in the config flow.

    Returns:
        The suggested area string, or None when no area should be assigned or
        no name components are available.
    """
    if room_sync_mode == "none":
        return None

    floor = (record.get("dev_floor_name") or record.get("devFloorName") or "").strip()
    room = (record.get("room_name") or record.get("room") or record.get("roomName") or "").strip()
    room_part = " ".join(part for part in (floor, room) if part)
    family_part = (family_name or "").strip()

    if room_sync_mode == "family_only":
        return family_part or None
    if room_sync_mode == "room_only":
        return room_part or None

    # Default: "family_and_room"
    return " ".join(part for part in (family_part, room_part) if part) or None


def build_area_name_candidates(
    record: dict,
    family_name: str | None = None,
) -> list[str]:
    """Return every area name this integration could generate for a device.

    The active ``room_sync_mode`` only decides which name is written *now*
    (via :func:`build_suggested_area`). But the mode can change between
    reloads, so a device's current area may have been produced under a
    *different* mode. To reconcile areas on reload without a volatile tracking
    cache, we enumerate the area name each mode would produce for this device
    (``none`` yields no name and is skipped) and treat that set as the names
    the integration "owns". A reload-time guard can then move any device whose
    current area is empty or in this set to the current mode's area, while
    leaving a genuinely custom area untouched.

    Ordering is deterministic (family_and_room, room_only, family_only) with
    duplicates removed, so the result is stable for logging/equality.

    Args:
        record: Device record from API (supports snake_case and camelCase).
        family_name: Resolved family/home name for the device's familyId.

    Returns:
        A de-duplicated list of candidate area names (possibly empty).
    """
    candidates: list[str] = []
    for mode in MANAGED_AREA_SYNC_MODES:
        name = build_suggested_area(record, family_name, room_sync_mode=mode)
        if name and name not in candidates:
            candidates.append(name)
    return candidates


def create_device_from_api_record(
    record: dict,
    attributes: dict[str, Attribute] | None = None,
    *,
    room_sync_mode: str = "family_and_room",
    family_name: str | None = None,
) -> HaierDevice | None:
    """Build a HaierDevice from a device list record.

    Args:
        record: Device record from API (supports both snake_case and camelCase)
        attributes: Optional dict of Attribute objects. If None, uses empty attributes.
        room_sync_mode: Room name sync mode selected in the config flow; controls
            how ``suggested_area`` is composed (see :func:`build_suggested_area`).
        family_name: Resolved family/home name for the device's familyId, used
            when the sync mode includes the family name.
    """
    # Support both snake_case (mock) and camelCase (real API) field names
    app_type_code = record.get("app_type_code", record.get("apptypeCode", ""))
    device_type = _resolve_device_type(app_type_code)
    if device_type != "AC":
        return None

    device_id = record.get("device_id", record.get("deviceId", ""))
    if not device_id:
        return None

    # Use provided attributes or empty dict
    device_attributes = attributes if attributes is not None else {}

    device = HaierDevice(
        device_id=device_id,
        pid=record.get("pid", "unknown"),
        app_type_code=app_type_code,
        attributes=device_attributes,
        device_name=record.get("device_name", record.get("devName", device_id)),
        suggested_area=build_suggested_area(record, family_name, room_sync_mode),
        family_id=record.get("family_id", record.get("familyId")),
        managed_area_names=build_area_name_candidates(record, family_name),
    )
    device.set_online(record.get("online", record.get("isOnline", True)))
    return device
