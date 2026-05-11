"""Plugin system for Luban.

Plugins live in ~/.agentkit/workspace/plugins/<name>/ and are loaded at startup.
Each plugin directory must contain:
  - plugin.toml  — metadata and plugin-specific config
  - __init__.py  — must implement setup(context: PluginContext) -> PluginHooks

Plugins are completely isolated from Luban's core — any exception inside a
plugin is caught and logged as a warning; it never propagates to the main flow.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-reattr]

logger = logging.getLogger(__name__)

_DEFAULT_PLUGINS_DIR = Path("~/.agentkit/workspace/plugins")


# ── Public types plugins must conform to ─────────────────────────────────────


@dataclass
class PluginContext:
    """Runtime context passed to a plugin's setup() function.

    Plugins receive read-only information about the running Luban instance.
    They must not import or depend on Luban internals directly.
    """

    plugin_id: str          # Directory name, e.g. "friday-tracing"
    config: dict[str, Any]  # Contents of [config] in plugin.toml
    app_version: str        # Luban version string
    plugins_dir: Path       # Absolute path to ~/.agentkit/workspace/plugins/


@dataclass
class PluginHooks:
    """Hooks a plugin can register.

    All fields are optional. Unregistered hooks are simply not called.
    Hooks must not raise — wrap internal errors inside the hook function itself.

    on_span_end(span_dict):
        Called each time a tracing span ends. span_dict is the serialized span
        (same structure as what the /api/spans dashboard endpoint returns).
        Use this for real-time trace forwarding (e.g. Friday Tracing upload).

    on_session_end(session_id):
        Called when the CLI session exits normally. Use for cleanup or
        final batch uploads.
    """

    on_span_end: Callable[[dict[str, Any]], None] | None = None
    on_session_end: Callable[[str], None] | None = None


# ── Internal plugin record ────────────────────────────────────────────────────


@dataclass
class _LoadedPlugin:
    plugin_id: str
    hooks: PluginHooks
    meta: dict[str, Any]  # Full plugin.toml contents


# ── PluginManager ─────────────────────────────────────────────────────────────


class PluginManager:
    """Discovers, loads, and dispatches hooks for all installed plugins.

    Usage in app.py:
        plugin_manager = PluginManager()
        plugin_manager.load_all()
        tracer.on_span_end = plugin_manager.dispatch_span_end

    Calling dispatch_span_end / dispatch_session_end will fan-out to all
    plugins that registered the corresponding hook, in load order.
    Each individual plugin's exception is caught and logged — it never
    stops other plugins or the main flow.
    """

    def __init__(self, plugins_dir: Path | None = None):
        self._dir = (plugins_dir or _DEFAULT_PLUGINS_DIR).expanduser().resolve()
        self._plugins: list[_LoadedPlugin] = []

    # ── Loading ───────────────────────────────────────────────────────────────

    def load_all(self) -> None:
        """Scan plugins directory and load every enabled plugin."""
        if not self._dir.exists():
            return

        for plugin_dir in sorted(self._dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            plugin_id = plugin_dir.name
            try:
                self._load_one(plugin_id, plugin_dir)
            except Exception as exc:
                logger.warning("[plugin:%s] failed to load: %s", plugin_id, exc)

    def _load_one(self, plugin_id: str, plugin_dir: Path) -> None:
        """Load a single plugin. Raises on any error (caller catches)."""
        # 1. Read plugin.toml
        toml_path = plugin_dir / "plugin.toml"
        if not toml_path.exists():
            raise FileNotFoundError(f"missing plugin.toml in {plugin_dir}")

        with open(toml_path, "rb") as f:
            meta = tomllib.load(f)

        # 2. Check enabled flag (default True)
        plugin_section = meta.get("plugin", {})
        if not plugin_section.get("enabled", True):
            logger.debug("[plugin:%s] disabled, skipping", plugin_id)
            return

        # 3. Load __init__.py
        init_path = plugin_dir / "__init__.py"
        if not init_path.exists():
            raise FileNotFoundError(f"missing __init__.py in {plugin_dir}")

        spec = importlib.util.spec_from_file_location(
            f"luban_plugin_{plugin_id}", init_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot create module spec for {init_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        # 4. Call setup()
        if not hasattr(module, "setup"):
            raise AttributeError(f"plugin {plugin_id} has no setup() function")

        from agentkit import __version__
        context = PluginContext(
            plugin_id=plugin_id,
            config=meta.get("config", {}),
            app_version=__version__,
            plugins_dir=self._dir,
        )

        hooks = module.setup(context)
        if not isinstance(hooks, PluginHooks):
            raise TypeError(
                f"plugin {plugin_id} setup() must return PluginHooks, got {type(hooks)}"
            )

        self._plugins.append(_LoadedPlugin(plugin_id=plugin_id, hooks=hooks, meta=meta))
        logger.info("[plugin:%s] loaded", plugin_id)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def loaded_plugins(self) -> list[str]:
        return [p.plugin_id for p in self._plugins]

    @property
    def has_plugins(self) -> bool:
        return bool(self._plugins)

    # ── Dispatchers ───────────────────────────────────────────────────────────

    def dispatch_span_end(self, span_dict: dict[str, Any]) -> None:
        """Fan-out on_span_end to all plugins that registered it."""
        for plugin in self._plugins:
            if plugin.hooks.on_span_end is None:
                continue
            try:
                plugin.hooks.on_span_end(span_dict)
            except Exception as exc:
                logger.warning(
                    "[plugin:%s] on_span_end raised: %s", plugin.plugin_id, exc
                )
                from agentkit.events import emit_system_event
                emit_system_event(f"插件 {plugin.plugin_id} 执行出错：{exc}")

    def dispatch_session_end(self, session_id: str) -> None:
        """Fan-out on_session_end to all plugins that registered it."""
        for plugin in self._plugins:
            if plugin.hooks.on_session_end is None:
                continue
            try:
                plugin.hooks.on_session_end(session_id)
            except Exception as exc:
                logger.warning(
                    "[plugin:%s] on_session_end raised: %s", plugin.plugin_id, exc
                )
                from agentkit.events import emit_system_event
                emit_system_event(f"插件 {plugin.plugin_id} 执行出错：{exc}")
