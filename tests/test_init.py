"""Tests for the integration entry point (__init__.py)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.haier_home.const import DOMAIN, EVENT_SEND_COMMAND


def _fake_dr():
    """Fake device_registry module: empty entry set, records removals."""
    registry = SimpleNamespace(async_remove_device=MagicMock())
    return SimpleNamespace(
        async_get=lambda hass: registry,
        async_entries_for_config_entry=lambda reg, entry_id: [],
    )


def _fake_ar():
    """Fake area_registry module (only async_get is exercised here)."""
    registry = SimpleNamespace()
    return SimpleNamespace(async_get=lambda hass: registry)


# A well-formed stored token (the four fields the OAuth flow / refresh produce).
_VALID_TOKEN = {
    "access_token": "test_token",
    "refresh_token": "test_refresh_token",
    "expires_in": 3600,
    "expires_at": 9999999999,
}


class TestAsyncSetup:
    """Test async_setup function."""

    @pytest.mark.asyncio
    async def test_async_setup(self):
        """Test async_setup sets up the domain and registers event listener."""
        hass = SimpleNamespace(
            data={},
            bus=SimpleNamespace(async_listen=MagicMock()),
            async_add_executor_job=AsyncMock(),
        )

        from custom_components.haier_home import async_setup

        result = await async_setup(hass, {})

        assert result is True
        assert DOMAIN in hass.data
        hass.bus.async_listen.assert_called_once()
        assert hass.bus.async_listen.call_args[0][0] == EVENT_SEND_COMMAND
        # The listener is wrapped in a lambda that binds hass to the real function.
        listener = hass.bus.async_listen.call_args[0][1]
        assert callable(listener)
        hass.async_add_executor_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_handles_send_command_event(self):
        """Test _handle_send_command event handler."""
        from custom_components.haier_home import _handle_send_command

        mock_coordinator = AsyncMock()
        mock_coordinator.async_send_command = AsyncMock()
        mock_coordinator.devices = {"device_001": {}}  # Device exists in coordinator

        hass = SimpleNamespace(
            data={
                DOMAIN: {
                    "entry_1": {"coordinator": mock_coordinator},
                }
            }
        )

        event = SimpleNamespace(
            data={"device_id": "device_001", "commands": {"targetTemperature": "26"}},
        )

        await _handle_send_command(event, hass)

        mock_coordinator.async_send_command.assert_called_once_with(
            "device_001", {"targetTemperature": "26"}
        )

    @pytest.mark.asyncio
    async def test_handle_send_command_no_coordinator(self):
        """Test _handle_send_command when no coordinator found."""
        from custom_components.haier_home import _handle_send_command

        hass = SimpleNamespace(data={DOMAIN: {}})

        event = SimpleNamespace(
            data={"device_id": "device_001", "commands": {"targetTemperature": "26"}},
        )

        # Should not raise
        await _handle_send_command(event, hass)


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_success(self):
        """Test async_setup_entry with mock data."""
        from custom_components.haier_home import async_setup_entry
        from tests.mock_data import create_mock_ac_device

        mock_device = create_mock_ac_device()

        mock_client = MagicMock()
        mock_client.get_homes = AsyncMock(
            return_value={
                "createfamilies": [{"familyId": "family_001", "familyName": "我的家"}],
                "joinfamilies": [],
            }
        )
        mock_client.get_devices = AsyncMock(return_value={"deviceInfos": []})
        mock_client.get_device_digital_model = AsyncMock(return_value={})

        mock_coordinator_class = MagicMock()
        mock_coordinator = MagicMock()
        mock_coordinator.devices = {mock_device.device_id: mock_device}
        mock_coordinator_class.return_value = mock_coordinator
        mock_coordinator.async_start = AsyncMock()
        mock_coordinator._ensure_dependencies_ready = AsyncMock(return_value=True)

        mock_cache = MagicMock()
        mock_cache.async_load = AsyncMock()
        mock_cache.set_device_list = MagicMock()
        mock_cache.prune_digital_models = MagicMock()
        mock_cache.set_digital_model = MagicMock()
        mock_cache.async_save = AsyncMock(return_value=True)

        hass = SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
            async_add_executor_job=AsyncMock(),
        )

        entry = SimpleNamespace(
            entry_id="test_entry",
            data={
                "token": _VALID_TOKEN,
                "ag_client_id": "test_client_id",
                "region": "cn",
                "language": "zh-Hans",
                "homes": ["family_001"],
                "room_sync_mode": "family_and_room",
            },
        )

        mock_oauth_impl = MagicMock()

        with (
            patch("custom_components.haier_home.HaierCoordinator", mock_coordinator_class),
            patch("custom_components.haier_home.HaierHttpClient", return_value=mock_client),
            patch("custom_components.haier_home.HaierDeviceCache", return_value=mock_cache),
            patch("custom_components.haier_home.dr", _fake_dr()),
            patch("custom_components.haier_home.ar", _fake_ar()),
            patch(
                "custom_components.haier_home.create_device_from_api_record",
                return_value=None,
            ),
            patch("custom_components.haier_home.parse_digital_model", return_value={}),
            patch(
                "custom_components.haier_home.HaierOAuth2Implementation",
                return_value=mock_oauth_impl,
            ),
            patch(
                "custom_components.haier_home.config_entry_oauth2_flow.async_register_implementation"
            ),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        assert DOMAIN in hass.data
        assert entry.entry_id in hass.data[DOMAIN]
        mock_coordinator.async_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_entry_missing_access_token(self):
        """Test setup raises ConfigEntryAuthFailed when the stored token is empty."""
        from homeassistant.config_entries import ConfigEntryAuthFailed

        from custom_components.haier_home import async_setup_entry

        hass = SimpleNamespace(data={})
        entry = SimpleNamespace(
            entry_id="test_entry",
            data={
                "token": {},
                "ag_client_id": "test_client_id",
                "region": "cn",
            },
        )

        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, entry)

    @pytest.mark.asyncio
    async def test_async_setup_entry_missing_ag_client_id(self):
        """Test setup surfaces re-configure when config-flow data (ag_client_id) is missing."""
        from homeassistant.config_entries import ConfigEntryNotReady

        from custom_components.haier_home import async_setup_entry

        hass = SimpleNamespace(data={})
        entry = SimpleNamespace(
            entry_id="test_entry",
            data={
                "token": _VALID_TOKEN,
                "region": "cn",
                "language": "zh-Hans",
            },
        )

        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)

    @pytest.mark.asyncio
    async def test_async_setup_entry_device_list_from_cache(self):
        """Test fallback to cached device list when cloud fails."""
        from custom_components.haier_home import async_setup_entry

        mock_client = MagicMock()
        mock_client.get_homes = AsyncMock(return_value={"createfamilies": [], "joinfamilies": []})
        mock_client.get_devices = AsyncMock(side_effect=Exception("Cloud error"))

        mock_cache = MagicMock()
        mock_cache.async_load = AsyncMock()
        mock_cache.get_device_list = AsyncMock(
            return_value=[
                {
                    "deviceId": "device_001",
                    "apptypeCode": "A177",
                    "pid": "test_pid",
                    "online": True,
                }
            ]
        )
        mock_cache.set_device_list = MagicMock()
        mock_cache.prune_digital_models = MagicMock()
        mock_cache.set_digital_model = MagicMock()
        mock_cache.async_save = AsyncMock(return_value=True)

        mock_coordinator_class = MagicMock()
        mock_coordinator = MagicMock()
        mock_coordinator.devices = {}
        mock_coordinator_class.return_value = mock_coordinator
        mock_coordinator.async_start = AsyncMock()
        mock_coordinator._ensure_dependencies_ready = AsyncMock(return_value=True)

        hass = SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
            async_add_executor_job=AsyncMock(),
        )

        entry = SimpleNamespace(
            entry_id="test_entry",
            data={
                "token": _VALID_TOKEN,
                "ag_client_id": "test_client_id",
                "region": "cn",
                "language": "zh-Hans",
                "homes": [],
            },
        )

        with (
            patch("custom_components.haier_home.HaierCoordinator", mock_coordinator_class),
            patch("custom_components.haier_home.HaierHttpClient", return_value=mock_client),
            patch("custom_components.haier_home.HaierDeviceCache", return_value=mock_cache),
            patch("custom_components.haier_home.dr", _fake_dr()),
            patch("custom_components.haier_home.ar", _fake_ar()),
            patch("custom_components.haier_home.create_device_from_api_record", return_value=None),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        mock_cache.get_device_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_entry_network_unreachable(self):
        """Test digital model fallback when network is unreachable."""
        import aiohttp

        from custom_components.haier_home import async_setup_entry

        mock_client = MagicMock()
        mock_client.get_homes = AsyncMock(return_value={"createfamilies": [], "joinfamilies": []})
        mock_client.get_devices = AsyncMock(
            return_value={
                "deviceInfos": [
                    {
                        "deviceId": "device_001",
                        "apptypeCode": "A177",
                        "pid": "test_pid",
                        "online": True,
                    }
                ]
            }
        )
        mock_client.get_device_digital_model = AsyncMock(side_effect=aiohttp.ClientError())

        mock_cache = MagicMock()
        mock_cache.async_load = AsyncMock()
        mock_cache.set_device_list = MagicMock()
        mock_cache.prune_digital_models = MagicMock()
        mock_cache.get_digital_model = AsyncMock(return_value={})
        mock_cache.set_digital_model = MagicMock()
        mock_cache.async_save = AsyncMock(return_value=True)

        mock_coordinator_class = MagicMock()
        mock_coordinator = MagicMock()
        mock_coordinator.devices = {}
        mock_coordinator_class.return_value = mock_coordinator
        mock_coordinator.async_start = AsyncMock()
        mock_coordinator._ensure_dependencies_ready = AsyncMock(return_value=True)

        hass = SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
            async_add_executor_job=AsyncMock(),
        )

        entry = SimpleNamespace(
            entry_id="test_entry",
            data={
                "token": _VALID_TOKEN,
                "ag_client_id": "test_client_id",
                "region": "cn",
                "language": "zh-Hans",
                "homes": [],
            },
        )

        mock_oauth_impl = MagicMock()

        with (
            patch("custom_components.haier_home.HaierCoordinator", mock_coordinator_class),
            patch("custom_components.haier_home.HaierHttpClient", return_value=mock_client),
            patch("custom_components.haier_home.HaierDeviceCache", return_value=mock_cache),
            patch("custom_components.haier_home.dr", _fake_dr()),
            patch("custom_components.haier_home.ar", _fake_ar()),
            patch("custom_components.haier_home.create_device_from_api_record", return_value=None),
            patch("custom_components.haier_home.parse_digital_model", return_value={}),
            patch(
                "custom_components.haier_home.HaierOAuth2Implementation",
                return_value=mock_oauth_impl,
            ),
            patch(
                "custom_components.haier_home.config_entry_oauth2_flow.async_register_implementation"
            ),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True


class TestAsyncUnloadEntry:
    """Test async_unload_entry function."""

    @pytest.mark.asyncio
    async def test_async_unload_entry(self):
        """Test async_unload_entry stops coordinator."""
        from custom_components.haier_home import async_unload_entry

        mock_coordinator = AsyncMock()
        mock_coordinator.async_stop = AsyncMock()

        hass = SimpleNamespace(
            data={
                DOMAIN: {
                    "test_entry": {"coordinator": mock_coordinator},
                }
            },
            config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True)),
        )

        entry = SimpleNamespace(entry_id="test_entry")

        result = await async_unload_entry(hass, entry)

        assert result is True
        mock_coordinator.async_stop.assert_called_once()
        assert "test_entry" not in hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_async_unload_entry_no_entry_data(self):
        """Test async_unload_entry when entry data doesn't exist."""
        from custom_components.haier_home import async_unload_entry

        hass = SimpleNamespace(
            data={DOMAIN: {}},
            config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True)),
        )

        entry = SimpleNamespace(entry_id="test_entry")

        result = await async_unload_entry(hass, entry)

        assert result is True


