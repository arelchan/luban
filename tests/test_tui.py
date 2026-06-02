"""Tests for agentkit.cli.tui — TUI layout and buffer management."""

from __future__ import annotations

import pytest

from agentkit.cli.tui import LubanTUI
from agentkit.cli.tui_renderer import TUIRenderer


class TestLubanTUI:
    def test_instantiation(self):
        tui = LubanTUI()
        assert tui._prompt_text == "you> "
        assert tui._chat_lines == []
        assert not tui.is_running

    def test_append_chat(self):
        tui = LubanTUI()
        tui.append_chat("hello")
        assert tui._chat_lines == ["hello"]

    def test_append_multiple(self):
        tui = LubanTUI()
        tui.append_chat("line 1")
        tui.append_chat("line 2")
        assert len(tui._chat_lines) == 2
        assert tui._chat_lines == ["line 1", "line 2"]

    def test_append_stream(self):
        tui = LubanTUI()
        tui.start_new_line()
        tui.append_stream("hel")
        tui.append_stream("lo")
        assert tui._chat_lines == ["hello"]

    def test_stream_after_chat(self):
        tui = LubanTUI()
        tui.append_chat("previous message")
        tui.start_new_line()
        tui.append_stream("streaming...")
        assert len(tui._chat_lines) == 2
        assert tui._chat_lines[1] == "streaming..."

    def test_set_status(self):
        tui = LubanTUI()
        tui.set_status("model: gpt-4 | 5k/200k")
        assert tui._status_text == "model: gpt-4 | 5k/200k"

    def test_set_prompt(self):
        tui = LubanTUI()
        tui.set_prompt("you (3k/200k)> ")
        assert tui._prompt_text == "you (3k/200k)> "

    def test_get_toolbar(self):
        tui = LubanTUI()
        tui.set_status("test")
        result = tui._get_toolbar()
        assert "test" in result

    def test_get_toolbar_empty(self):
        tui = LubanTUI()
        result = tui._get_toolbar()
        assert result == ""


class TestTUIRenderer:
    def test_show_info(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.show_info("test message")
        assert any("ℹ" in line and "test message" in line for line in tui._chat_lines)

    def test_show_success(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.show_success("done")
        assert any("✓" in line and "done" in line for line in tui._chat_lines)

    def test_show_error(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.show_error("failed")
        assert any("✗" in line and "failed" in line for line in tui._chat_lines)

    def test_stream_lifecycle(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.start_stream()
        r.stream_token("hello ")
        r.stream_token("world")
        r.end_stream()
        assert any("hello world" in line for line in tui._chat_lines)

    def test_stream_with_newlines(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.start_stream()
        r.stream_token("line1\nline2")
        r.end_stream()
        assert any("line1" in line for line in tui._chat_lines)
        assert any("line2" in line for line in tui._chat_lines)

    def test_show_tool_start(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.show_tool_start("read_file", "/path/to/file.py")
        assert any("read_file" in line for line in tui._chat_lines)

    def test_show_tool_end(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.show_tool_end("read_file", "42 lines", elapsed=1.5)
        assert any("42 lines" in line for line in tui._chat_lines)

    def test_show_startup_panel(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.show_startup_panel("gpt-4", "temp=0.7", "tools(26)", "新会话")
        assert any("gpt-4" in line for line in tui._chat_lines)

    def test_show_help(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.show_help()
        assert any("/tools" in line for line in tui._chat_lines)

    def test_show_user_message(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.show_user_message("你好")
        assert any("you:" in line and "你好" in line for line in tui._chat_lines)

    def test_stream_lifecycle(self):
        """Verify state transitions: thinking → outputting → cleared."""
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.start_stream()
        # Before first token: thinking state
        assert tui._stream_state == "thinking"
        # After first token: outputting state + header appears
        r.stream_token("hi")
        assert tui._stream_state == "outputting"
        assert any("luban" in line.lower() or "◀" in line for line in tui._chat_lines)
        # After end: state cleared
        r.end_stream()
        assert tui._stream_state == ""
        assert not r._streaming

    def test_stream_no_duplication(self):
        """Partial flush should not duplicate content when newline arrives."""
        tui = LubanTUI()
        r = TUIRenderer(tui)
        r.start_stream()
        r.stream_token("abc")
        # partial flush should show "abc" in last line
        assert tui._chat_lines[-1] == "abc"
        # Now newline arrives — should NOT have double "abc"
        r.stream_token("\ndef")
        lines_with_abc = [l for l in tui._chat_lines if "abc" in l]
        assert len(lines_with_abc) == 1, f"Duplication detected: {lines_with_abc}"
        r.end_stream()

    def test_show_session_history(self):
        tui = LubanTUI()
        r = TUIRenderer(tui)
        class FakeMsg:
            def __init__(self, role, content="", tool_calls=None):
                self.role = role
                self.content = content
                self.tool_calls = tool_calls
        msgs = [
            FakeMsg("system", "sys"),
            FakeMsg("user", "[2025-01-01 10:00] 你好"),
            FakeMsg("assistant", "你好！有什么可以帮你的？"),
            FakeMsg("user", "[2025-01-01 10:01] 再见"),
            FakeMsg("assistant", "再见！"),
        ]
        r.show_session_history(msgs, "zh")
        assert any("你好" in line for line in tui._chat_lines)
        assert any("再见" in line for line in tui._chat_lines)

    def test_show_session_history_filters_system_events(self):
        """System-event user messages (no timestamp) should be excluded."""
        tui = LubanTUI()
        r = TUIRenderer(tui)
        class FakeMsg:
            def __init__(self, role, content="", tool_calls=None):
                self.role = role
                self.content = content
                self.tool_calls = tool_calls
        msgs = [
            FakeMsg("system", "system prompt"),
            FakeMsg("user", "[2025-01-01 10:00] 真正的用户消息"),
            FakeMsg("assistant", "回复"),
            # This is a system-event user message (tool result, context injection, etc.)
            FakeMsg("user", "tool_result: {\"output\": \"file contents\"}"),
            FakeMsg("assistant", "处理完毕"),
        ]
        r.show_session_history(msgs, "zh")
        assert any("真正的用户消息" in line for line in tui._chat_lines)
        # The fake system-event user message should NOT appear
        assert not any("tool_result" in line for line in tui._chat_lines)
