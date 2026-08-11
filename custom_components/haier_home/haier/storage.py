"""Local persistent cache for the Haier Home integration.

An HA integration does not "restart" on its own; a Home Assistant *service*
restart tears the config entry down and re-runs ``async_setup_entry`` from
scratch, so all in-memory (RAM) state is lost. To avoid re-fetching the whole
device list and every device's digital model from the cloud on each restart,
this module persists them to ``config/.storage/`` via Home Assistant's
:class:`~homeassistant.helpers.storage.Store` helper, which *does* survive
restarts.

Strategy implemented:

* device list      -> cloud-first; the cache is a fallback used only when the
  cloud is unreachable, so newly added/removed devices show up on restart.
* digital models   -> per device, cloud-first; cache is the offline fallback.
* scenes           -> cloud-first; cache (then config-entry seed) is fallback.

``DEFAULT_TTL`` bounds freshness for normal (online) reads. The offline
fallback path (``allow_stale=True``) intentionally ignores the TTL: when the
cloud cannot be reached, stale data is better than no data at all.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Bump when the on-disk structure changes in a backwards-incompatible way.
STORAGE_VERSION = 1

# Cache freshness window in seconds. Entries older than this are treated as a
# cache miss so the cloud is queried again. Keeps startup fast while ensuring
# device metadata (enums, ranges, added/removed devices) eventually refreshes.
DEFAULT_TTL = 7 * 24 * 3600  # 7 days


def _storage_key(entry_id: str) -> str:
    """Return the ``.storage`` file key for a config entry's cache."""
    return f"{DOMAIN}.cache_{entry_id}"


