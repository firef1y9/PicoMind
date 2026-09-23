"""Runtime path helpers."""

from __future__ import annotations

import os
from pathlib import Path

from picomind.config.loader import get_config_path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_dir() -> Path:
    return ensure_dir(get_config_path().parent)


def get_logs_dir() -> Path:
    return ensure_dir(get_data_dir() / "logs")


def get_cli_history_path() -> Path:
    return get_data_dir() / "history" / "cli_history"


def resolve_workspace(workspace: str | Path | None = None) -> Path:
    configured = workspace or os.getenv("PICOMIND_WORKSPACE") or "~/.picomind/workspace"
    return ensure_dir(Path(configured).expanduser().resolve())