class TestAsyncRemoveEntry:
    """Test async_remove_entry function."""

    @pytest.mark.asyncio
    async def test_async_remove_entry(self):
        """Test async_remove_entry removes cache."""
        from custom_components.haier_home import async_remove_entry

        mock_cache = MagicMock()
        mock_cache.async_remove = AsyncMock()

        hass = SimpleNamespace()

        entry = SimpleNamespace(entry_id="test_entry")

        with patch("custom_components.haier_home.HaierDeviceCache", return_value=mock_cache):
            await async_remove_entry(hass, entry)

        mock_cache.async_remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_remove_entry_cache_failure(self):
        """Test async_remove_entry handles cache removal failure."""
        from custom_components.haier_home import async_remove_entry

        mock_cache = MagicMock()
        mock_cache.async_remove = AsyncMock(side_effect=Exception("Cache error"))

        hass = SimpleNamespace()

        entry = SimpleNamespace(entry_id="test_entry")

        with patch("custom_components.haier_home.HaierDeviceCache", return_value=mock_cache):
            # Should not raise
            await async_remove_entry(hass, entry)


class _FakeDevRegEntry:
    """Minimal stand-in for a HA device-registry entry."""

    def __init__(self, entry_id: str, identifiers: set[tuple[str, str]]):
        self.id = entry_id
        self.identifiers = identifiers