class HaierDeviceCache:
    """Persistent cache for the device list and per-device digital models.

    The cache is loaded once into memory (:meth:`async_load`); reads and writes
    then operate on that in-memory copy, and :meth:`async_save` flushes it back
    to disk in a single write. This avoids one disk write per device during
    setup while still surviving HA service restarts.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        ttl: int = DEFAULT_TTL,
    ) -> None:
        """Initialize the cache for a specific config entry."""
        self._store: Store = Store(hass, STORAGE_VERSION, _storage_key(entry_id))
        self._ttl = ttl
        self._data: dict[str, Any] = {
            "device_list": None,
            "digital_models": {},
            "scenes": None,
            # device_id -> area_id this integration last assigned to the
            # device. Used to tell an untouched integration area apart from a
            # user-customized one when reconciling areas on reload (see
            # __init__._reconcile_device_area).
            "assigned_areas": {},
        }
        self._loaded = False
        self._dirty = False

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------

    async def async_load(self) -> None:
        """Load the cache from disk into memory (idempotent)."""
        if self._loaded:
            return
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._data = {
                "device_list": stored.get("device_list"),
                "digital_models": stored.get("digital_models") or {},
                "scenes": stored.get("scenes"),
                "assigned_areas": stored.get("assigned_areas") or {},
            }
        self._loaded = True

    async def async_save(self) -> bool:
        """Persist the in-memory cache to disk if it changed.

        Returns ``True`` when a write happened, ``False`` when nothing was
        dirty (so callers can skip needless disk I/O).
        """
        if not self._dirty:
            return False
        await self._store.async_save(self._data)
        self._dirty = False
        return True

    async def async_remove(self) -> None:
        """Delete the cache file (used when the config entry is removed)."""
        await self._store.async_remove()
        self._data = {
            "device_list": None,
            "digital_models": {},
            "scenes": None,
            "assigned_areas": {},
        }
        self._dirty = False

    # ------------------------------------------------------------------
    # Freshness helper
    # ------------------------------------------------------------------

    def _is_fresh(self, entry: dict[str, Any] | None) -> bool:
        """Return True if a cache entry exists and is within the TTL window."""
        if not isinstance(entry, dict):
            return False
        try:
            ts = float(entry.get("ts", 0))
        except (TypeError, ValueError):  # fmt: skip
            return False
        return (time.time() - ts) <= self._ttl

    # ------------------------------------------------------------------
    # Device list
    # ------------------------------------------------------------------

    def get_device_list(
        self, selected_homes: list[str] | None, *, allow_stale: bool = False
    ) -> list[dict] | None:
        """Return the cached device list, or ``None`` on miss.

        The cache is keyed by the set of selected homes; if the user changed
        their home selection (options flow), the cached list no longer applies
        and a miss is reported so the cloud is queried with the new selection.

        With ``allow_stale=True`` the TTL check is skipped: this is meant for
        the offline fallback path where any last-known list beats an empty one.
        The home-selection key is still enforced to avoid returning a list for
        the wrong set of homes.
        """
        entry = self._data.get("device_list")
        if not isinstance(entry, dict):
            return None
        if not allow_stale and not self._is_fresh(entry):
            return None
        if sorted(entry.get("homes") or []) != sorted(selected_homes or []):
            return None
        value = entry.get("value")
        return value if isinstance(value, list) else None

    def set_device_list(self, selected_homes: list[str] | None, device_infos: list[dict]) -> None:
        """Store the device list for the given home selection."""
        self._data["device_list"] = {
            "ts": time.time(),
            "homes": sorted(selected_homes or []),
            "value": device_infos,
        }
        self._dirty = True

    # ------------------------------------------------------------------
    # Digital models (per device)
    # ------------------------------------------------------------------

    def get_digital_model(self, device_id: str, *, allow_stale: bool = False) -> dict | None:
        """Return the cached raw digital model for a device, or ``None``.

        With ``allow_stale=True`` the TTL check is skipped, for the offline
        fallback path where a last-known model beats having no attributes.
        """
        entry = self._data.get("digital_models", {}).get(device_id)
        if not isinstance(entry, dict):
            return None
        if not allow_stale and not self._is_fresh(entry):
            return None
        value = entry.get("value")
        return value if isinstance(value, dict) else None

    def set_digital_model(self, device_id: str, model: dict) -> None:
        """Store the raw digital model for a device."""
        self._data.setdefault("digital_models", {})[device_id] = {
            "ts": time.time(),
            "value": model,
        }
        self._dirty = True

    def prune_digital_models(self, keep_device_ids: set[str]) -> None:
        """Drop cached digital models for devices no longer present.

        Called after refreshing the device list so the cache does not grow
        unbounded with entries for removed devices.
        """
        models = self._data.get("digital_models", {})
        stale = [dev_id for dev_id in models if dev_id not in keep_device_ids]
        for dev_id in stale:
            del models[dev_id]
        if stale:
            self._dirty = True

    # ------------------------------------------------------------------
    # Assigned areas (per device)
    # ------------------------------------------------------------------

    def get_assigned_area(self, device_id: str) -> str | None:
        """Return the area id this integration last assigned to a device.

        Returns ``None`` when no assignment has been recorded for the device
        (the caller then falls back to the name-candidate ownership heuristic).
        """
        area_id = self._data.get("assigned_areas", {}).get(device_id)
        return area_id if isinstance(area_id, str) else None

    def set_assigned_area(self, device_id: str, area_id: str | None) -> None:
        """Record (or clear) the area id this integration assigned to a device.

        Passing ``area_id=None`` removes any stored assignment (used when the
        device is detached under sync mode ``none``); an empty area is then
        treated as free to (re)populate on the next reconcile pass.
        """
        assigned = self._data.setdefault("assigned_areas", {})
        if area_id is None:
            if assigned.pop(device_id, None) is not None:
                self._dirty = True
            return
        if assigned.get(device_id) != area_id:
            assigned[device_id] = area_id
            self._dirty = True

    def prune_assigned_areas(self, keep_device_ids: set[str]) -> None:
        """Drop area-assignment records for devices no longer present.

        Called after refreshing the device list so the map does not grow
        unbounded with entries for removed devices.
        """
        assigned = self._data.get("assigned_areas", {})
        stale = [dev_id for dev_id in assigned if dev_id not in keep_device_ids]
        for dev_id in stale:
            del assigned[dev_id]
        if stale:
            self._dirty = True

    # ------------------------------------------------------------------
    # Scenes (grouped by family)
    # ------------------------------------------------------------------

    def get_scenes(
        self, selected_homes: list[str] | None, *, allow_stale: bool = False
    ) -> dict[str, list[dict]] | None:
        """Return the cached scenes map, or ``None`` on miss.

        Like the device list, the scenes cache is keyed by the selected homes
        so changing the home selection reports a miss and triggers a refresh.
        The returned value is a ``{family_id: [scene, ...]}`` mapping.

        With ``allow_stale=True`` the TTL check is skipped (offline fallback);
        the home-selection key is still enforced.
        """
        entry = self._data.get("scenes")
        if not isinstance(entry, dict):
            return None
        if not allow_stale and not self._is_fresh(entry):
            return None
        if sorted(entry.get("homes") or []) != sorted(selected_homes or []):
            return None
        value = entry.get("value")
        return value if isinstance(value, dict) else None

    def set_scenes(
        self, selected_homes: list[str] | None, scenes_by_family: dict[str, list[dict]]
    ) -> None:
        """Store the scenes map for the given home selection."""
        self._data["scenes"] = {
            "ts": time.time(),
            "homes": sorted(selected_homes or []),
            "value": scenes_by_family,
        }
        self._dirty = True
