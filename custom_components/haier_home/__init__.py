"""The Haier Home integration.

Integration entry point. Sets up the coordinator with WebSocket connection, triggers
PID extension auto-discovery via the ``extend`` package, and forwards
config entry setup to the climate and scene platforms.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import APP_ID, DEFAULT_LANGUAGE, DEFAULT_REGION, DOMAIN, EVENT_SEND_COMMAND, PLATFORMS
from .device import HaierDevice, create_device_from_api_record, parse_digital_model
from .haier.coordinator import HaierCoordinator
from .haier.http_client import HaierHttpClient
from .haier.oauth2 import HaierOAuth2Implementation
from .haier.storage import HaierDeviceCache
from .haier.utils import validate_entry_data

_LOGGER = logging.getLogger(__name__)

# This integration is configured exclusively through the UI config flow, so it
# has no YAML configuration schema. Declaring config_entry_only satisfies the
# HA requirement that any integration implementing async_setup defines one of
# CONFIG_SCHEMA / PLATFORM_SCHEMA / PLATFORM_SCHEMA_BASE.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def _handle_send_command(event: Event, hass: HomeAssistant) -> None:
    """Route an ``EVENT_SEND_COMMAND`` event to the owning coordinator.

    Args:
        event: Event carrying ``device_id`` and ``commands`` data.
        hass: Home Assistant instance.
    """
    device_id = event.data.get("device_id")
    commands = event.data.get("commands", {})

    _LOGGER.debug("Received send command event: device_id=%s, commands=%s", device_id, commands)

    for _entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
        coordinator = entry_data.get("coordinator")
        if coordinator and device_id in coordinator.devices:
            await coordinator.async_send_command(device_id, commands)
            return

    _LOGGER.warning("No coordinator found for device %s", device_id)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Haier Home component (shared, entry-independent setup).

    Loads the PID extension registry and registers the send-command event
    listener once for the integration.

    Args:
        hass: Home Assistant instance.
        config: The integration's YAML config (unused; entry-based setup).

    Returns:
        ``True`` when setup succeeded.
    """
    hass.data.setdefault(DOMAIN, {})

    from . import extend

    await hass.async_add_executor_job(extend.load_extensions)
    _LOGGER.debug("Loaded extend module for PID auto-discovery")

    # Store the listener unsub function so it can be cancelled in
    # async_unload_entry, preventing duplicate listeners on re-setup.
    unsub = hass.bus.async_listen(
        EVENT_SEND_COMMAND, lambda event: _handle_send_command(event, hass)
    )
    hass.data[DOMAIN]["_event_unsub"] = unsub
    _LOGGER.debug("Registered event listener for %s", EVENT_SEND_COMMAND)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Haier Home account from a config entry.

    Validates entry data, builds the HTTP client and coordinator, gets the
    token/HTTP/WebSocket ready, loads devices (cloud-first with cache
    fallback), forwards platform setup and reconciles device areas.

    Args:
        hass: Home Assistant instance.
        entry: The config entry to set up.

    Returns:
        ``True`` when the entry was set up successfully.

    Raises:
        ConfigEntryAuthFailed: When the token is invalid or refresh failed.
        ConfigEntryNotReady: When non-token config-flow data is missing.
    """
    hass.data.setdefault(DOMAIN, {})

    # Setup is the integration's starting point: validate everything the entry
    # must carry in ONE place (see validate_entry_data). Token problems surface
    # as ValueError → reauth; broken non-token config-flow data surfaces as
    # KeyError → re-configure. No defaulting, no silent limping.
    try:
        validate_entry_data(entry.data)
    except ValueError as err:
        _LOGGER.exception("Stored token is invalid; re-authentication required")
        raise ConfigEntryAuthFailed(str(err)) from err
    except KeyError as err:
        _LOGGER.exception("Config entry data is invalid; re-configure the integration")
        raise ConfigEntryNotReady(str(err)) from err

    # Validation above guarantees these fields exist; extract them directly.
    access_token = entry.data["token"]["access_token"]
    ag_client_id = entry.data["ag_client_id"]
    region = entry.data["region"]
    language = entry.data["language"]
    _LOGGER.debug(
        "Setting up Haier Home account %s (region=%s)",
        entry.data.get("uid", "<unknown>"),
        region,
    )

    # HTTP holds no token of its own; its token_provider is wired to the
    # coordinator's read-only _current_access_token right after the coordinator
    # is built below.
    client = HaierHttpClient(
        hass=hass,
        region=region,
        ag_client_id=ag_client_id,
        language=language,
    )

    devices: dict[str, HaierDevice] = {}
    selected_homes = entry.data.get("homes", [])
    room_sync_mode = entry.data.get("room_sync_mode", "family_and_room")
    _LOGGER.debug(
        "Selected homes count: %d, room_sync_mode: %s",
        len(selected_homes),
        room_sync_mode,
    )

    # --- OAuth token gate ----------------------------------------------------
    # Configure the coordinator's OAuth2 session up front, bound to THIS config
    # entry's own region/ag_client_id, and route every HTTP request through the
    # single refresh gate (the coordinator owns refreshing and writes the
    # refreshed token back to the entry). Every cloud call below (homes /
    # device list / digital models) therefore validates and, if needed,
    # refreshes the token first instead of trusting a possibly-stale token
    # cached in the entry. ``devices`` is passed by reference and filled in
    # below before ``async_start`` is reached.
    coordinator = HaierCoordinator(
        hass=hass,
        region=region,
        devices=devices,
        token=access_token,
        ag_client_id=ag_client_id,
        app_id=APP_ID,
        token_data=entry.data["token"],
        config_entry=entry,
        http_client=client,
    )
    coordinator._configure_oauth(entry)
    # The coordinator is the single token owner and the single refresh gate.
    # HTTP is a pure consumer: it reads the current token via
    # _current_access_token (no refresh, no local copy), exactly like the
    # WebSocket client, so both always send the same token generation.
    # Refreshing is driven only by the coordinator — its background refresh
    # loop (early-expiry) and the auth-failure handler below (HTTP 401/403).
    client.token_provider = coordinator._current_access_token
    # Wire auth rejections (HTTP 401/403) back to the coordinator so it can
    # force-refresh the token and reconnect the WebSocket — this keeps token
    # recovery closed-loop even when the token fails server-side outside any
    # periodic refresh window.
    client.auth_failure_handler = coordinator._handle_auth_failure

    # Dependencies ready BEFORE any cloud call: verify/refresh the token now
    # and bring the HTTP client up. If the token can't be made valid (refresh
    # failed) fail setup loudly and send the user to re-auth instead of limping
    # along on a broken credential.
    if not await coordinator._ensure_dependencies_ready():
        raise ConfigEntryAuthFailed(
            "Haier token is invalid or refresh failed; re-authenticate the integration"
        )

    # Build familyId -> familyName map so devices can be assigned to areas that
    # include the home name. The device list only carries familyId, not the
    # human-readable family name.
    #
    # Seed from the config entry for *all* modes so the area-name candidates
    # (build_area_name_candidates) always include the family-based variants,
    # even when the active mode does not use the family name. Without this a
    # room_only device would have no "<family> <floor> <room>" candidate, so
    # a device previously placed under a family_and_room area could not be
    # recognized as integration-managed on reload and its area would be stuck.
    family_name_map: dict[str, str] = dict(entry.data.get("family_names", {}) or {})
    if room_sync_mode in ("family_and_room", "family_only"):
        try:
            homes_data = await client.get_homes()
            for group in ("createfamilies", "joinfamilies"):
                for family in homes_data.get(group, []) or []:
                    family_id = family.get("familyId")
                    if family_id:
                        family_name_map[family_id] = family.get("familyName", "")
            _LOGGER.debug("Resolved %d family names", len(family_name_map))
        except Exception:
            # Family names are an optional enrichment for suggested_area;
            # log full traceback but let setup continue without them.
            _LOGGER.warning("Failed to fetch family names", exc_info=True)

    # Local persistent cache (survives HA service restarts). Data is fetched
    # cloud-first so restarts pick up devices/scenes added or removed while HA
    # was down; the cache is only a fallback used when the cloud is unreachable.
    cache = HaierDeviceCache(hass, entry.entry_id)
    await cache.async_load()

    # Whether the device list below came from an authoritative cloud fetch (vs a
    # stale-cache fallback). Orphan cleanup must only run when this is True: a
    # transient cloud outage falls back to the cached list, and pruning against
    # that stale list would wrongly delete every device that happens to be
    # absent from the (possibly incomplete) cache.
    device_list_from_cloud = False

    try:
        # --- Phase 1: device list (cloud-first, cache fallback) ---
        # Cache-first would hide devices added while HA was down (a device not
        # in the cached list never gets its digital model fetched), so always
        # ask the cloud first and refresh the cache. Only when the cloud call
        # fails do we fall back to the last known list (stale-tolerant) so a
        # transient outage does not wipe every entity on restart.
        try:
            devices_data = await client.get_devices(selected_homes)
            device_infos = devices_data.get("deviceInfos", [])
            cache.set_device_list(selected_homes, device_infos)
            device_list_from_cloud = True
            _LOGGER.debug("Device list fetched from cloud: %d devices", len(device_infos))
        except Exception as e:
            device_infos = cache.get_device_list(selected_homes, allow_stale=True) or []
            _LOGGER.warning(
                "Failed to fetch device list from cloud (%s); using %d cached devices",
                e,
                len(device_infos),
            )

        # Drop cached digital models for devices no longer in the list.
        _present_device_ids = {r.get("deviceId", r.get("device_id", "")) for r in device_infos}
        cache.prune_digital_models(_present_device_ids)
        # NOTE: assigned_areas is intentionally *not* pruned against the cloud
        # device list here. A device can vanish from the list only temporarily
        # (e.g. moved to an unauthorized family, then back), and HA keeps a
        # tombstone (DeletedDeviceEntry) that preserves its old area_id. If we
        # dropped the assignment record now, then on the device's return HA
        # would restore the stale area while we'd have lost the proof that the
        # area was ours -- leaving the device stuck in its previous area. So the
        # assigned_areas map is pruned later against HA's own device lifecycle
        # (active + deleted devices), see _async_sync_device_areas().

        # --- Phase 2: per-device digital model (cloud-first, cache fallback) ---
        # On restart the device's mode/temperature may have been changed from
        # another app while HA was down, so the local cache cannot be trusted.
        # Always refetch the digital model from the cloud to get the latest
        # attribute states. Only when the cloud/device is network-unreachable
        # do we fall back to the last cached model, and in that case the device
        # is marked offline so the UI signals its state may be stale.
        async def _load_device(
            record: dict,
        ) -> HaierDevice | None:
            """Fetch one device's digital model in parallel and build its entity.

            Each device is fetched independently so a single failure (network,
            auth, malformed response) degrades to the per-device cache fallback
            without aborting the rest of the batch. Returns the created device
            or ``None`` when the record is skipped (not an AC type), so
            :func:`asyncio.gather` never sees a device-level error.
            """
            device_id = record.get("deviceId", record.get("device_id", ""))
            app_type_code = record.get("apptypeCode", record.get("app_type_code", ""))
            _LOGGER.debug("Device record: device_id=%s, app_type_code=%s", device_id, app_type_code)

            device_attributes = None
            network_unreachable = False
            try:
                # Cloud-first: fetch the freshest model and refresh the cache.
                digital_model = await client.get_device_digital_model(device_id)
                cache.set_digital_model(device_id, digital_model)
                _LOGGER.debug("Digital model fetched from cloud for device %s", device_id)
            except (TimeoutError, aiohttp.ClientError) as e:
                # Network cannot reach the cloud: fall back to the last known
                # good cached model (stale-tolerant) and flag the device offline.
                digital_model = cache.get_digital_model(device_id, allow_stale=True)
                network_unreachable = True
                _LOGGER.warning(
                    "Network unreachable for device %s digital model; using cached "
                    "data and marking device offline: %s",
                    device_id,
                    e,
                )
            except Exception as e:
                # Non-network failure (auth/API error, malformed response). Fall
                # back to cache too, but do not force-offline: reachability is
                # not the problem, so keep the device-list online flag.
                digital_model = cache.get_digital_model(device_id, allow_stale=True)
                _LOGGER.warning("Failed to fetch digital model for device %s: %s", device_id, e)

            if digital_model is not None:
                device_attributes = parse_digital_model(digital_model)
                _LOGGER.debug(
                    "Parsed %d attributes for device %s", len(device_attributes), device_id
                )

            family_id = record.get("familyId")
            if not family_id:
                _LOGGER.debug("Skipped device (no familyId): app_type_code=%s", app_type_code)
                return None
            family_name = family_name_map.get(family_id)
            device = create_device_from_api_record(
                record,
                device_attributes,
                room_sync_mode=room_sync_mode,
                family_name=family_name,
            )
            if device is None:
                _LOGGER.debug("Skipped device (not AC type): app_type_code=%s", app_type_code)
                return None
            # Override the device-list online flag only when we had to fall
            # back to cache because the cloud was unreachable.
            if network_unreachable:
                device.set_online(False)
            return device

        # Fetch all digital models concurrently instead of serially, so setup
        # time does not grow linearly with the number of devices.
        loaded_devices: list[HaierDevice | None] = []
        if device_infos:
            loaded_devices = await asyncio.gather(
                *(_load_device(record) for record in device_infos),
                return_exceptions=False,
            )
        for device in loaded_devices:
            if device is not None:
                devices[device.device_id] = device
                _LOGGER.debug("Created device: %s, type=%s", device.device_id, device.device_type)
    except Exception as e:
        _LOGGER.error("Failed to fetch devices: %s", e, exc_info=True)

    # Flush the cache once (no-op when nothing was fetched from the cloud).
    try:
        await cache.async_save()
    except Exception:  # pragma: no cover - cache persistence is best-effort
        _LOGGER.warning("Failed to persist Haier device cache", exc_info=True)

    implementation = HaierOAuth2Implementation(hass, ag_client_id, region)
    config_entry_oauth2_flow.async_register_implementation(hass, DOMAIN, implementation)

    await coordinator.async_start()

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "region": region,
        # token was already validated non-empty by validate_token_structure
        # above, so no fallback: the key is guaranteed present here.
        "token": entry.data["token"],
        "cache": cache,
    }

    # Snapshot which of our devices HA still holds a deletion tombstone for,
    # BEFORE forwarding to platforms: entity creation calls
    # ``device_registry.async_get_or_create``, which restores and pops a
    # matching tombstone, so it must be read first. A device restored from our
    # tombstone is definitively ours (only this integration creates a
    # ``(DOMAIN, device_id)`` identifier), so its stale restored area may be
    # overwritten with the freshly computed ``suggested_area``.
    dev_reg = dr.async_get(hass)
    restored_from_tombstone = _collect_tombstoned_device_ids(dev_reg)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Remove HA devices (and their entities) for cloud-deleted devices. Guarded
    # by device_list_from_cloud so a stale-cache fallback never triggers a wipe.
    if device_list_from_cloud:
        _async_cleanup_orphan_devices(hass, entry, set(devices))

    # DeviceInfo.suggested_area only applies when a device is first created;
    # HA never re-applies it on reload. So after the user changes room_sync_mode
    # the existing devices keep their old area. Actively reconcile now that the
    # devices are registered (platforms create them during setup above).
    await _async_sync_device_areas(hass, entry, devices, cache, restored_from_tombstone)

    return True


def _async_cleanup_orphan_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    expected_device_ids: set[str],
) -> None:
    """Remove HA devices whose cloud device no longer exists.

    Scope: this handles **device-backed** entities only. Every such entity
    inherits :class:`.entity.HaierDeviceEntity`, whose ``device_info`` uses
    ``identifiers={(DOMAIN, device_id)}``. Removing the device-registry entry
    therefore cascades to *all* its entities across *every* platform (climate
    today, plus any future sensor/switch/number/... that follows the same base
    class) with no per-platform code. Adding a new device-backed platform needs
    no change here.

    It does **not** cover device-less entities such as scenes (``device_info is
    None``); those are standalone in the entity registry and each such platform
    must clean up its own orphans (see ``scene._async_cleanup_orphan_scenes``).

    Only call this when the device list came from an authoritative cloud fetch;
    pruning against a stale-cache fallback would delete devices merely missing
    from an incomplete cache.

    Args:
        hass: Home Assistant instance.
        entry: The config entry whose devices are scanned.
        expected_device_ids: Device ids currently present on the cloud.
    """
    dev_reg = dr.async_get(hass)
    expected_identifiers = {(DOMAIN, device_id) for device_id in expected_device_ids}

    for reg_device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if reg_device.identifiers & expected_identifiers:
            continue
        _LOGGER.debug(
            "Removing orphan device %s (identifiers=%s) no longer present on cloud",
            reg_device.id,
            reg_device.identifiers,
        )
        dev_reg.async_remove_device(reg_device.id)


def _collect_tombstoned_device_ids(dev_reg: dr.DeviceRegistry) -> set[str]:
    """Return device_ids this integration still has a deletion tombstone for.

    A tombstone carrying a ``(DOMAIN, device_id)`` identifier can only belong to
    a device this integration created, so it is proof of ownership. Must be
    called before platforms create entities, since ``async_get_or_create`` pops
    the matching tombstone on restore.

    Args:
        dev_reg: The device registry to scan.

    Returns:
        The set of owned device ids with a pending tombstone; empty on any
        registry-shape surprise (older core / test double).
    """
    deleted_devices = getattr(dev_reg, "deleted_devices", None)
    if deleted_devices is None:
        return set()
    ids: set[str] = set()
    try:
        for del_device in deleted_devices.values():
            ids.update(value for domain, value in del_device.identifiers if domain == DOMAIN)
    except Exception:
        _LOGGER.debug("Could not enumerate deletion tombstones", exc_info=True)
        return set()
    return ids


async def _async_sync_device_areas(
    hass: HomeAssistant,
    entry: ConfigEntry,
    devices: dict[str, HaierDevice],
    cache: HaierDeviceCache,
    restored_from_tombstone: set[str] | None = None,
) -> None:
    """Reconcile registered device areas with the current room_sync_mode.

    ``DeviceInfo.suggested_area`` is a creation-only hint, so changing the room
    sync mode and reloading leaves existing devices in their previous area.
    This routine moves each integration-managed device to the area for the mode
    now in effect.

    Ownership guard: a device is treated as integration-managed only when its
    current area is empty, matches the area id this integration last assigned
    (persisted in ``cache``), or -- when no assignment was recorded -- its
    current area name is one this integration could have generated
    (``device.managed_area_names``). A user-picked custom area is none of these
    and is left untouched.

    Each device's target is ``device.suggested_area`` (``None`` for mode
    ``none``, in which case an owned area is detached). Assignments made here
    are persisted back to ``cache``.

    Args:
        hass: Home Assistant instance.
        entry: The config entry being reconciled.
        devices: The devices loaded for this entry.
        cache: Persistent cache holding per-device area assignments.
        restored_from_tombstone: Device ids HA restored from our tombstone,
            whose stale restored area may be overwritten with the target.
    """
    dev_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)
    restored_from_tombstone = restored_from_tombstone or set()

    for device in devices.values():
        try:
            _reconcile_device_area(
                dev_reg,
                area_reg,
                device,
                cache,
                restored=device.device_id in restored_from_tombstone,
            )
        except Exception:
            # Isolate failures per device: a bad/duplicate/invalid area name or
            # a registry rejection for one device must not abort setup or skip
            # reconciliation for the remaining devices. This is single-threaded
            # (runs in the event loop), so this is fault isolation, not a lock.
            _LOGGER.exception(
                "Failed to reconcile area for device %s; skipping it",
                device.device_id,
            )

    # Prune stale area-assignment records against HA's own device lifecycle
    # (active devices + deletion tombstones) rather than the transient cloud
    # list. A device merely moved out of the selected/authorized homes is gone
    # from the cloud list but still lives in HA as a DeletedDeviceEntry that
    # keeps its old area_id; keeping our assignment record for it is what lets a
    # later return be recognized as integration-owned and moved to its new area.
    # Only once HA itself purges the tombstone (after ORPHANED_DEVICE_KEEP) do
    # we drop the record, so the map cannot grow unbounded.
    _prune_assigned_areas_against_ha(dev_reg, entry, cache)

    # Persist any area assignments recorded during reconciliation so the next
    # reload can distinguish an untouched device from a user-moved one.
    try:
        await cache.async_save()
    except Exception:  # pragma: no cover - cache persistence is best-effort
        _LOGGER.warning("Failed to persist Haier device area assignments", exc_info=True)


def _prune_assigned_areas_against_ha(
    dev_reg: dr.DeviceRegistry,
    entry: ConfigEntry,
    cache: HaierDeviceCache,
) -> None:
    """Drop assigned-area records for devices HA no longer knows about.

    "Knows about" spans both active device-registry entries and deletion
    tombstones (``DeletedDeviceEntry``) for this config entry, since a tombstone
    still holds the device's old ``area_id`` and can restore it if the device
    returns. The record must live exactly as long as that tombstone.

    If the registry does not expose deletion tombstones (older HA, or a
    stripped-down test double), pruning is skipped entirely: never dropping a
    record is safe (at worst a tiny, bounded leak), whereas dropping one HA can
    still restore would leave the device stuck in its old area.

    Args:
        dev_reg: The device registry.
        entry: The config entry whose assignment records are pruned.
        cache: Persistent cache holding the assignment records.
    """
    deleted_devices = getattr(dev_reg, "deleted_devices", None)
    if deleted_devices is None:
        return

    known_ids: set[str] = set()
    try:
        for reg_device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            known_ids.update(value for domain, value in reg_device.identifiers if domain == DOMAIN)
        for del_device in deleted_devices.values():
            if not _tombstone_belongs_to_entry(del_device, entry.entry_id):
                continue
            known_ids.update(value for domain, value in del_device.identifiers if domain == DOMAIN)
    except Exception:
        # Any registry-shape surprise: skip pruning rather than risk dropping a
        # record HA could still restore.
        _LOGGER.debug("Skipping assigned_areas prune; registry not enumerable", exc_info=True)
        return

    cache.prune_assigned_areas(known_ids)


# Sentinel distinguishing "attribute absent" from "attribute present but None".
_UNSET = object()


def _tombstone_belongs_to_entry(del_device: object, entry_id: str) -> bool:
    """Return True if a deletion tombstone belongs to this config entry.

    HA core versions model the owning entry differently on
    ``DeletedDeviceEntry``: newer core stores a singular ``config_entry_id``
    (``None`` once the entry itself is removed), while other builds store a
    ``config_entries`` set. Support both shapes.

    When the tombstone exposes *neither* attribute (an unknown/legacy shape),
    return True: keeping the assigned-area record is the safe default. An
    explicit, non-matching association returns False.

    Args:
        del_device: The deletion tombstone to inspect.
        entry_id: The config entry id to match against.

    Returns:
        ``True`` if the tombstone belongs to this entry or its shape is unknown.
    """
    has_shape = False

    single = getattr(del_device, "config_entry_id", _UNSET)
    if single is not _UNSET:
        has_shape = True
        if single == entry_id:
            return True

    multi = getattr(del_device, "config_entries", _UNSET)
    if multi is not _UNSET:
        has_shape = True
        if multi and entry_id in multi:
            return True

    return not has_shape


def _integration_owns_area(
    device: HaierDevice,
    cache: HaierDeviceCache,
    current_area_id: str,
    current_area_name: str | None,
) -> bool:
    """Return True if the device's current area is one this integration set.

    Prefers the persisted last-assigned area id (an exact match that survives
    the user renaming the area and follows cloud-side transfers). Falls back to
    the name-candidate heuristic only when no assignment was recorded.

    Args:
        device: The device being checked.
        cache: Persistent cache holding the last-assigned area id.
        current_area_id: The device's current area id.
        current_area_name: The device's current area name, if any.

    Returns:
        ``True`` when the current area is integration-owned.
    """
    last_assigned_id = cache.get_assigned_area(device.device_id)
    if last_assigned_id is not None:
        return current_area_id == last_assigned_id
    return current_area_name in set(device.managed_area_names)


def _reconcile_device_area(
    dev_reg: dr.DeviceRegistry,
    area_reg: ar.AreaRegistry,
    device: HaierDevice,
    cache: HaierDeviceCache,
    restored: bool = False,
) -> None:
    """Move a single integration-managed device to its current-mode area.

    Ownership is decided by :func:`_integration_owns_area`. After every
    (re)assignment the resulting area id is persisted to ``cache`` so the next
    pass can tell an untouched device from a user-moved one.

    A device restored from our own tombstone is definitively ours, and HA
    restores it into its stale old ``area_id`` while ignoring the creation-time
    ``suggested_area``; when ``restored`` is set, the ownership guard is
    bypassed and the freshly computed ``suggested_area`` is adopted.

    Args:
        dev_reg: The device registry.
        area_reg: The area registry.
        device: The device to reconcile.
        cache: Persistent cache for area assignments.
        restored: ``True`` when HA restored this device from our tombstone.

    Raises:
        Exception: Whatever the device/area registries raise; the caller
            isolates failures so one device cannot abort the whole pass.
    """
    reg_device = dev_reg.async_get_device(identifiers={(DOMAIN, device.device_id)})
    if reg_device is None:
        return

    # Resolve the current area's id and human-readable name, if any.
    current_area_id = reg_device.area_id
    current_area_name: str | None = None
    if current_area_id is not None:
        current_area = area_reg.async_get_area(current_area_id)
        current_area_name = current_area.name if current_area is not None else None

    # Ownership guard: skip devices sitting in a user-customized area. An empty
    # area (current_area_id is None) is always free for us to populate. A device
    # restored from our own tombstone bypasses the guard: it is provably ours,
    # so its stale restored area may be overwritten with the current target.
    if (
        current_area_id is not None
        and not restored
        and not _integration_owns_area(device, cache, current_area_id, current_area_name)
    ):
        _LOGGER.debug(
            "Device %s area %r is user-customized; leaving it unchanged",
            device.device_id,
            current_area_name,
        )
        return

    target_area_name = device.suggested_area

    if target_area_name is None:
        # Mode "none": detach the device from any area we own and forget the
        # assignment (an empty area is treated as free on the next pass).
        if current_area_id is not None:
            dev_reg.async_update_device(reg_device.id, area_id=None)
            _LOGGER.debug("Detached device %s from managed area", device.device_id)
        cache.set_assigned_area(device.device_id, None)
        return

    if current_area_name == target_area_name:
        # Already in the right area. Still record the assignment so a later
        # user move is detected precisely -- important on the first pass after
        # upgrade, when the device matched via the name heuristic and has no
        # persisted id yet.
        if current_area_id is not None:
            cache.set_assigned_area(device.device_id, current_area_id)
        return

    area_entry = area_reg.async_get_area_by_name(target_area_name)
    if area_entry is None:
        area_entry = area_reg.async_create(target_area_name)
    dev_reg.async_update_device(reg_device.id, area_id=area_entry.id)
    cache.set_assigned_area(device.device_id, area_entry.id)
    _LOGGER.debug(
        "Moved device %s to area %r (was %r)",
        device.device_id,
        target_area_name,
        current_area_name,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Stops the coordinator, cancels debouncer timers, unloads platforms, and
    removes the shared event listener when the last entry is unloaded.

    Args:
        hass: Home Assistant instance.
        entry: The config entry to unload.

    Returns:
        ``True`` when all platforms unloaded successfully.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data:
        coordinator = entry_data.get("coordinator")
        if coordinator:
            await coordinator.async_stop()
        # Cancel the scene platform's leading-only debouncer timers so their
        # callbacks never fire against a torn-down entry.
        scene_debouncer = entry_data.get("scene_debouncer")
        if scene_debouncer:
            scene_debouncer.async_cancel()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Cancel the event bus listener registered in async_setup when the
    # last config entry is removed, preventing duplicate registrations
    # if the integration is reconfigured later.
    # After popping the current entry, the only remaining key under
    # hass.data[DOMAIN] should be the internal "_event_unsub".
    domain_data = hass.data.get(DOMAIN)
    if domain_data is not None and list(domain_data) == ["_event_unsub"]:
        unsub = domain_data.pop("_event_unsub")
        unsub()
        _LOGGER.debug("Unregistered event listener for %s", EVENT_SEND_COMMAND)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up persistent data when the config entry is removed.

    Deletes the local device cache file and calls the Haier logout API to
    invalidate the token server-side. Both steps are best-effort: failures are
    logged but do not abort the removal.

    Args:
        hass: Home Assistant instance.
        entry: The config entry being removed.
    """
    entry_data = getattr(entry, "data", {}) or {}
    token_data = entry_data.get("token", {}) or {}
    access_token = token_data.get("access_token", "")
    if access_token:
        region = entry_data.get("region", DEFAULT_REGION)
        ag_client_id = entry_data.get("ag_client_id", "")
        language = entry_data.get("language", DEFAULT_LANGUAGE)
        # No coordinator here (the entry is being removed), so this one-shot
        # client reads the token via a provider that returns the entry's own
        # static token. The entry is settled during removal, so it is a stable
        # source. HTTP itself never holds a token — the provider is its only
        # way to obtain one.
        client = HaierHttpClient(
            hass=hass,
            region=region,
            ag_client_id=ag_client_id,
            language=language,
            token_provider=lambda: access_token,
        )
        try:
            await client.logout()
            _LOGGER.debug("Successfully called logout on entry removal")
        except Exception:  # pragma: no cover - best-effort cleanup
            _LOGGER.warning("Failed to call logout on entry removal", exc_info=True)

    try:
        await HaierDeviceCache(hass, entry.entry_id).async_remove()
    except Exception:  # pragma: no cover - best-effort cleanup
        _LOGGER.warning("Failed to remove Haier device cache", exc_info=True)
