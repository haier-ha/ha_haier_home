"""Example PID extension: custom mode mapping for specific PIDs."""

from ..climate import HaierClimateEntity
from ..entity import HaierDeviceEntity


@HaierDeviceEntity.register(["pid_common_a", "pid_common_b"], "climate")
class CommonABClimateEntity(HaierClimateEntity):
    """Climate entity with different mode mapping for PID A and B."""

    # Keys MUST be strings: hvac_mode/hvac_modes look modes up via
    # MODE_NAME_MAP.get(str(v)). Integer keys silently never match, so the
    # override would be a no-op.
    MODE_NAME_MAP = {
        "0": "auto",
        "1": "cool",
        "2": "heat",
        "3": "dry",
        "6": "fan_only",
    }