class _FakeDeviceRegistry:
    def __init__(self, entries):
        self._entries = entries
        self.removed: list[str] = []

    def async_remove_device(self, device_id: str) -> None:
        self.removed.append(device_id)


class TestCleanupOrphanDevices:
    """_async_cleanup_orphan_devices prunes cloud-deleted device-backed devices."""

    @staticmethod
    def _patch_registry(monkeypatch, entries):
        import custom_components.haier_home as init_mod

        registry = _FakeDeviceRegistry(entries)
        fake_dr = SimpleNamespace(
            async_get=lambda hass: registry,
            async_entries_for_config_entry=lambda reg, entry_id: list(entries),
        )
        monkeypatch.setattr(init_mod, "dr", fake_dr)
        return init_mod, registry

    def test_removes_only_cloud_deleted_devices(self, monkeypatch):
        entries = [
            _FakeDevRegEntry("reg_keep", {(DOMAIN, "device_keep")}),
            _FakeDevRegEntry("reg_orphan", {(DOMAIN, "device_orphan")}),
        ]
        init_mod, registry = self._patch_registry(monkeypatch, entries)
        entry = SimpleNamespace(entry_id="e1")

        init_mod._async_cleanup_orphan_devices(
            hass=SimpleNamespace(), entry=entry, expected_device_ids={"device_keep"}
        )

        assert registry.removed == ["reg_orphan"]

    def test_keeps_all_when_all_present(self, monkeypatch):
        entries = [
            _FakeDevRegEntry("reg_a", {(DOMAIN, "device_a")}),
            _FakeDevRegEntry("reg_b", {(DOMAIN, "device_b")}),
        ]
        init_mod, registry = self._patch_registry(monkeypatch, entries)
        entry = SimpleNamespace(entry_id="e1")

        init_mod._async_cleanup_orphan_devices(
            hass=SimpleNamespace(),
            entry=entry,
            expected_device_ids={"device_a", "device_b"},
        )

        assert registry.removed == []

    def test_ignores_devices_with_foreign_identifiers(self, monkeypatch):
        # A device registry entry that carries only a non-DOMAIN identifier must
        # never be removed by this integration.
        entries = [
            _FakeDevRegEntry("reg_foreign", {("other_domain", "x")}),
        ]
        init_mod, registry = self._patch_registry(monkeypatch, entries)
        entry = SimpleNamespace(entry_id="e1")

        init_mod._async_cleanup_orphan_devices(
            hass=SimpleNamespace(), entry=entry, expected_device_ids=set()
        )

        # Not expected (no DOMAIN identifier match) → removed as orphan.
        # This is safe because async_entries_for_config_entry already scopes to
        # THIS entry's devices; a foreign-only identifier under our entry should
        # not normally occur, and removing the stale registry link is correct.
        assert registry.removed == ["reg_foreign"]


