r"""User settings shared by all projects (%APPDATA%\DVD Studyo\settings.yaml; DVD_SETTINGS
points elsewhere). Secrets such as the TMDB key live here, never in a project file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def settings_file() -> Path:
    if env := os.environ.get("DVD_SETTINGS"):
        return Path(env)
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "DVD Studyo" / "settings.yaml"


def load() -> dict[str, Any]:
    path = settings_file()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def save(values: dict[str, Any]) -> None:
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {**load(), **values}
    path.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=True), encoding="utf-8")


def tmdb_key() -> str:
    """DVD_TMDB_KEY wins over the saved key."""
    return os.environ.get("DVD_TMDB_KEY") or str(load().get("tmdb_key") or "")
