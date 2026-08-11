"""Scene platform for the Haier Home integration.

Each Haier cloud scene is exposed as a Home Assistant ``Scene`` entity.
Scenes are stateless — every activation calls the cloud API to trigger
the scene; there is no on/off concept.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SCENE_DEBOUNCE_MS
from .haier.command_debouncer import CommandDebouncer
from .haier.http_client import HaierAPIError

_LOGGER = logging.getLogger(__name__)


class HaierScene(Scene):
    """Represents a Haier smart scene as a Home Assistant Scene entity.

    Following the official Scene entity model, a scene is a stateless entity
    and is **not** backed by a virtual device. Activating it triggers the scene
    through the cloud client without changing local state.

    Because a device-less entity has no device to inherit an area from, the
    scene registers its own area directly in the entity registry: on first add
    it resolves (get-or-create) an area named after the home/family and assigns
    the entity to it. This keeps the entity a plain Scene (no virtual device)
    while still populating the "area" column with the home name. The
    assignment only happens while the entity has no area yet, so a user's
    later manual area choice is never overwritten.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self,
        client: Any,
        area: str,
        family_id: str,
        scene_id: str,
        scene_name: str,
        family_name: str | None = None,
        debouncer: CommandDebouncer | None = None,
    ) -> None:
        """Initialize a HaierScene.

        Args:
            client: API client exposing ``execute_scene(family_id, scene_id)``.
            area: Region/area identifier (e.g. ``"cn"``, ``"sea"``).
            family_id: Cloud family identifier the scene belongs to.
            scene_id: Cloud scene identifier.
            scene_name: Scene name returned by the API; used verbatim as
                the entity name (no translation).
            family_name: Human-readable home/family name. When provided, the
                scene auto-registers to an area with this name on first add.
            debouncer: Shared leading-only debouncer (keyed by scene_id) that
                swallows accidental double-taps. When ``None`` the scene is
                executed directly (used by lightweight tests).
        """
        self._client = client
        self._area = area
        self._family_id = family_id
        self._scene_id = scene_id
        self._family_name = family_name
        self._debouncer = debouncer

        self._attr_unique_id = f"haier_home_{area}_{family_id}_scene_{scene_id}"
        self._attr_name = scene_name

    async def async_added_to_hass(self) -> None:
        """Assign the scene to an area named after its home, if unset.

        Runs after the entity is registered (so ``entity_id`` and
        ``registry_entry`` are available). It only assigns an area when the
        entity currently has none, so re-adds/restarts never clobber a manual
        area the user picked. When the home name is unknown the scene simply
        stays unassigned (empty area), exactly like before.
        """
        await super().async_added_to_hass()

        if not self._family_name:
            return

        # Respect a user's existing choice: only fill in an empty area.
        registry_entry = self.registry_entry
        if registry_entry is not None and registry_entry.area_id is not None:
            return

        area_reg = ar.async_get(self.hass)
        area_entry = area_reg.async_get_area_by_name(self._family_name)
        if area_entry is None:
            area_entry = area_reg.async_create(self._family_name)

        ent_reg = er.async_get(self.hass)
        ent_reg.async_update_entity(self.entity_id, area_id=area_entry.id)

    async def async_activate(self, **kwargs: Any) -> None:
        """Trigger the scene, debounced against accidental double-taps.

        The scene is stateless and replaying it drives real devices again and
        consumes cloud quota, so a leading-only debouncer (keyed by scene_id)
        fires the first activation immediately and swallows repeats inside the
        window. When no debouncer is wired (lightweight tests) the scene is
        executed directly. See docs/command-debounce-design.md.
        """
        if self._debouncer is None:
            await self._execute()
            return
        # Leading edge runs _execute (via the shared send callback) and
        # re-raises its errors here so HA still surfaces the failure toast;
        # swallowed repeats simply return without executing.
        await self._debouncer.async_submit(self._scene_id, {})

    async def _execute(self) -> bool:
        """Call the cloud client to trigger the scene.

        The cloud scene-exec API requires both the family id and scene id, so
        the bound ``family_id`` is passed alongside the ``scene_id``.

        On failure a detailed ERROR log is emitted so the real Haier error
        code and message (retCode/retInfo) are never lost, then the exception
        is re-raised so HA core can surface the ``scene/turn_on`` failure
        toast to the user with the enriched error string.
        """
        try:
            await self._client.execute_scene(self._family_id, self._scene_id)
        except HaierAPIError as exc:
            _LOGGER.error(
                "Failed to execute scene scene_id=%s family_id=%s error_code=%s error_message=%s",
                self._scene_id,
                self._family_id,
                exc.error_code,
                exc.error_message,
                exc_info=True,
            )
            raise
        else:
            _LOGGER.info(
                "Scene scene_id=%s family_id=%s activated successfully",
                self._scene_id,
                self._family_id,
            )
            return True


