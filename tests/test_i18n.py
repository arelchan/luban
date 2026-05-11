"""Tests for agentkit.cli.i18n — translation system."""

from __future__ import annotations

from agentkit.cli.i18n import TEXTS, TOOL_DESCRIPTIONS, t, tool_desc


class TestTranslation:
    def test_t_basic_zh(self):
        result = t("cleared", "zh")
        assert "清除" in result

    def test_t_basic_en(self):
        result = t("cleared", "en")
        assert "cleared" in result.lower()

    def test_t_with_kwargs(self):
        result = t("model_label", "zh", model="claude-3")
        assert "claude-3" in result

    def test_t_missing_key_returns_key(self):
        result = t("nonexistent_key_xyz", "zh")
        assert result == "nonexistent_key_xyz"

    def test_t_fallback_to_zh(self):
        result = t("cleared", "invalid_lang")
        assert "清除" in result

    def test_all_keys_in_both_languages(self):
        zh_keys = set(TEXTS["zh"].keys())
        en_keys = set(TEXTS["en"].keys())
        assert zh_keys == en_keys, f"Missing in en: {zh_keys - en_keys}, Missing in zh: {en_keys - zh_keys}"

    def test_no_empty_values(self):
        for lang in ("zh", "en"):
            for key, value in TEXTS[lang].items():
                assert value.strip(), f"Empty value for key '{key}' in lang '{lang}'"


class TestToolDescriptions:
    def test_tool_desc_zh(self):
        desc = tool_desc("calculate", "zh")
        assert desc is not None
        assert "数学" in desc

    def test_tool_desc_en_returns_none(self):
        desc = tool_desc("calculate", "en")
        assert desc is None  # English uses original docstrings

    def test_tool_desc_unknown_tool(self):
        desc = tool_desc("nonexistent_tool_xyz", "zh")
        assert desc is None

    def test_all_builtin_tools_have_zh_descriptions(self):
        expected_tools = [
            "read_file", "write_file", "edit_file", "run_command",
            "glob_files", "grep_files", "list_directory",
            "get_current_time", "calculate", "web_fetch", "web_search",
        ]
        for tool_name in expected_tools:
            desc = tool_desc(tool_name, "zh")
            assert desc is not None, f"Missing zh description for tool: {tool_name}"
            assert len(desc) > 0
