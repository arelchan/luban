"""Load context files (agents.md, soul.md, memory.md) from workspace."""

from __future__ import annotations

from pathlib import Path

from agentkit.config.models import ContextConfig


class ContextLoader:
    """Loads context files from the workspace directory."""

    def __init__(self, config: ContextConfig):
        self._config = config
        self._workspace = Path(config.workspace_dir).expanduser().resolve()

    @property
    def workspace(self) -> Path:
        return self._workspace

    def load_all(self) -> dict[str, str | None]:
        """Load all context files. Returns {key: content_or_none}."""
        return {
            "soul": self._load_file(self._config.soul_file),
            "agents": self._load_file(self._config.agents_file),
            "memory": self._load_file(self._config.memory_file),
        }

    def _load_file(self, filename: str) -> str | None:
        """Load a single file, return None if not found."""
        path = self._workspace / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def get_watched_paths(self) -> list[Path]:
        """Return absolute paths of all context files for the watcher."""
        return [
            self._workspace / self._config.soul_file,
            self._workspace / self._config.agents_file,
            self._workspace / self._config.memory_file,
        ]
