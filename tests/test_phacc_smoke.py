"""Smoke test: verify the PHACC harness boots real HA and loads haier_home."""

from homeassistant.core import HomeAssistant

from custom_components.haier_home.const import DOMAIN


async def test_phacc_hass_fixture_works(hass: HomeAssistant) -> None:
    """The real ``hass`` fixture boots up a live Home Assistant."""
    assert hass is not None
    assert hass.config is not None


def test_integration_importable() -> None:
    """haier_home const module imports under real HA."""
    assert DOMAIN == "haier_home"
