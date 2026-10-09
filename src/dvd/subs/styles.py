"""Subtitle style templates: built-in ones and the user's own, by name.

A subtitle track names its style (`style:` in the project). The viewing profile then scales
it (text size, overscan margin), the same way for every style. User styles are YAML files in
%APPDATA%\\DVD Studyo\\styles (DVD_STYLE_DIR overrides it), holding only the fields that
differ from the default style.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any

import yaml

from dvd.subs.render import DEFAULT_STYLE, SubStyle

TEMPLATES: dict[str, dict[str, Any]] = {
    "varsayilan": {},
    "buyuk": {"size": 0.068, "outline_width": 0.0065},
    "sari": {"fill": (240, 220, 60)},  # yellow text, as on many older discs
    "ince": {"weight": 400, "outline_width": 0.0040},
    "kalin": {"weight": 700, "outline_width": 0.0070},
}
FIELDS = {f.name for f in fields(SubStyle)}


class StyleError(ValueError):
    pass


def style_folder() -> Path:
    if env := os.environ.get("DVD_STYLE_DIR"):
        return Path(env)
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "DVD Studyo" / "styles"


def _file(name: str, folder: Path | None) -> Path:
    if not re.fullmatch(r"[\w\- ]{1,40}", name):
        raise StyleError(f"style name {name!r} may only hold letters, digits, spaces, - and _")
    return (folder or style_folder()) / f"{name}.yaml"


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in values.items():
        if key not in FIELDS:
            raise StyleError(f"unknown style field {key!r}")
        default = getattr(DEFAULT_STYLE, key)
        if isinstance(default, tuple):
            value = tuple(int(c) for c in value)
            if len(value) != 3 or not all(0 <= c <= 255 for c in value):
                raise StyleError(f"{key} must be three values 0-255")
        else:
            value = type(default)(value)
        out[key] = value
    return out


def list_styles(folder: Path | None = None) -> list[str]:
    folder = folder or style_folder()
    users = sorted(p.stem for p in folder.glob("*.yaml")) if folder.is_dir() else []
    return [*TEMPLATES, *(u for u in users if u not in TEMPLATES)]


def load_style(name: str, folder: Path | None = None) -> SubStyle:
    if name in TEMPLATES:
        return replace(DEFAULT_STYLE, **TEMPLATES[name])
    path = _file(name, folder)
    if not path.is_file():
        raise StyleError(f"no subtitle style named {name!r}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return replace(DEFAULT_STYLE, **_clean(data))


def save_style(name: str, style: SubStyle, folder: Path | None = None) -> Path:
    if name in TEMPLATES:
        raise StyleError(f"{name!r} is a built-in style; save under another name")
    path = _file(name, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    changed = {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(style).items()
               if v != getattr(DEFAULT_STYLE, k)}  # fmt: skip
    path.write_text(yaml.safe_dump(changed, allow_unicode=True, sort_keys=True), encoding="utf-8")
    return path


def for_viewing(style: SubStyle, size: float, safe_area: float) -> SubStyle:
    """Scale a style for the viewing profile: larger text and a wider margin where the screen
    is small or the TV crops the picture edges (overscan)."""
    margin = (1 - safe_area) / 2
    return replace(
        style,
        size=style.size * size,
        bottom=max(style.bottom, margin + 0.02),
        max_width=min(style.max_width, safe_area - 0.04),
    )
