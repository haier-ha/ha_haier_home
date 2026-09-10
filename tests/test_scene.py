"""Tests for the Scene platform (HaierScene).

Replaces the previous ``test_button.py``. Verifies that
``HaierScene.async_activate`` correctly delegates to
``client.execute_scene`` with the bound ``family_id`` and ``scene_id``,
and that the entity exposes the unique_id and name defined in the spec
(Requirement 4 — 场景模块).

Scenes follow the official Home Assistant Scene entity model: they are
stateless entities and are not backed by a virtual device.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haier_home.const import DOMAIN
from custom_components.haier_home.haier.http_client import HaierAPIError
from custom_components.haier_home.scene import HaierScene
from tests.mock_data import MockClient


def _make_scene(
    client,
    *,
    area: str = "cn",
    family_id: str = "mock_family_001",
    scene_id: str = "scene_001",
    scene_name: str = "回家模式",
) -> HaierScene:
    """Build a HaierScene with sensible defaults for testing."""
    return HaierScene(
        client=client,
        area=area,
        family_id=family_id,
        scene_id=scene_id,
        scene_name=scene_name,
    )


class TestHaierSceneActivation:
    """async_activate must invoke client.execute_scene(family_id, scene_id)."""

    @pytest.mark.asyncio
    async def test_async_activate_invokes_execute_scene(self):
        """Validates: Requirements 4.4."""
        client = MockClient()
        client.execute_scene = AsyncMock()
        scene = _make_scene(client, family_id="family_001", scene_id="scene_001")

        await scene.async_activate()

        client.execute_scene.assert_awaited_once_with("family_001", "scene_001")

    @pytest.mark.asyncio
    async def test_async_activate_passes_correct_scene_id(self):
        """Each entity uses its own bound family_id/scene_id, not a shared one."""
        client = MockClient()
        client.execute_scene = AsyncMock()
        scene_a = _make_scene(client, family_id="family_001", scene_id="scene_001")
        scene_b = _make_scene(client, family_id="family_002", scene_id="scene_002")

        await scene_a.async_activate()
        await scene_b.async_activate()

        assert client.execute_scene.await_count == 2
        called_args = [call.args for call in client.execute_scene.await_args_list]
        assert called_args == [("family_001", "scene_001"), ("family_002", "scene_002")]

    @pytest.mark.asyncio
    async def test_async_activate_ignores_extra_kwargs(self):
        """HA may pass extra kwargs; only family_id/scene_id should reach the client."""
        client = MockClient()
        client.execute_scene = AsyncMock()
        scene = _make_scene(client, family_id="family_001", scene_id="scene_001")

        await scene.async_activate(transition=5, extra="ignored")

        client.execute_scene.assert_awaited_once_with("family_001", "scene_001")


class TestHaierSceneIdentity:
    """Verify unique_id and entity name, and that scenes have no device."""

    def test_unique_id_format(self):
        """Validates: Requirements 4.2."""
        scene = _make_scene(
            MockClient(),
            area="cn",
            family_id="mock_family_001",
            scene_id="scene_001",
        )
        assert scene.unique_id == "haier_home_cn_mock_family_001_scene_scene_001"

    def test_unique_id_uses_sea_region(self):
        """Region is propagated into the unique_id prefix."""
        scene = _make_scene(
            MockClient(),
            area="sea",
            family_id="fam_42",
            scene_id="s_42",
        )
        assert scene.unique_id == "haier_home_sea_fam_42_scene_s_42"

    def test_entity_name_uses_scene_name_verbatim(self):
        """Validates: Requirements 4.3."""
        scene = _make_scene(MockClient(), scene_name="回家模式")
        assert scene.name == "回家模式"

    def test_scene_has_no_device(self):
        """Official Scene entities are device-less; device_info must be None.

        This keeps scenes out of the onboarding "Name and assign" dialog,
        which lists devices belonging to the config entry.
        """
        scene = _make_scene(
            MockClient(),
            area="cn",
            family_id="mock_family_001",
        )
        assert scene.device_info is None


class TestHaierSceneWithMockClient:
    """End-to-end check using the real MockClient (no AsyncMock).

    This protects against API-shape drift between MockClient and HaierScene.
    """

    @pytest.mark.asyncio
    async def test_activate_with_real_mock_client_does_not_raise(self):
        """The MockClient.execute_scene contract is respected."""
        client = MockClient()
        scene = _make_scene(client, scene_id="scene_001")
        # Should complete without exception — MockClient logs the execution.
        await scene.async_activate()


class TestSceneSetupFamilyNaming:
    """async_setup_entry creates stateless, device-less Scene entities.

    Scene objects from the API carry only ``sceneId`` / ``sceneName``; each
    becomes an official Scene entity with a stable unique_id and a verbatim
    name, with no backing device.
    """

    @staticmethod
    def _make_entry(data: dict) -> MockConfigEntry:
        return MockConfigEntry(domain=DOMAIN, entry_id="entry_1", data=data)

    @staticmethod
    def _patch_er_empty(monkeypatch, scene_mod) -> None:
        """Stub the entity-registry lookups with an empty registry.

        ``async_setup_entry`` prunes orphan scene entities (via
        ``er.async_get`` / ``er.async_entries_for_config_entry``) before
        creating new ones. These tests only assert the create-side behavior,
        so an empty registry keeps the cleanup path a no-op while still
        exercising the real ``HomeAssistant`` ``hass`` fixture.
        """
        registry = _FakeRegistry([])
        fake_er = SimpleNamespace(
            async_get=lambda hass: registry,
            async_entries_for_config_entry=lambda reg, entry_id: [],
        )
        monkeypatch.setattr(scene_mod, "er", fake_er)

    @pytest.mark.asyncio
    async def test_setup_creates_scene_entities_without_device(
        self, hass: HomeAssistant, monkeypatch
    ):
        """Scenes are created from cached sceneId/sceneName with no device."""
        from custom_components.haier_home import scene as scene_mod

        family_id = "853265552183000000"
        entry = self._make_entry(
            {
                "region": "cn",
                "homes": [family_id],
                "scene_sync": "all_manual",
                # Real API field shape: sceneId/sceneName, no familyName.
                "scenes": {
                    family_id: [
                        {"sceneId": "s1", "sceneName": "回家"},
                        {"sceneId": "s2", "sceneName": "离家"},
                    ]
                },
                # Cached from /fam/list by config_flow (reusing all_families).
                "family_names": {family_id: "我的家"},
            }
        )
        hass.data[DOMAIN] = {entry.entry_id: {"client": MockClient()}}
        self._patch_er_empty(monkeypatch, scene_mod)

        captured: list = []
        await scene_mod.async_setup_entry(hass, entry, cast(AddEntitiesCallback, captured.extend))

        assert len(captured) == 2
        # Scenes stay plain, device-less official Scene entities; the area is
        # assigned via the entity registry in async_added_to_hass, not a device.
        assert all(e.device_info is None for e in captured)
        # The resolved home name is carried for later area registration.
        assert all(e._family_name == "我的家" for e in captured)
        # Scene ids come from sceneId; entity names from sceneName.
        assert {e.unique_id for e in captured} == {
            f"haier_home_cn_{family_id}_scene_s1",
            f"haier_home_cn_{family_id}_scene_s2",
        }
        assert {e.name for e in captured} == {"回家", "离家"}

    @pytest.mark.asyncio
    async def test_setup_creates_scene_without_family_names_cache(
        self, hass: HomeAssistant, monkeypatch
    ):
        """Legacy entries without family_names still create scene entities."""
        from custom_components.haier_home import scene as scene_mod

        family_id = "fam_legacy"
        entry = self._make_entry(
            {
                "region": "cn",
                "homes": [family_id],
                "scene_sync": "all_manual",
                "scenes": {family_id: [{"sceneId": "s1", "sceneName": "回家"}]},
                # No "family_names" key (pre-feature entry).
            }
        )
        hass.data[DOMAIN] = {entry.entry_id: {"client": MockClient()}}
        self._patch_er_empty(monkeypatch, scene_mod)

        captured: list = []
        await scene_mod.async_setup_entry(hass, entry, cast(AddEntitiesCallback, captured.extend))

        assert len(captured) == 1
        assert captured[0].device_info is None
        assert captured[0].unique_id == f"haier_home_cn_{family_id}_scene_s1"
        assert captured[0].name == "回家"


class TestHaierSceneActivationErrorHandling:
    """When execute_scene raises HaierAPIError:
    (a) the exception must still propagate so HA core reports the service failure;
    (b) a detailed ERROR log must be emitted with family_id, scene_id, and
        the real error_code/error_message.

    Previously the exception bubbled up silently (no log), and the exception
    itself dropped error_code/error_message on the floor, which made the
    scene/turn_on failure toast completely undebuggable.
    """

    @pytest.mark.asyncio
    async def test_activate_reraises_haier_api_error(self):
        """Exception must propagate — HA core needs it for the service toast."""
        client = MockClient()
        client.execute_scene = AsyncMock(
            side_effect=HaierAPIError(error_code="E0002", error_message="场景不存在")
        )
        scene = _make_scene(client, family_id="family_001", scene_id="scene_001")

        with pytest.raises(HaierAPIError) as exc_info:
            await scene.async_activate()

        # Exception itself should carry the real details in its string now.
        exc_text = str(exc_info.value)
        assert "E0002" in exc_text, f"error_code lost in reraised exc: {exc_text!r}"
        assert "场景不存在" in exc_text, f"error_message lost: {exc_text!r}"

    @pytest.mark.asyncio
    async def test_activate_logs_detailed_error_on_failure(self, caplog):
        """caplog must contain an ERROR record with all context fields."""
        import logging

        client = MockClient()
        client.execute_scene = AsyncMock(
            side_effect=HaierAPIError(error_code="B0001", error_message="令牌过期")
        )
        scene = _make_scene(client, family_id="fam_X", scene_id="scn_Y")
        scene._attr_name = "我的场景"

        caplog.set_level(logging.ERROR, logger="custom_components.haier_home.scene")
        with pytest.raises(HaierAPIError):
            await scene.async_activate()

        log_text = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "custom_components.haier_home.scene"
            and record.levelno >= logging.ERROR
        )
        assert "fam_X" in log_text, f"family_id missing from error log: {log_text!r}"
        assert "scn_Y" in log_text, f"scene_id missing from error log: {log_text!r}"
        assert "B0001" in log_text, f"error_code missing from error log: {log_text!r}"
        assert "令牌过期" in log_text, f"error_message missing from error log: {log_text!r}"


class TestHaierSceneActivationSuccessBehavior:
    """When execute_scene succeeds, ``async_activate`` must:

    1. Emit an ``INFO`` log line carrying the ``scene_id`` and ``family_id``
       so operators can trace successful activations in the HA log stream.
    2. Never raise (the scene activation has already been accepted by the
       cloud API and the caller sees a clean success).

    On the failure path, ``HaierAPIError`` is re-raised unmodified so HA
    core surfaces the enriched error string on the ``scene/turn_on`` toast.
    """

    @pytest.mark.asyncio
    async def test_success_emits_info_log(self, caplog):
        """On success the scene logger records an INFO entry with the
        scene id and family id (both fields are required for diagnostics).

        The scene activation function itself must not raise.
        """
        import logging

        client = MockClient()
        client.execute_scene = AsyncMock(return_value=None)
        scene = _make_scene(client, area="cn", family_id="fam_C", scene_id="scn_C")
        scene._attr_name = "Sleep Mode"
        scene.entity_id = "scene.test"

        caplog.set_level(logging.INFO, logger="custom_components.haier_home.scene")
        # Must succeed with no exception at all.
        await scene.async_activate()

        joined = "\n".join(
            r.getMessage()
            for r in caplog.records
            if r.name == "custom_components.haier_home.scene" and r.levelno == logging.INFO
        )
        # The INFO log must identify the scene by scene_id + family_id.
        assert "scn_C" in joined, f"scene_id missing from INFO log: {joined!r}"
        assert "fam_C" in joined, f"family_id missing from INFO log: {joined!r}"
        # Must state success / activation outcome.
        lowered = joined.lower()
        assert "activated" in lowered or "succeeded" in lowered or "success" in lowered, (
            f"INFO log does not mention successful activation: {joined!r}"
        )

    @pytest.mark.asyncio
    async def test_failure_reraises_haier_api_error(self):
        """Regression: HaierAPIError must propagate out unchanged so HA core
        sees the real retCode/retInfo and never silently swallows failures.

        As an additional guard against accidental side-effects on the
        failure path (e.g. leftover success-notification code), the test
        asserts no hass.service.async_call invocations happen.
        """
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import MagicMock as _MagicMock

        client = MockClient()
        client.execute_scene = _AsyncMock(
            side_effect=HaierAPIError(error_code="E9999", error_message="Nope")
        )
        scene = _make_scene(client, family_id="fam_FAIL", scene_id="scn_FAIL")
        scene.entity_id = "scene.dead"
        # Provide a real-ish hass so any stray side-effect call becomes a
        # verifiable async_call record, not AttributeError.
        hass = _MagicMock()
        hass.services.async_call = _AsyncMock()
        hass.data = {}
        scene.hass = hass

        with pytest.raises(HaierAPIError) as excinfo:
            await scene.async_activate()

        # Reraised error must preserve the real Haier payload.
        assert excinfo.value.error_code == "E9999"
        assert excinfo.value.error_message == "Nope"
        # Failure path must NOT fire success notification / logbook writes.
        assert not hass.services.async_call.called, (
            "Failure path must NOT invoke hass.services.async_call at all"
        )


class TestExpectedSceneUniqueIds:
    """_expected_scene_unique_ids drives which entities should exist."""

    def test_returns_ids_for_selected_families_when_sync_enabled(self):
        from custom_components.haier_home import scene as scene_mod

        ids = scene_mod._expected_scene_unique_ids(
            region="cn",
            selected_homes=["famA"],
            scene_sync_mode="all_manual",
            cached_scenes={"famA": [{"sceneId": "s1"}, {"sceneId": "s2"}]},
        )
        assert ids == {
            "haier_home_cn_famA_scene_s1",
            "haier_home_cn_famA_scene_s2",
        }

    def test_empty_when_scene_sync_none(self):
        """Disabling scene sync means no scene entity should exist."""
        from custom_components.haier_home import scene as scene_mod

        ids = scene_mod._expected_scene_unique_ids(
            region="cn",
            selected_homes=["famA"],
            scene_sync_mode="none",
            cached_scenes={"famA": [{"sceneId": "s1"}]},
        )
        assert ids == set()

    def test_empty_when_no_selected_homes(self):
        from custom_components.haier_home import scene as scene_mod

        ids = scene_mod._expected_scene_unique_ids(
            region="cn",
            selected_homes=[],
            scene_sync_mode="all_manual",
            cached_scenes={"famA": [{"sceneId": "s1"}]},
        )
        assert ids == set()

    def test_excludes_deselected_families(self):
        """Scenes of families not in selected_homes are not expected."""
        from custom_components.haier_home import scene as scene_mod

        ids = scene_mod._expected_scene_unique_ids(
            region="cn",
            selected_homes=["famA"],
            scene_sync_mode="all_manual",
            cached_scenes={
                "famA": [{"sceneId": "s1"}],
                "famB": [{"sceneId": "s2"}],  # not selected
            },
        )
        assert ids == {"haier_home_cn_famA_scene_s1"}

    def test_supports_mock_client_field_names(self):
        """Mock client uses scene_id instead of sceneId."""
        from custom_components.haier_home import scene as scene_mod

        ids = scene_mod._expected_scene_unique_ids(
            region="cn",
            selected_homes=["famA"],
            scene_sync_mode="all_manual",
            cached_scenes={"famA": [{"scene_id": "s1"}]},
        )
        assert ids == {"haier_home_cn_famA_scene_s1"}


class _FakeRegEntry:
    def __init__(self, entity_id, unique_id, domain):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.domain = domain


class _FakeRegistry:
    def __init__(self, entries):
        self._entries = entries
        self.removed: list[str] = []

    def async_remove(self, entity_id):
        self.removed.append(entity_id)


class TestCleanupOrphanScenes:
    """_cleanup_orphan_scenes prunes stale scene entities only."""

    @staticmethod
    def _patch_registry(monkeypatch, entries):
        """Wire scene_mod.er / scene_mod.Platform to a fake registry."""
        from custom_components.haier_home import scene as scene_mod

        registry = _FakeRegistry(entries)
        fake_er = SimpleNamespace(
            async_get=lambda hass: registry,
            async_entries_for_config_entry=lambda reg, entry_id: list(entries),
        )
        monkeypatch.setattr(scene_mod, "er", fake_er)
        monkeypatch.setattr(scene_mod, "Platform", SimpleNamespace(SCENE="scene"))
        return scene_mod, registry

    def test_removes_only_unexpected_scene_entities(self, monkeypatch):
        entries = [
            _FakeRegEntry("scene.keep", "uid_keep", "scene"),
            _FakeRegEntry("scene.orphan", "uid_orphan", "scene"),
        ]
        scene_mod, registry = self._patch_registry(monkeypatch, entries)
        entry = SimpleNamespace(entry_id="e1")

        scene_mod._cleanup_orphan_scenes(
            hass=SimpleNamespace(), entry=entry, expected_unique_ids={"uid_keep"}
        )

        assert registry.removed == ["scene.orphan"]

    def test_removes_all_when_expected_empty(self, monkeypatch):
        """scene_sync=none -> expected empty -> every scene entity removed."""
        entries = [
            _FakeRegEntry("scene.a", "uid_a", "scene"),
            _FakeRegEntry("scene.b", "uid_b", "scene"),
        ]
        scene_mod, registry = self._patch_registry(monkeypatch, entries)
        entry = SimpleNamespace(entry_id="e1")

        scene_mod._cleanup_orphan_scenes(
            hass=SimpleNamespace(), entry=entry, expected_unique_ids=set()
        )

        assert set(registry.removed) == {"scene.a", "scene.b"}

    def test_never_touches_non_scene_entities(self, monkeypatch):
        """climate entities must never be removed, even if not in expected."""
        entries = [
            _FakeRegEntry("climate.ac", "uid_climate", "climate"),
            _FakeRegEntry("scene.orphan", "uid_orphan", "scene"),
        ]
        scene_mod, registry = self._patch_registry(monkeypatch, entries)
        entry = SimpleNamespace(entry_id="e1")

        scene_mod._cleanup_orphan_scenes(
            hass=SimpleNamespace(), entry=entry, expected_unique_ids=set()
        )

        assert registry.removed == ["scene.orphan"]


class TestSceneAreaAutoRegistration:
    """async_added_to_hass assigns the scene to an area named after the home.

    The scene stays a plain, device-less Scene entity; the area is written
    directly into the entity registry. The assignment is skipped when the
    entity already has an area (user override) or when the home name is
    unknown.
    """

    def _make_scene_in_hass(self, *, family_name, area_id):
        client = MockClient()
        scene = HaierScene(
            client=client,
            area="cn",
            family_id="f1",
            scene_id="s1",
            scene_name="回家",
            family_name=family_name,
        )
        scene.hass = SimpleNamespace()
        scene.entity_id = "scene.hui_jia"
        scene.registry_entry = SimpleNamespace(area_id=area_id)
        return scene

    @pytest.mark.asyncio
    async def test_creates_and_assigns_area_when_unset(self):
        from unittest.mock import MagicMock, patch

        scene = self._make_scene_in_hass(family_name="我的家", area_id=None)

        area_reg = MagicMock()
        area_reg.async_get_area_by_name.return_value = None
        area_reg.async_create.return_value = SimpleNamespace(id="area_home")
        ent_reg = MagicMock()

        with (
            patch("custom_components.haier_home.scene.ar.async_get", return_value=area_reg),
            patch("custom_components.haier_home.scene.er.async_get", return_value=ent_reg),
        ):
            await scene.async_added_to_hass()

        area_reg.async_get_area_by_name.assert_called_once_with("我的家")
        area_reg.async_create.assert_called_once_with("我的家")
        ent_reg.async_update_entity.assert_called_once_with("scene.hui_jia", area_id="area_home")

    @pytest.mark.asyncio
    async def test_reuses_existing_area(self):
        from unittest.mock import MagicMock, patch

        scene = self._make_scene_in_hass(family_name="我的家", area_id=None)

        area_reg = MagicMock()
        area_reg.async_get_area_by_name.return_value = SimpleNamespace(id="existing")
        ent_reg = MagicMock()

        with (
            patch("custom_components.haier_home.scene.ar.async_get", return_value=area_reg),
            patch("custom_components.haier_home.scene.er.async_get", return_value=ent_reg),
        ):
            await scene.async_added_to_hass()

        area_reg.async_create.assert_not_called()
        ent_reg.async_update_entity.assert_called_once_with("scene.hui_jia", area_id="existing")

    @pytest.mark.asyncio
    async def test_respects_user_assigned_area(self):
        """When the entity already has an area, do not overwrite it."""
        from unittest.mock import MagicMock, patch

        scene = self._make_scene_in_hass(family_name="我的家", area_id="user_area")

        area_reg = MagicMock()
        ent_reg = MagicMock()

        with (
            patch("custom_components.haier_home.scene.ar.async_get", return_value=area_reg),
            patch("custom_components.haier_home.scene.er.async_get", return_value=ent_reg),
        ):
            await scene.async_added_to_hass()

        area_reg.async_get_area_by_name.assert_not_called()
        ent_reg.async_update_entity.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_without_family_name(self):
        """Legacy scenes without a home name stay unassigned (empty area)."""
        from unittest.mock import MagicMock, patch

        scene = self._make_scene_in_hass(family_name=None, area_id=None)

        area_reg = MagicMock()
        ent_reg = MagicMock()

        with (
            patch("custom_components.haier_home.scene.ar.async_get", return_value=area_reg),
            patch("custom_components.haier_home.scene.er.async_get", return_value=ent_reg),
        ):
            await scene.async_added_to_hass()

        area_reg.async_get_area_by_name.assert_not_called()
        ent_reg.async_update_entity.assert_not_called()
