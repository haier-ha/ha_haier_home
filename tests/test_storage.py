"""Tests for haier/storage.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.haier_home.haier.storage import HaierDeviceCache


class TestHaierDeviceCacheInit:
    """Test HaierDeviceCache initialization."""

    def test_init(self):
        """Test initialization creates data structure."""
        mock_store = MagicMock()
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")

        assert cache._data == {
            "device_list": None,
            "digital_models": {},
            "scenes": None,
            "assigned_areas": {},
        }
        assert cache._loaded is False
        assert cache._dirty is False


class TestHaierDeviceCacheLoadSave:
    """Test async_load and async_save methods."""

    @pytest.mark.asyncio
    async def test_async_load(self):
        """Test loading cache from store."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(
            return_value={
                "device_list": {"ts": 1234567890, "homes": ["family_001"], "value": []},
                "digital_models": {},
                "scenes": None,
            }
        )
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

        assert cache._loaded is True
        assert cache._data["device_list"] is not None

    @pytest.mark.asyncio
    async def test_async_load_empty(self):
        """Test loading empty cache."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

        assert cache._loaded is True

    @pytest.mark.asyncio
    async def test_async_save_dirty(self):
        """Test saving dirty cache."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        mock_store.async_save = AsyncMock()
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()
            cache._dirty = True

            result = await cache.async_save()

        assert result is True
        mock_store.async_save.assert_called_once()
        assert cache._dirty is False

    @pytest.mark.asyncio
    async def test_async_save_not_dirty(self):
        """Test saving not dirty cache."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        mock_store.async_save = AsyncMock()
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            result = await cache.async_save()

        assert result is False
        mock_store.async_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_remove(self):
        """Test removing cache."""
        mock_store = MagicMock()
        mock_store.async_remove = AsyncMock()
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_remove()

        mock_store.async_remove.assert_called_once()
        assert cache._data == {
            "device_list": None,
            "digital_models": {},
            "scenes": None,
            "assigned_areas": {},
        }


class TestHaierDeviceCacheDeviceList:
    """Test device list methods."""

    @pytest.mark.asyncio
    async def test_set_device_list(self):
        """Test setting device list."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            device_list = [{"deviceId": "device_001"}]
            cache.set_device_list(["family_001"], device_list)

            assert cache._data["device_list"] is not None
            assert cache._data["device_list"]["value"] == device_list
            assert cache._dirty is True

    @pytest.mark.asyncio
    async def test_get_device_list(self):
        """Test getting device list."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            device_list = [{"deviceId": "device_001"}]
            cache.set_device_list(["family_001"], device_list)

            result = cache.get_device_list(["family_001"])
            assert result == device_list

    @pytest.mark.asyncio
    async def test_get_device_list_wrong_homes(self):
        """Test getting device list with wrong homes returns None."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            device_list = [{"deviceId": "device_001"}]
            cache.set_device_list(["family_001"], device_list)

            result = cache.get_device_list(["family_002"])
            assert result is None

    @pytest.mark.asyncio
    async def test_get_device_list_stale(self):
        """Test getting stale device list."""
        import time

        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry", ttl=1)  # 1 second TTL
            await cache.async_load()

            device_list = [{"deviceId": "device_001"}]
            cache.set_device_list(["family_001"], device_list)

            # Wait for TTL to expire
            time.sleep(1.1)

            # Without allow_stale, should return None
            result = cache.get_device_list(["family_001"])
            assert result is None

            # With allow_stale, should return data
            result = cache.get_device_list(["family_001"], allow_stale=True)
            assert result == device_list


class TestHaierDeviceCacheDigitalModels:
    """Test digital models methods."""

    @pytest.mark.asyncio
    async def test_set_digital_model(self):
        """Test setting digital model."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            model = {"attributes": []}
            cache.set_digital_model("device_001", model)

            assert cache._data["digital_models"]["device_001"] is not None
            assert cache._data["digital_models"]["device_001"]["value"] == model

    @pytest.mark.asyncio
    async def test_get_digital_model(self):
        """Test getting digital model."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            model = {"attributes": []}
            cache.set_digital_model("device_001", model)

            result = cache.get_digital_model("device_001")
            assert result == model

    @pytest.mark.asyncio
    async def test_get_digital_model_not_found(self):
        """Test getting non-existent digital model returns None."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            result = cache.get_digital_model("device_001")
            assert result is None

    @pytest.mark.asyncio
    async def test_prune_digital_models(self):
        """Test pruning digital models."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            cache.set_digital_model("device_001", {})
            cache.set_digital_model("device_002", {})
            cache.set_digital_model("device_003", {})

            # Reset dirty flag
            cache._dirty = False

            # Prune device_003
            cache.prune_digital_models({"device_001", "device_002"})

            assert "device_003" not in cache._data["digital_models"]
            assert cache._dirty is True


