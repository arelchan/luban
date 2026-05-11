"""Tests for agentkit.tools — native decorator, builtin tools, schema, manager."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from agentkit.tools.native import NativeTool, _build_schema, clear_registry, get_registered_tools, tool


# ─── @tool decorator ───


class TestToolDecorator:
    def setup_method(self):
        clear_registry()

    def teardown_method(self):
        clear_registry()

    def test_basic_registration(self):
        @tool
        def my_tool(x: str) -> str:
            """Do something."""
            return x

        registry = get_registered_tools()
        assert "my_tool" in registry
        assert registry["my_tool"].description == "Do something."

    def test_custom_name_and_description(self):
        @tool(name="custom_name", description="Custom desc")
        def fn(a: int) -> str:
            """Ignored docstring."""
            return str(a)

        registry = get_registered_tools()
        assert "custom_name" in registry
        assert registry["custom_name"].description == "Custom desc"

    def test_schema_generation_basic_types(self):
        @tool
        def typed_fn(name: str, count: int, flag: bool = False) -> str:
            """Test."""
            return ""

        registry = get_registered_tools()
        schema = registry["typed_fn"].schema
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"
        assert schema["properties"]["flag"]["type"] == "boolean"
        assert "name" in schema["required"]
        assert "count" in schema["required"]
        assert "flag" not in schema["required"]

    def test_clear_registry(self):
        @tool
        def temp_tool() -> str:
            """Temp."""
            return ""

        assert "temp_tool" in get_registered_tools()
        clear_registry()
        assert "temp_tool" not in get_registered_tools()


# ─── Built-in tools ───


class TestBuiltinTools:
    """Tests for the 11 built-in tools in agentkit.tools.builtin."""

    def setup_method(self):
        # Re-register builtin tools (clear_registry in TestToolDecorator tears them down)
        import importlib
        import agentkit.tools.builtin.files
        import agentkit.tools.builtin.shell
        import agentkit.tools.builtin.search
        import agentkit.tools.builtin.utility
        import agentkit.tools.builtin.web
        import agentkit.tools.builtin.tasks
        import agentkit.tools.builtin.session
        import agentkit.tools.builtin.memory
        import agentkit.tools.builtin.agents
        for mod in [
            agentkit.tools.builtin.files,
            agentkit.tools.builtin.shell,
            agentkit.tools.builtin.search,
            agentkit.tools.builtin.utility,
            agentkit.tools.builtin.web,
            agentkit.tools.builtin.tasks,
            agentkit.tools.builtin.session,
            agentkit.tools.builtin.memory,
            agentkit.tools.builtin.agents,
        ]:
            importlib.reload(mod)

    def test_builtin_tools_registered(self):
        registry = get_registered_tools()
        expected = {
            "read_file", "write_file", "edit_file", "run_command",
            "glob_files", "grep_files", "list_directory",
            "get_current_time", "calculate", "web_fetch", "web_search",
        }
        assert expected.issubset(set(registry.keys())), f"Missing: {expected - set(registry.keys())}"

    def test_calculate_basic(self):
        from agentkit.tools.builtin import calculate

        assert calculate("2+2") == "4"
        assert calculate("10/3") == str(10 / 3)
        assert calculate("2**10") == "1024"

    def test_calculate_invalid(self):
        from agentkit.tools.builtin import calculate

        result = calculate("import os")
        assert "Error" in result

    def test_get_current_time(self):
        from agentkit.tools.builtin import get_current_time

        result = get_current_time()
        assert "UTC" in result
        # Should have date format
        assert "-" in result

    def test_read_file_not_found(self):
        from agentkit.tools.builtin import read_file

        result = read_file("/nonexistent/path/xyz.txt")
        assert "Error" in result

    def test_read_file_success(self):
        from agentkit.tools.builtin import read_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            f.flush()
            path = f.name

        try:
            result = read_file(path)
            assert "line1" in result
            assert "line2" in result
            # Check line numbers
            assert "1│" in result
        finally:
            os.unlink(path)

    def test_read_file_with_offset_and_limit(self):
        from agentkit.tools.builtin import read_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("a\nb\nc\nd\ne\n")
            f.flush()
            path = f.name

        try:
            result = read_file(path, offset=2, limit=2)
            assert "c" in result
            assert "d" in result
            assert "a" not in result
            assert "e" not in result
        finally:
            os.unlink(path)

    def test_write_file(self):
        from agentkit.tools.builtin import write_file

        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "sub" / "test.txt")
            result = write_file(path, "hello world")
            assert "Successfully" in result
            assert Path(path).read_text() == "hello world"

    def test_edit_file_success(self):
        from agentkit.tools.builtin import edit_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("foo bar baz")
            f.flush()
            path = f.name

        try:
            result = edit_file(path, "bar", "BAR")
            assert "Successfully" in result
            assert Path(path).read_text() == "foo BAR baz"
        finally:
            os.unlink(path)

    def test_edit_file_not_unique(self):
        from agentkit.tools.builtin import edit_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("aaa aaa")
            f.flush()
            path = f.name

        try:
            result = edit_file(path, "aaa", "bbb")
            assert "2 times" in result
        finally:
            os.unlink(path)

    def test_edit_file_not_found_string(self):
        from agentkit.tools.builtin import edit_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello")
            f.flush()
            path = f.name

        try:
            result = edit_file(path, "xyz", "abc")
            assert "not found" in result
        finally:
            os.unlink(path)

    def test_run_command(self):
        from agentkit.tools.builtin import run_command

        result = run_command("echo hello")
        assert "hello" in result

    def test_run_command_timeout(self):
        from agentkit.tools.builtin import run_command

        result = run_command("sleep 10", timeout=1)
        assert "timed out" in result

    def test_run_command_exit_code(self):
        from agentkit.tools.builtin import run_command

        result = run_command("exit 42")
        assert "exit code: 42" in result

    def test_glob_files(self):
        from agentkit.tools.builtin import glob_files

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.py").write_text("x")
            (Path(td) / "b.py").write_text("y")
            (Path(td) / "c.txt").write_text("z")

            result = glob_files("*.py", path=td)
            assert "a.py" in result
            assert "b.py" in result
            assert "c.txt" not in result

    def test_glob_files_no_match(self):
        from agentkit.tools.builtin import glob_files

        with tempfile.TemporaryDirectory() as td:
            result = glob_files("*.xyz", path=td)
            assert "No files" in result

    def test_grep_files(self):
        from agentkit.tools.builtin import grep_files

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "test.py").write_text("def hello():\n    pass\n")
            result = grep_files("hello", path=td)
            assert "hello" in result
            assert "test.py" in result

    def test_grep_files_no_match(self):
        from agentkit.tools.builtin import grep_files

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "test.py").write_text("nothing here")
            result = grep_files("nonexistent_pattern_xyz", path=td)
            assert "No matches" in result

    def test_list_directory(self):
        from agentkit.tools.builtin import list_directory

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "file.txt").write_text("content")
            (Path(td) / "subdir").mkdir()

            result = list_directory(td)
            assert "subdir/" in result
            assert "file.txt" in result

    def test_list_directory_not_found(self):
        from agentkit.tools.builtin import list_directory

        result = list_directory("/nonexistent_dir_xyz")
        assert "Error" in result


# ─── Tool Schema ───


class TestToolSchema:
    def test_native_tool_to_openai_schema(self):
        from agentkit.tools.schema import native_tool_to_openai_schema

        nt = NativeTool(
            func=lambda x: x,
            name="test_tool",
            description="A test tool",
            schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        )
        schema = native_tool_to_openai_schema(nt)
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test_tool"
        assert schema["function"]["description"] == "A test tool"
        assert schema["function"]["parameters"]["properties"]["x"]["type"] == "string"

    def test_mcp_tool_to_openai_schema(self):
        from agentkit.tools.schema import mcp_tool_to_openai_schema

        schema = mcp_tool_to_openai_schema(
            server_name="filesystem",
            tool_name="read",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        assert schema["function"]["name"] == "filesystem__read"
        assert schema["function"]["description"] == "Read a file"


# ─── ToolManager ───


class TestToolManager:
    def setup_method(self):
        import importlib
        import agentkit.tools.builtin.files
        import agentkit.tools.builtin.shell
        import agentkit.tools.builtin.search
        import agentkit.tools.builtin.utility
        import agentkit.tools.builtin.web
        import agentkit.tools.builtin.tasks
        import agentkit.tools.builtin.session
        import agentkit.tools.builtin.memory
        import agentkit.tools.builtin.agents
        for mod in [
            agentkit.tools.builtin.files, agentkit.tools.builtin.shell,
            agentkit.tools.builtin.search, agentkit.tools.builtin.utility,
            agentkit.tools.builtin.web, agentkit.tools.builtin.tasks,
            agentkit.tools.builtin.session, agentkit.tools.builtin.memory,
            agentkit.tools.builtin.agents,
        ]:
            importlib.reload(mod)

    @pytest.mark.asyncio
    async def test_initialize_native_tools(self):
        from agentkit.config.models import ToolsConfig
        from agentkit.tools.manager import ToolManager

        config = ToolsConfig(enable_native=True, mcp_servers=[])
        manager = ToolManager(config)
        await manager.initialize()

        schemas = manager.get_tool_schemas()
        assert len(schemas) >= 19  # We have 19 builtin tools
        names = [s["function"]["name"] for s in schemas]
        assert "calculate" in names
        assert "read_file" in names

    @pytest.mark.asyncio
    async def test_execute_native_tool(self):
        from agentkit.config.models import ToolsConfig
        from agentkit.tools.manager import ToolManager

        config = ToolsConfig(enable_native=True, mcp_servers=[])
        manager = ToolManager(config)
        await manager.initialize()

        result = await manager.execute_tool("calculate", {"expression": "7*6"})
        assert result == "42"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        from agentkit.config.models import ToolsConfig
        from agentkit.tools.manager import ToolManager

        config = ToolsConfig(enable_native=True, mcp_servers=[])
        manager = ToolManager(config)
        await manager.initialize()

        result = await manager.execute_tool("nonexistent_tool", {})
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_list_tools_with_lang(self):
        from agentkit.config.models import ToolsConfig
        from agentkit.tools.manager import ToolManager

        config = ToolsConfig(enable_native=True, mcp_servers=[])
        manager = ToolManager(config)
        await manager.initialize()

        # Chinese
        tools_zh = manager.list_tools(lang="zh")
        calc_zh = next(t for t in tools_zh if t["name"] == "calculate")
        assert "数学" in calc_zh["description"]

        # English (uses original docstring)
        tools_en = manager.list_tools(lang="en")
        calc_en = next(t for t in tools_en if t["name"] == "calculate")
        assert "Evaluate" in calc_en["description"]

    @pytest.mark.asyncio
    async def test_disabled_native_tools(self):
        from agentkit.config.models import ToolsConfig
        from agentkit.tools.manager import ToolManager

        config = ToolsConfig(enable_native=False, mcp_servers=[])
        manager = ToolManager(config)
        await manager.initialize()

        schemas = manager.get_tool_schemas()
        assert schemas == []

    @pytest.mark.asyncio
    async def test_rename_session_tool(self):
        from agentkit.config.models import ToolsConfig
        from agentkit.tools.manager import ToolManager
        from agentkit.tools.builtin import set_session_context

        # Mock session context
        class FakeSession:
            id = "test123"
            title = "old title"

        fake_session = FakeSession()
        updated_titles = {}

        class FakeStore:
            def update_meta(self, session_id, **kwargs):
                updated_titles[session_id] = kwargs.get("title", "")

        set_session_context(
            session_store=FakeStore(),
            current_session_getter=lambda: fake_session,
            current_session_setter=lambda t: setattr(fake_session, "title", t),
        )

        config = ToolsConfig(enable_native=True, mcp_servers=[])
        manager = ToolManager(config)
        await manager.initialize()

        result = await manager.execute_tool("rename_session", {"title": "新标题"})
        assert "新标题" in result
        assert fake_session.title == "新标题"
        assert updated_titles["test123"] == "新标题"

    @pytest.mark.asyncio
    async def test_rename_session_no_context(self):
        from agentkit.config.models import ToolsConfig
        from agentkit.tools.manager import ToolManager
        from agentkit.tools.builtin import _session_context

        # Clear context
        _session_context.clear()

        config = ToolsConfig(enable_native=True, mcp_servers=[])
        manager = ToolManager(config)
        await manager.initialize()

        result = await manager.execute_tool("rename_session", {"title": "test"})
        assert "Error" in result
