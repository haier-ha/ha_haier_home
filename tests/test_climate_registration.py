"""End-to-end tests for the Climate platform registration mechanism.

Drives mock AC data through ``climate.async_setup_entry`` so the
registry lookup path (``_specific_registry`` → ``_generic_registry`` →
``_platform_registry``) is exercised together with
``HaierClimateEntity`` property resolution and command dispatch.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from custom_components.haier_home import climate as climate_mod

# Importing the ``extend`` package triggers auto-discovery of PID-specific
# entity subclasses (e.g. CommonABClimateEntity for ``pid_common_a``), which
# populates the generic registry. In production this happens via
# ``async_setup`` (``from . import extend``); the unit tests bypass that path,
# so import it here so the generic-registry lookup can resolve.
from custom_components.haier_home import extend as _extend  # noqa: F401

# Call load_extensions() to actually import extension modules and register PIDs
_extend.load_extensions()
from custom_components.haier_home.const import DOMAIN  # noqa: E402
from custom_components.haier_home.entity import HaierDeviceEntity  # noqa: E402
from tests.mock_data import (  # noqa: E402
    MockClient,
    create_mock_ac_device,
    create_mock_coordinator,
)

HVACMode = sys.modules["homeassistant.components.climate"].HVACMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hass(coordinator, client) -> SimpleNamespace:
    """Build a minimal hass-like object for platform setup + send_command."""
    fired: list[tuple[str, dict]] = []

    bus = SimpleNamespace(async_fire=lambda evt, payload: fired.append((evt, payload)))
    hass = SimpleNamespace(
        data={DOMAIN: {"entry_1": {"coordinator": coordinator, "client": client}}},
        bus=bus,
    )
    hass.fired = fired  # for assertions
    return hass


def _make_entry(entry_id: str = "entry_1") -> SimpleNamespace:
    return SimpleNamespace(entry_id=entry_id)


# ---------------------------------------------------------------------------
# async_setup_entry registers entities through the registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_setup_entry_resolves_platform_fallback():
    """Default PID with no specific/generic match → platform fallback."""
    coordinator = create_mock_coordinator()
    hass = _make_hass(coordinator, MockClient())

    captured: list = []
    await climate_mod.async_setup_entry(hass, _make_entry(), captured.extend)

    assert len(captured) == 1
    entity = captured[0]
    assert type(entity) is climate_mod.HaierClimateEntity
    assert entity.unique_id == "haier_home_cn_mock_ac_001_climate"


@pytest.mark.asyncio
async def test_async_setup_entry_uses_generic_registry_for_known_pid():
    """PID listed in extend/common_ab.py resolves to CommonABClimateEntity."""
    # Importing extend/ at module import time already populated registries.
    # Build a coordinator whose AC device advertises a generic-registered PID.
    ac = create_mock_ac_device()
    ac.pid = "pid_common_a"
    coordinator = create_mock_coordinator()
    coordinator._devices = {ac.device_id: ac}

    hass = _make_hass(coordinator, MockClient())

    captured: list = []
    await climate_mod.async_setup_entry(hass, _make_entry(), captured.extend)

    from custom_components.haier_home.extend.common_ab import (
        CommonABClimateEntity,
    )

    assert len(captured) == 1
    assert type(captured[0]) is CommonABClimateEntity
    assert captured[0].MODE_NAME_MAP["2"] == "heat"  # diff vs default


@pytest.mark.asyncio
async def test_specific_registry_overrides_generic_and_platform():
    """A @register(pid, platform) entry wins over generic and platform."""

    @HaierDeviceEntity.register("pid_setup_specific", "climate")
    class _SpecificClimate(climate_mod.HaierClimateEntity):
        MODE_NAME_MAP = {1: "cool"}

    try:
        ac = create_mock_ac_device()
        ac.pid = "pid_setup_specific"
        coordinator = create_mock_coordinator()
        coordinator._devices = {ac.device_id: ac}

        hass = _make_hass(coordinator, MockClient())

        captured: list = []
        await climate_mod.async_setup_entry(hass, _make_entry(), captured.extend)

        assert len(captured) == 1
        assert type(captured[0]) is _SpecificClimate
    finally:
        HaierDeviceEntity._specific_registry.pop(("pid_setup_specific", "climate"), None)


@pytest.mark.asyncio
async def test_setup_skips_non_ac_devices():
    """Devices whose device_type != AC are not added to the climate platform."""
    coordinator = create_mock_coordinator()

    # Mutate the in-coordinator device so its type no longer matches "AC".
    for dev in coordinator.devices.values():
        dev.device_type = "FRIDGE"

    hass = _make_hass(coordinator, MockClient())

    captured: list = []
    await climate_mod.async_setup_entry(hass, _make_entry(), captured.extend)

    assert captured == []


# ---------------------------------------------------------------------------
# Resolved entity exposes correct climate state and dispatches commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolved_entity_reads_mock_state_and_emits_commands():
    coordinator = create_mock_coordinator()
    hass = _make_hass(coordinator, MockClient())

    # Spy on the coordinator command sink. ``send_command`` dispatches directly
    # to ``coordinator.async_send_command`` (see entity.py), so capture those
    # calls instead of HA bus events.
    sent: list[tuple[str, dict]] = []

    async def _capture_send(device_id, commands):
        sent.append((device_id, commands))

    coordinator.async_send_command = _capture_send

    captured: list = []
    await climate_mod.async_setup_entry(hass, _make_entry(), captured.extend)

    entity = captured[0]
    entity.hass = hass

    # State derived from mock attributes.
    assert entity.target_temperature == 24.0
    assert entity.current_temperature == 25.0
    assert entity.fan_mode == "auto"
    # hvac_modes always includes the OFF sentinel plus unique registered modes.
    assert len(entity.hvac_modes) == 1 + len(set(entity.MODE_NAME_MAP.values()))

    # Drive commands; verify the coordinator receives them.
    await entity.async_set_temperature(temperature=26)
    await entity.async_set_fan_mode("low")
    await entity.async_set_hvac_mode(HVACMode.OFF)

    device_ids = [device_id for device_id, _ in sent]
    payloads = [commands for _, commands in sent]

    assert device_ids == [entity._device.device_id] * 3
    assert {"targetTemperature": "26"} in payloads
    assert {"windSpeed": "3"} in payloads
    assert {"onOffStatus": "false"} in payloads
