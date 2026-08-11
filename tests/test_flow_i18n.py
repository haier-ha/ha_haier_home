"""Tests for haier/flow_i18n.py."""

from __future__ import annotations

from custom_components.haier_home.haier.flow_i18n import (
    SUPPORTED_FLOW_LANGUAGES,
    flow_t,
    normalize_flow_language,
    translate,
)


class TestNormalizeFlowLanguage:
    """Test normalize_flow_language function."""

    def test_normalize_supported_language(self):
        assert normalize_flow_language("en") == "en"

    def test_normalize_unsupported_language(self):
        assert normalize_flow_language("xx") == "zh-Hans"

    def test_normalize_none(self):
        assert normalize_flow_language(None) == "zh-Hans"


class TestTranslate:
    """Test translate function."""

    def test_translate_existing_key(self):
        result = translate("en", "title")
        assert isinstance(result, str)

    def test_translate_nonexistent_key(self):
        result = translate("en", "nonexistent_key", "default_value")
        assert result == "default_value"

    def test_translate_nested_key(self):
        result = translate("en", "title")
        assert isinstance(result, str)

    def test_translate_unsupported_language(self):
        result = translate("xx", "title")
        assert isinstance(result, str)

    def test_flow_t_alias(self):
        result1 = translate("en", "title")
        result2 = flow_t("en", "title")
        assert result1 == result2

    def test_translate_nested_path_missing_midway(self):
        result = translate("en", "title.nonexistent.deep", "fallback")
        assert result == "fallback"


class TestSupportedFlowLanguages:
    """Test SUPPORTED_FLOW_LANGUAGES constant."""

    def test_supported_languages_contains_en(self):
        assert "en" in SUPPORTED_FLOW_LANGUAGES