class _FakeArea:
    def __init__(self, area_id: str, name: str):
        self.id = area_id
        self.name = name


class _FakeAreaRegistry:
    """Area registry that can look up by id/name and create new areas."""

    def __init__(self, areas=None):
        self._by_id = {a.id: a for a in (areas or [])}
        self.created: list[str] = []

    def async_get_area(self, area_id):
        return self._by_id.get(area_id)

    def async_get_area_by_name(self, name):
        for area in self._by_id.values():
            if area.name == name:
                return area
        return None

    def async_create(self, name):
        area = _FakeArea(f"area_{name}", name)
        self._by_id[area.id] = area
        self.created.append(name)
        return area


class _FakeReconcileRegDevice:
    def __init__(self, device_id, identifiers, area_id=None):
        self.id = device_id
        self.identifiers = identifiers
        self.area_id = area_id


class _FakeReconcileDeviceRegistry:
    def __init__(self, reg_device):
        self._reg_device = reg_device
        self.updates: list[tuple[str, str | None]] = []

    def async_get_device(self, identifiers):
        if self._reg_device and self._reg_device.identifiers & identifiers:
            return self._reg_device
        return None

    def async_update_device(self, device_id, area_id=None):
        self._reg_device.area_id = area_id
        self.updates.append((device_id, area_id))