class TestHaierDeviceCacheScenes:
    """Test scenes methods."""

    @pytest.mark.asyncio
    async def test_set_scenes(self):
        """Test setting scenes."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            scenes = {"family_001": [{"sceneId": "scene_001"}]}
            cache.set_scenes(["family_001"], scenes)

            assert cache._data["scenes"] is not None
            assert cache._data["scenes"]["value"] == scenes

    @pytest.mark.asyncio
    async def test_get_scenes(self):
        """Test getting scenes."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            scenes = {"family_001": [{"sceneId": "scene_001"}]}
            cache.set_scenes(["family_001"], scenes)

            result = cache.get_scenes(["family_001"])
            assert result == scenes

    @pytest.mark.asyncio
    async def test_get_scenes_wrong_homes(self):
        """Test getting scenes with wrong homes returns None."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            scenes = {"family_001": [{"sceneId": "scene_001"}]}
            cache.set_scenes(["family_001"], scenes)

            result = cache.get_scenes(["family_002"])
            assert result is None


class TestHaierDeviceCacheAssignedAreas:
    """Test assigned-area (device_id -> area_id) methods."""

    @pytest.mark.asyncio
    async def test_set_and_get_assigned_area(self):
        """Setting an area id makes it retrievable and marks the cache dirty."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()
            cache._dirty = False

            cache.set_assigned_area("device_001", "area_abc")

            assert cache.get_assigned_area("device_001") == "area_abc"
            assert cache._dirty is True

    @pytest.mark.asyncio
    async def test_get_assigned_area_missing(self):
        """Unknown device returns None (caller falls back to name heuristic)."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            assert cache.get_assigned_area("device_001") is None

    @pytest.mark.asyncio
    async def test_set_assigned_area_none_clears(self):
        """Passing None removes the record and marks dirty only if it existed."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            cache.set_assigned_area("device_001", "area_abc")
            cache._dirty = False

            cache.set_assigned_area("device_001", None)
            assert cache.get_assigned_area("device_001") is None
            assert cache._dirty is True

            # Clearing a non-existent record is a no-op (stays clean).
            cache._dirty = False
            cache.set_assigned_area("device_001", None)
            assert cache._dirty is False

    @pytest.mark.asyncio
    async def test_set_assigned_area_unchanged_is_noop(self):
        """Re-setting the same id does not re-mark the cache dirty."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            cache.set_assigned_area("device_001", "area_abc")
            cache._dirty = False

            cache.set_assigned_area("device_001", "area_abc")
            assert cache._dirty is False

    @pytest.mark.asyncio
    async def test_prune_assigned_areas(self):
        """Pruning drops records for devices no longer present."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            cache.set_assigned_area("device_001", "area_a")
            cache.set_assigned_area("device_002", "area_b")
            cache.set_assigned_area("device_003", "area_c")
            cache._dirty = False

            cache.prune_assigned_areas({"device_001", "device_002"})

            assert cache.get_assigned_area("device_003") is None
            assert cache.get_assigned_area("device_001") == "area_a"
            assert cache._dirty is True

    @pytest.mark.asyncio
    async def test_assigned_areas_loaded_from_disk(self):
        """A persisted assigned_areas map is restored on load."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(
            return_value={
                "device_list": None,
                "digital_models": {},
                "scenes": None,
                "assigned_areas": {"device_001": "area_abc"},
            }
        )
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            assert cache.get_assigned_area("device_001") == "area_abc"

    @pytest.mark.asyncio
    async def test_assigned_areas_missing_key_backward_compatible(self):
        """An old cache file without assigned_areas loads without error."""
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(
            return_value={
                "device_list": None,
                "digital_models": {},
                "scenes": None,
            }
        )
        hass = MagicMock()

        with patch("custom_components.haier_home.haier.storage.Store", return_value=mock_store):
            cache = HaierDeviceCache(hass, "test_entry")
            await cache.async_load()

            assert cache.get_assigned_area("device_001") is None
            assert cache._data["assigned_areas"] == {}
