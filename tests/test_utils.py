"""Tests for haier/utils.py."""

from __future__ import annotations

from custom_components.haier_home.haier.utils import (
    generate_ag_client_id,
    generate_instant_id,
)


class TestGenerateInstantId:
    """Test generate_instant_id function."""

    def test_generate_instant_id_length(self):
        """Test generated ID has correct length."""
        result = generate_instant_id()
        assert len(result) == 12

    def test_generate_instant_id_prefix(self):
        """Test generated ID starts with 'HA'."""
        result = generate_instant_id()
        assert result.startswith("HA")

    def test_generate_instant_id_characters(self):
        """Test generated ID contains only uppercase letters and digits."""
        result = generate_instant_id()
        assert result[2:].isalnum()
        assert result[2:].isupper()


class TestGenerateAgClientId:
    """Test generate_ag_client_id function."""

    def test_generate_ag_client_id_format(self):
        """Test generated client ID has correct format."""
        result = generate_ag_client_id("cn")
        parts = result.split(".")
        assert len(parts) == 3
        assert len(parts[0]) == 12  # instant_id
        assert parts[1] == "cn"  # area
        assert len(parts[2]) == 16  # ha_uuid

    def test_generate_ag_client_id_area_sea(self):
        """Test generated client ID with sea area."""
        result = generate_ag_client_id("sea")
        parts = result.split(".")
        assert parts[1] == "sea"

    def test_generate_ag_client_id_uniqueness(self):
        """Test generated client IDs are unique."""
        ids = set()
        for _ in range(100):
            id_val = generate_ag_client_id("cn")
            assert id_val not in ids
            ids.add(id_val)