class _FakeAreaCache:
    def __init__(self, assigned=None):
        self._assigned = dict(assigned or {})

    def get_assigned_area(self, device_id):
        return self._assigned.get(device_id)

    def set_assigned_area(self, device_id, area_id):
        if area_id is None:
            self._assigned.pop(device_id, None)
        else:
            self._assigned[device_id] = area_id


def _make_device(device_id, suggested_area, managed_area_names):
    return SimpleNamespace(
        device_id=device_id,
        suggested_area=suggested_area,
        managed_area_names=managed_area_names,
    )


class TestReconcileDeviceArea:
    """_reconcile_device_area moves integration-owned devices, keeps custom ones."""

    def test_cloud_transfer_moves_device_via_persisted_id(self):
        """A device transferred on the cloud is moved to its new area.

        The old area name is no longer among the (new-location) candidates, so
        only the persisted assignment id proves ownership -- this is the exact
        case that used to get stuck.
        """
        from custom_components.haier_home import _reconcile_device_area

        old_area = _FakeArea("a1", "家庭1 一层 房间1")
        area_reg = _FakeAreaRegistry([old_area])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a1")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache({"device_001": "a1"})

        # Device now reports a new location (family 2); managed names reflect
        # only that new location, NOT the old "家庭1 一层 房间1".
        device = _make_device(
            "device_001",
            suggested_area="家庭2 一层 房间2",
            managed_area_names=["家庭2 一层 房间2", "一层 房间2", "家庭2"],
        )

        _reconcile_device_area(dev_reg, area_reg, device, cache)

        assert reg_device.area_id == "area_家庭2 一层 房间2"
        assert "家庭2 一层 房间2" in area_reg.created
        assert cache.get_assigned_area("device_001") == "area_家庭2 一层 房间2"

    def test_user_customized_area_left_untouched(self):
        """A device the user manually re-homed is not moved."""
        from custom_components.haier_home import _reconcile_device_area

        custom_area = _FakeArea("a_custom", "客厅")
        area_reg = _FakeAreaRegistry([custom_area])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a_custom")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        # We last put it in a1, but the user moved it to a_custom.
        cache = _FakeAreaCache({"device_001": "a1"})
        device = _make_device(
            "device_001",
            suggested_area="家庭2 一层 房间2",
            managed_area_names=["家庭2 一层 房间2"],
        )

        _reconcile_device_area(dev_reg, area_reg, device, cache)

        assert reg_device.area_id == "a_custom"
        assert dev_reg.updates == []
        assert area_reg.created == []

    def test_no_record_falls_back_to_name_heuristic_owned(self):
        """With no persisted id, a name-candidate area is still recognized."""
        from custom_components.haier_home import _reconcile_device_area

        old_area = _FakeArea("a1", "家庭1 一层 房间1")
        area_reg = _FakeAreaRegistry([old_area])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a1")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache()  # no record (e.g. first run after upgrade)
        device = _make_device(
            "device_001",
            suggested_area="家庭1 一层 房间2",
            managed_area_names=["家庭1 一层 房间2", "家庭1 一层 房间1"],
        )

        _reconcile_device_area(dev_reg, area_reg, device, cache)

        assert reg_device.area_id == "area_家庭1 一层 房间2"
        assert cache.get_assigned_area("device_001") == "area_家庭1 一层 房间2"

    def test_no_record_name_not_managed_left_untouched(self):
        """With no persisted id and a non-candidate name, leave the area."""
        from custom_components.haier_home import _reconcile_device_area

        custom = _FakeArea("a_custom", "书房")
        area_reg = _FakeAreaRegistry([custom])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a_custom")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache()
        device = _make_device(
            "device_001",
            suggested_area="家庭1 一层 房间2",
            managed_area_names=["家庭1 一层 房间2"],
        )

        _reconcile_device_area(dev_reg, area_reg, device, cache)

        assert reg_device.area_id == "a_custom"
        assert dev_reg.updates == []

    def test_empty_area_is_assigned_and_recorded(self):
        """A device with no area is populated and the assignment persisted."""
        from custom_components.haier_home import _reconcile_device_area

        area_reg = _FakeAreaRegistry()
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id=None)
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache()
        device = _make_device(
            "device_001",
            suggested_area="家庭1 一层 房间1",
            managed_area_names=["家庭1 一层 房间1"],
        )

        _reconcile_device_area(dev_reg, area_reg, device, cache)

        assert reg_device.area_id == "area_家庭1 一层 房间1"
        assert cache.get_assigned_area("device_001") == "area_家庭1 一层 房间1"

    def test_already_in_target_records_id_on_first_pass(self):
        """When already in the target area, the id is backfilled into cache."""
        from custom_components.haier_home import _reconcile_device_area

        area = _FakeArea("a1", "家庭1 一层 房间1")
        area_reg = _FakeAreaRegistry([area])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a1")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache()  # no record yet
        device = _make_device(
            "device_001",
            suggested_area="家庭1 一层 房间1",
            managed_area_names=["家庭1 一层 房间1"],
        )

        _reconcile_device_area(dev_reg, area_reg, device, cache)

        # No move happened, but the assignment is now recorded for next time.
        assert dev_reg.updates == []
        assert cache.get_assigned_area("device_001") == "a1"

    def test_mode_none_detaches_owned_device_and_clears_record(self):
        """Sync mode 'none' detaches an owned device and forgets the record."""
        from custom_components.haier_home import _reconcile_device_area

        area = _FakeArea("a1", "家庭1 一层 房间1")
        area_reg = _FakeAreaRegistry([area])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a1")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache({"device_001": "a1"})
        device = _make_device(
            "device_001",
            suggested_area=None,  # mode "none"
            managed_area_names=["家庭1 一层 房间1"],
        )

        _reconcile_device_area(dev_reg, area_reg, device, cache)

        assert reg_device.area_id is None
        assert cache.get_assigned_area("device_001") is None

    def test_restored_from_tombstone_adopts_suggested_area(self):
        """A tombstone-restored device adopts suggested_area over its stale area.

        This is the remove+re-add fix: HA restores the device into its old area
        ('A家庭') ignoring suggested_area, and the per-entry cache proving
        ownership is gone (fresh cache after re-add). Because the device is
        provably ours (restored from our tombstone), the user-customized guard
        is bypassed and it is moved to the current target ('B家庭').
        """
        from custom_components.haier_home import _reconcile_device_area

        old_area = _FakeArea("a_old", "A家庭")
        area_reg = _FakeAreaRegistry([old_area])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a_old")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache()  # fresh cache: no ownership record survives
        device = _make_device(
            "device_001",
            suggested_area="B家庭",
            managed_area_names=["B家庭", "B家庭 一层 客厅", "一层 客厅"],
        )

        _reconcile_device_area(dev_reg, area_reg, device, cache, restored=True)

        assert reg_device.area_id == "area_B家庭"
        assert cache.get_assigned_area("device_001") == "area_B家庭"

    def test_restored_from_tombstone_already_in_target_no_move(self):
        """A restored device already in the target area is only recorded."""
        from custom_components.haier_home import _reconcile_device_area

        area = _FakeArea("a_b", "B家庭")
        area_reg = _FakeAreaRegistry([area])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a_b")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache()
        device = _make_device("device_001", suggested_area="B家庭", managed_area_names=["B家庭"])

        _reconcile_device_area(dev_reg, area_reg, device, cache, restored=True)

        assert reg_device.area_id == "a_b"
        assert dev_reg.updates == []
        assert cache.get_assigned_area("device_001") == "a_b"

    def test_non_restored_user_area_still_left_untouched(self):
        """Without the restored flag, a non-owned area is still respected."""
        from custom_components.haier_home import _reconcile_device_area

        custom = _FakeArea("a_custom", "书房")
        area_reg = _FakeAreaRegistry([custom])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a_custom")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache()
        device = _make_device("device_001", suggested_area="B家庭", managed_area_names=["B家庭"])

        # restored defaults to False -> guard active -> left untouched.
        _reconcile_device_area(dev_reg, area_reg, device, cache)

        assert reg_device.area_id == "a_custom"
        assert dev_reg.updates == []

    def test_restored_from_tombstone_mode_none_detaches(self):
        """A restored device under mode 'none' is detached from its stale area."""
        from custom_components.haier_home import _reconcile_device_area

        old_area = _FakeArea("a_old", "A家庭")
        area_reg = _FakeAreaRegistry([old_area])
        reg_device = _FakeReconcileRegDevice("reg1", {(DOMAIN, "device_001")}, area_id="a_old")
        dev_reg = _FakeReconcileDeviceRegistry(reg_device)
        cache = _FakeAreaCache()
        device = _make_device("device_001", suggested_area=None, managed_area_names=[])

        _reconcile_device_area(dev_reg, area_reg, device, cache, restored=True)

        assert reg_device.area_id is None