# ---------------------------------------------------------------------------
# Orphan scene entity cleanup
# ---------------------------------------------------------------------------


def _expected_scene_unique_ids(
    region: str,
    selected_homes: list[str],
    scene_sync_mode: str,
    cached_scenes: dict[str, list[dict]],
) -> set[str]:
    """Compute the set of scene ``unique_id``s that should exist right now.

    Returns an empty set when scene sync is disabled or no home is selected —
    i.e. "no scene entity should exist", which drives full cleanup.
    """
    if scene_sync_mode == "none" or not selected_homes:
        return set()

    expected: set[str] = set()
    for family_id in selected_homes:
        for scene in cached_scenes.get(family_id, []) or []:
            # Real API uses ``sceneId``; the mock client uses ``scene_id``.
            scene_id = scene.get("sceneId") or scene.get("scene_id") or ""
            if scene_id:
                expected.add(f"haier_home_{region}_{family_id}_scene_{scene_id}")
    return expected


def _cleanup_orphan_scenes(
    hass: HomeAssistant,
    entry: ConfigEntry,
    expected_unique_ids: set[str],
) -> None:
    """Remove scene entities of this entry that are no longer expected.

    Covers deselecting a family, switching ``scene_sync`` to ``none`` and
    scenes deleted on the cloud side. Only the ``scene`` domain is touched so
    ``climate`` entities are never affected.
    """
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != Platform.SCENE:
            continue
        if reg_entry.unique_id not in expected_unique_ids:
            _LOGGER.debug(
                "Removing orphan scene entity %s (unique_id=%s)",
                reg_entry.entity_id,
                reg_entry.unique_id,
            )
            registry.async_remove(reg_entry.entity_id)


