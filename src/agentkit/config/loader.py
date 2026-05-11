"""Load and save AgentKit configuration from TOML files."""

from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

from agentkit.config.models import AgentKitConfig

CONFIG_DIR = Path("~/.agentkit").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.toml"


def get_config_path() -> Path:
    """Return the path to the config file."""
    return CONFIG_FILE


def load_config(path: Path | None = None) -> AgentKitConfig:
    """Load config from a TOML file. Returns default config if file doesn't exist."""
    config_path = path or CONFIG_FILE
    if not config_path.exists():
        return AgentKitConfig()

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    return AgentKitConfig.model_validate(data)


def save_config(config: AgentKitConfig, path: Path | None = None) -> None:
    """Save config to a TOML file."""
    config_path = path or CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(exclude_none=True)
    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)