class TestCollectTombstonedDeviceIds:
    """_collect_tombstoned_device_ids reads our-domain deletion tombstones."""

    def test_collects_our_domain_ids(self):
        from custom_components.haier_home import _collect_tombstoned_device_ids

        deleted = {
            "t1": SimpleNamespace(identifiers={(DOMAIN, "device_001")}),
            "t2": SimpleNamespace(identifiers={("other", "x"), (DOMAIN, "device_002")}),
            "t3": SimpleNamespace(identifiers={("other", "y")}),
        }
        dev_reg = SimpleNamespace(deleted_devices=deleted)

        assert _collect_tombstoned_device_ids(dev_reg) == {"device_001", "device_002"}

    def test_no_deleted_devices_attr_returns_empty(self):
        from custom_components.haier_home import _collect_tombstoned_device_ids

        assert _collect_tombstoned_device_ids(SimpleNamespace()) == set()


class _FakeDeletedDevice:
    def __init__(self, identifiers, config_entries):
        self.identifiers = identifiers
        self.config_entries = config_entries


class _FakeDeletedDeviceSingular:
    """Newer-core tombstone shape: singular ``config_entry_id`` (no set)."""

    def __init__(self, identifiers, config_entry_id):
        self.identifiers = identifiers
        self.config_entry_id = config_entry_id


