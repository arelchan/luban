"""Tests for agentkit.context — ContextLoader, ContextInjector."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentkit.config.models import ContextConfig, MemoryConfig
from agentkit.context.injector import ContextInjector
from agentkit.context.loader import ContextLoader
from agentkit.memory.short_term import ShortTermMemory


# ─── ContextLoader ───


class TestContextLoader:
    def test_load_all_from_empty_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            config = ContextConfig(workspace_dir=td)
            loader = ContextLoader(config)
            context = loader.load_all()
            assert context["soul"] is None
            assert context["agents"] is None
            assert context["memory"] is None

    def test_load_all_with_files(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "soul.md").write_text("You are a helpful agent.", encoding="utf-8")
            (Path(td) / "agents.md").write_text("Follow instructions.", encoding="utf-8")
            (Path(td) / "memory.md").write_text("User prefers Python.", encoding="utf-8")

            config = ContextConfig(workspace_dir=td)
            loader = ContextLoader(config)
            context = loader.load_all()

            assert context["soul"] == "You are a helpful agent."
            assert context["agents"] == "Follow instructions."
            assert context["memory"] == "User prefers Python."

    def test_load_partial(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "soul.md").write_text("persona", encoding="utf-8")

            config = ContextConfig(workspace_dir=td)
            loader = ContextLoader(config)
            context = loader.load_all()

            assert context["soul"] == "persona"
            assert context["agents"] is None
            assert context["memory"] is None

    def test_get_watched_paths(self):
        with tempfile.TemporaryDirectory() as td:
            config = ContextConfig(workspace_dir=td)
            loader = ContextLoader(config)
            paths = loader.get_watched_paths()
            assert len(paths) == 3
            assert all(isinstance(p, Path) for p in paths)

    def test_workspace_property(self):
        config = ContextConfig(workspace_dir="/tmp/test_workspace")
        loader = ContextLoader(config)
        # On macOS /tmp is a symlink to /private/tmp, so use resolve()
        assert loader.workspace == Path("/tmp/test_workspace").resolve()


# ─── ContextInjector ───


class TestContextInjector:
    def test_build_system_messages_all_files(self):
        injector = ContextInjector()
        msgs = injector.build_system_messages({
            "soul": "You are an assistant.",
            "agents": "Help users.",
            "memory": "User likes Go.",
        })
        # All sections merged into a single system message
        assert len(msgs) == 1
        content = msgs[0].content
        assert "You are an assistant." in content
        assert "Help users." in content
        assert "Long-term Memory" in content

    def test_build_system_messages_empty_context(self):
        injector = ContextInjector()
        msgs = injector.build_system_messages({"soul": None, "agents": None, "memory": None})
        assert len(msgs) == 1
        from agentkit import APP_NAME
        assert APP_NAME in msgs[0].content

    def test_build_system_messages_partial(self):
        injector = ContextInjector()
        msgs = injector.build_system_messages({"soul": "persona", "agents": None, "memory": None})
        assert len(msgs) == 1
        assert msgs[0].content == "persona"

    def test_inject_into_memory(self):
        injector = ContextInjector()
        config = MemoryConfig()
        mem = ShortTermMemory(config)

        injector.inject({"soul": "You are helpful.", "agents": None, "memory": None}, mem)
        sys_msgs = mem.get_system_messages()
        assert len(sys_msgs) == 1
        assert sys_msgs[0].content == "You are helpful."

    def test_inject_replaces_previous(self):
        injector = ContextInjector()
        config = MemoryConfig()
        mem = ShortTermMemory(config)

        injector.inject({"soul": "v1", "agents": None, "memory": None}, mem)
        assert mem.get_system_messages()[0].content == "v1"

        injector.inject({"soul": "v2", "agents": None, "memory": None}, mem)
        assert mem.get_system_messages()[0].content == "v2"