# ---------------------------------------------------------------------------
# Task 5.3: async_setup_entry — platform entry point
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up scene entities for all selected families.

    Uses cached scene data from config entry to avoid redundant API calls.
    """
    _LOGGER.debug("Setting up scene platform")

    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        _LOGGER.error("No client data found for entry %s", entry.entry_id)
        return

    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    cache = data.get("cache")
    region: str = entry.data.get("region", "cn")
    selected_homes: list[str] = entry.data.get("homes", []) or []
    scene_sync_mode = entry.data.get("scene_sync", "none")

    _LOGGER.debug("Scene sync mode: %s, selected homes: %s", scene_sync_mode, selected_homes)

    # Resolve the family_id → list[scene] map cloud-first, so scenes created
    # or deleted on the app while HA was down are reflected on restart (and the
    # orphan-cleanup below stays accurate). Fallback order when the cloud call
    # fails:
    #   1. local Store cache, stale-tolerant (survives HA service restarts);
    #   2. scenes persisted in the config entry by the config flow (seed) —
    #      covers "went offline right after onboarding" before any cache exists.
    # Freshly fetched scenes are written back to the Store cache.
    # Only meaningful when scene sync is enabled and homes are selected.
    cached_scenes: dict[str, list[dict]] = {}
    if scene_sync_mode != "none" and selected_homes:
        resolved: dict[str, list[dict]] | None = None
        source = "empty"
        try:
            raw = await client.get_scenes(selected_homes)
            resolved = {fid: (raw.get(fid) or []) for fid in selected_homes}
            source = "cloud"
            # Persist the freshly resolved scenes for the next offline restart.
            if cache is not None:
                cache.set_scenes(selected_homes, resolved)
                try:
                    await cache.async_save()
                except Exception:  # pragma: no cover - best-effort persistence
                    _LOGGER.warning("Failed to persist scene cache", exc_info=True)
        except Exception as err:
            _LOGGER.warning("Failed to fetch scenes from cloud: %s", err)
            # Offline fallback: last known cache (stale ok), then config seed.
            if cache is not None:
                resolved = cache.get_scenes(selected_homes, allow_stale=True)
                if resolved is not None:
                    source = "cache"
            if resolved is None:
                entry_scenes = entry.data.get("scenes") or None
                if entry_scenes:
                    resolved = entry_scenes
                    source = "config_entry"
        cached_scenes = resolved or {}
        _LOGGER.debug("Scenes resolved from %s: %d families", source, len(cached_scenes))
    else:
        # Not syncing: retain config-entry scenes only for the cleanup calc
        # below (which yields an empty expected set in this case anyway).
        cached_scenes = entry.data.get("scenes", {}) or {}

    # family_id → family/home name, cached by config_flow from /fam/list.
    # Used to group each family's scenes under a virtual device whose
    # suggested area is the home name. Legacy entries may lack this map.
    family_names: dict[str, str] = entry.data.get("family_names", {}) or {}

    # Compute the entities that should exist now and prune any stale scene
    # entities from the registry. This MUST run before the early returns below
    # so that disabling scene sync (mode=none) or deselecting a family also
    # removes the previously created — now orphaned — scene entities, instead
    # of leaving them marked "unavailable / no longer provided" in HA.
    expected_ids = _expected_scene_unique_ids(
        region, selected_homes, scene_sync_mode, cached_scenes
    )
    _cleanup_orphan_scenes(hass, entry, expected_ids)

    if not selected_homes:
        _LOGGER.debug("No selected homes, skipping scene setup")
        return

    # Scene sync only has two states: "none" (disabled) or sync all scenes.
    # The cloud exposes manual scenes only. Any non-"none" value (including the
    # legacy "all" / "all_manual" options) means "sync all scenes".
    if scene_sync_mode == "none":
        _LOGGER.debug("Scene sync is disabled (mode=none), skipping scene setup")
        return

    entities: list[HaierScene] = []
    # Shared leading-only debouncer for this entry's scenes. Keyed by
    # scene_id, it swallows accidental double-taps (see design doc). The send
    # callback resolves the scene entity by id and runs its _execute (which
    # keeps the per-scene error logging + re-raise). Stored in hass.data so
    # async_unload_entry can cancel its timers.
    scene_by_id: dict[str, HaierScene] = {}

    async def _execute_scene(scene_id: str, _commands: dict[str, Any]) -> bool:
        entity = scene_by_id.get(scene_id)
        if entity is None:
            _LOGGER.warning("Debounced scene %s no longer present; skipping", scene_id)
            return False
        return await entity._execute()  # noqa: SLF001 - same-module helper

    debouncer = CommandDebouncer(hass, SCENE_DEBOUNCE_MS, _execute_scene, trailing=False)
    data["scene_debouncer"] = debouncer

    for family_id in selected_homes:
        scenes = cached_scenes.get(family_id, [])
        _LOGGER.debug("Family %s has %d scenes", family_id, len(scenes))
        for scene in scenes or []:
            # Real API uses ``sceneId``/``sceneName``; the mock client uses
            # ``scene_id``/``scene_name``. Support both so entities are created
            # with a stable, unique scene id regardless of the data source.
            scene_id = scene.get("sceneId") or scene.get("scene_id") or ""
            scene_name = scene.get("sceneName") or scene.get("scene_name") or scene_id
            if not scene_id:
                _LOGGER.warning("Skipping scene without id: %s", scene)
                continue
            _LOGGER.debug("Creating scene entity: %s - %s", scene_id, scene_name)
            entity = HaierScene(
                client=client,
                area=region,
                family_id=family_id,
                scene_id=scene_id,
                scene_name=scene_name,
                family_name=family_names.get(family_id),
                debouncer=debouncer,
            )
            entities.append(entity)
            scene_by_id[scene_id] = entity

    _LOGGER.debug("Adding %d scene entities", len(entities))
    if entities:
        async_add_entities(entities)
