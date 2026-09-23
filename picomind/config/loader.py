"""Load and save PicoMind TOML configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import tomlkit
from loguru import logger
from pydantic import ValidationError

from picomind.config.schema import Config

_current_config_path: Path | None = None


def set_config_path(path: Path | None) -> None:
    """Set the active config path for the current process."""

    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Return the active config path."""

    if _current_config_path:
        return _current_config_path
    return Path.home() / ".picomind" / "config.toml"


def load_config(config_path: Path | None = None) -> Config:
    """Load a TOML config, returning defaults when it does not exist."""

    path = config_path or get_config_path()
    if not path.exists():
        return Config()

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        return Config.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValidationError, ValueError) as exc:
        logger.warning("Failed to load config from {}: {}", path, exc)
        logger.warning("Using default PicoMind configuration.")
        return Config()


def _remove_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _remove_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_remove_none(item) for item in value]
    return value


def save_config(config: Config, config_path: Path | None = None) -> None:
    """Write configuration as UTF-8 TOML."""

    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _remove_none(config.model_dump(mode="json"))
    text = tomlkit.dumps(data)
    path.write_text(text, encoding="utf-8")