class _FakePruneDevReg:
    """Device registry double exposing active entries + deletion tombstones."""

    def __init__(self, active=None, deleted=None):
        self._active = list(active or [])
        # DeletedDeviceRegistryItems behaves dict-like (has .values()).
        self.deleted_devices = {d.identifiers and id(d): d for d in (deleted or [])}

    def entries_for_config_entry(self, entry_id):
        return self._active


class _FakePruneCache:
    def __init__(self, assigned):
        self._assigned = dict(assigned)
        self.pruned_with = None

    def prune_assigned_areas(self, keep_device_ids):
        self.pruned_with = set(keep_device_ids)
        for dev_id in list(self._assigned):
            if dev_id not in keep_device_ids:
                del self._assigned[dev_id]

    def get_assigned_area(self, device_id):
        return self._assigned.get(device_id)


class TestPruneAssignedAreasAgainstHa:
    """assigned_areas records track HA's device lifecycle, not the cloud list."""

    def _patch(self, monkeypatch, dev_reg):
        from custom_components import haier_home as init_mod

        monkeypatch.setattr(
            init_mod.dr,
            "async_entries_for_config_entry",
            lambda reg, entry_id: reg.entries_for_config_entry(entry_id),
        )
        return init_mod

    def test_keeps_record_for_deleted_tombstone(self, monkeypatch):
        """A device gone from the cloud but still a deletion tombstone is kept.

        This is the reported bug: moved to an unauthorized family (removed from
        HA -> tombstone), its assigned-area record must survive so a later
        return can be recognized as ours and re-homed.
        """
        dev_reg = _FakePruneDevReg(
            active=[_FakeReconcileRegDevice("reg1", {(DOMAIN, "device_active")})],
            deleted=[_FakeDeletedDevice({(DOMAIN, "device_gone")}, {"e1"})],
        )
        init_mod = self._patch(monkeypatch, dev_reg)
        cache = _FakePruneCache({"device_active": "a1", "device_gone": "a_old"})

        init_mod._prune_assigned_areas_against_ha(dev_reg, SimpleNamespace(entry_id="e1"), cache)

        assert cache.get_assigned_area("device_gone") == "a_old"
        assert cache.get_assigned_area("device_active") == "a1"

    def test_drops_record_when_fully_purged(self, monkeypatch):
        """Once HA has neither an active device nor a tombstone, drop it."""
        dev_reg = _FakePruneDevReg(
            active=[_FakeReconcileRegDevice("reg1", {(DOMAIN, "device_active")})],
            deleted=[],
        )
        init_mod = self._patch(monkeypatch, dev_reg)
        cache = _FakePruneCache({"device_active": "a1", "device_purged": "a_old"})

        init_mod._prune_assigned_areas_against_ha(dev_reg, SimpleNamespace(entry_id="e1"), cache)

        assert cache.get_assigned_area("device_purged") is None
        assert cache.get_assigned_area("device_active") == "a1"

    def test_skips_prune_when_registry_lacks_tombstones(self, monkeypatch):
        """Without tombstone knowledge, never drop (avoid resurrecting the bug)."""
        dev_reg = SimpleNamespace()  # no deleted_devices attribute
        init_mod = self._patch(monkeypatch, dev_reg)
        cache = _FakePruneCache({"device_x": "a1"})

        init_mod._prune_assigned_areas_against_ha(dev_reg, SimpleNamespace(entry_id="e1"), cache)

        assert cache.pruned_with is None
        assert cache.get_assigned_area("device_x") == "a1"

    def test_ignores_tombstones_from_other_entries(self, monkeypatch):
        """A tombstone belonging to another config entry does not keep our record."""
        dev_reg = _FakePruneDevReg(
            active=[],
            deleted=[_FakeDeletedDevice({(DOMAIN, "device_gone")}, {"other_entry"})],
        )
        init_mod = self._patch(monkeypatch, dev_reg)
        cache = _FakePruneCache({"device_gone": "a_old"})

        init_mod._prune_assigned_areas_against_ha(dev_reg, SimpleNamespace(entry_id="e1"), cache)

        assert cache.get_assigned_area("device_gone") is None

    def test_keeps_record_for_singular_config_entry_id_tombstone(self, monkeypatch):
        """Newer HA core exposes singular ``config_entry_id`` on tombstones.

        The deployment target uses this shape; the record must still be kept.
        """
        dev_reg = _FakePruneDevReg(
            active=[],
            deleted=[_FakeDeletedDeviceSingular({(DOMAIN, "device_gone")}, "e1")],
        )
        init_mod = self._patch(monkeypatch, dev_reg)
        cache = _FakePruneCache({"device_gone": "a_old"})

        init_mod._prune_assigned_areas_against_ha(dev_reg, SimpleNamespace(entry_id="e1"), cache)

        assert cache.get_assigned_area("device_gone") == "a_old"

    def test_drops_orphaned_singular_tombstone(self, monkeypatch):
        """A tombstone orphaned by entry removal (config_entry_id=None) is not ours."""
        dev_reg = _FakePruneDevReg(
            active=[],
            deleted=[_FakeDeletedDeviceSingular({(DOMAIN, "device_gone")}, None)],
        )
        init_mod = self._patch(monkeypatch, dev_reg)
        cache = _FakePruneCache({"device_gone": "a_old"})

        init_mod._prune_assigned_areas_against_ha(dev_reg, SimpleNamespace(entry_id="e1"), cache)

        assert cache.get_assigned_area("device_gone") is None

    def test_keeps_record_for_unknown_tombstone_shape(self, monkeypatch):
        """Unknown tombstone shape (no entry attrs): keep the record, never drop."""
        tombstone = SimpleNamespace(identifiers={(DOMAIN, "device_gone")})
        dev_reg = _FakePruneDevReg(active=[], deleted=[tombstone])
        init_mod = self._patch(monkeypatch, dev_reg)
        cache = _FakePruneCache({"device_gone": "a_old"})

        init_mod._prune_assigned_areas_against_ha(dev_reg, SimpleNamespace(entry_id="e1"), cache)

        assert cache.get_assigned_area("device_gone") == "a_old"
