"""Layered profiles (docs/profiller.md): each layer sets some settings, later layers win.

    standard -> media -> content -> viewing -> audio -> user profile -> title overrides

Only settings the engine applies are listed here. Values are starting points that Phase 2
calibrates against the test corpus and reference discs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dvd.project.model import Profiles

# Setting -> (default, allowed values or type)
SETTINGS: dict[str, tuple[Any, Any]] = {
    "deband": (1, range(0, 5)),
    "dither": ("error_diffusion", ("error_diffusion", "ordered", "none")),
    "kernel": ("spline36", ("spline36", "lanczos", "bicubic")),
    "peak_kbps": (9_000, range(4_000, 9_801)),
    "subtitle_size": (1.0, float),  # multiplier on the default subtitle height
    "safe_area": (0.95, float),  # fraction of the frame kept clear of overscan
    "audio_channels": ("5.1", ("5.1", "2.0")),
    "audio_bitrate": (448, (192, 224, 256, 320, 384, 448)),
    "audio_extra_stereo": (False, bool),  # also add a stereo copy of the main track
}

CONTENT: dict[str, dict[str, Any]] = {
    "modern-film": {"deband": 1},
    "grenli-film": {"deband": 1},
    "eski-film": {"deband": 1},
    "animasyon-2d": {"deband": 3},
    "animasyon-3d": {"deband": 3},
    "dizi": {"deband": 1},
    "yayin": {"deband": 1},
    "icerik-4-3": {"deband": 1},
    "telefon": {"deband": 1},
    "kamera": {"deband": 1},
    "eski-kamera": {"deband": 1},
    "ekran-kaydi": {"deband": 2},
}
# Viewing settings; "deband" here is a shift on the content's level.
VIEWING: dict[str, dict[str, Any]] = {
    "modern-tv": {"peak_kbps": 9_000, "safe_area": 0.95},
    "projeksiyon": {"peak_kbps": 9_000, "safe_area": 0.95, "deband": +1},
    "crt": {"peak_kbps": 9_000, "safe_area": 0.875, "subtitle_size": 1.2, "deband": -1},
    "bilgisayar": {"peak_kbps": 9_500, "safe_area": 1.0},
    "konsol": {"peak_kbps": 8_000, "safe_area": 0.9},
    "tasinabilir": {"peak_kbps": 7_500, "safe_area": 0.9, "subtitle_size": 1.2, "deband": -1},
    "evrensel": {"peak_kbps": 8_000, "safe_area": 0.9},
}
AUDIO: dict[str, dict[str, Any]] = {
    "tv": {"audio_channels": "2.0", "audio_bitrate": 192},
    "5.1": {"audio_channels": "5.1", "audio_bitrate": 448},
    # Night mode compression comes with the audio work in Phase 3; until then it is 5.1.
    "gece": {"audio_channels": "5.1", "audio_bitrate": 448},
    "hepsi": {"audio_channels": "5.1", "audio_bitrate": 448, "audio_extra_stereo": True},
}


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Resolved:
    values: dict[str, Any]
    origin: dict[str, str]  # setting -> "default" | "content:x" | "viewing:x" | "user:x" | ...

    def __getitem__(self, key: str) -> Any:
        return self.values[key]


def validate(key: str, value: Any) -> Any:
    if key not in SETTINGS:
        raise ProfileError(f"unknown setting {key!r}")
    _, allowed = SETTINGS[key]
    if allowed is float:
        return float(value)
    if allowed is bool:
        return bool(value)
    if isinstance(value, str) and isinstance(next(iter(allowed)), int):
        value = int(value.rstrip("k"))
    if value not in allowed:
        raise ProfileError(f"{key} cannot be {value!r}")
    return value


def user_profile_dir() -> Path:
    env = os.environ.get("DVD_PROFILE_DIR")
    if env:
        return Path(env)
    return Path(os.environ.get("APPDATA", Path.home())) / "DVD Studyo" / "profiles"


def load_user_profile(name: str, folder: Path | None = None) -> dict[str, Any]:
    path = (folder or user_profile_dir()) / f"{name}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ProfileError(f"user profile {name!r} not found in {path.parent}") from None
    settings = data.get("settings", {}) if isinstance(data, dict) else {}
    return {k: validate(k, v) for k, v in settings.items()}


def save_user_profile(name: str, settings: dict[str, Any], folder: Path | None = None) -> Path:
    clean = {k: validate(k, v) for k, v in settings.items()}
    path = (folder or user_profile_dir()) / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump({"name": name, "settings": clean}, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return path


def list_user_profiles(folder: Path | None = None) -> list[str]:
    folder = folder or user_profile_dir()
    return sorted(p.stem for p in folder.glob("*.yaml")) if folder.is_dir() else []


def resolve(
    profiles: Profiles,
    overrides: dict[str, Any] | None = None,
    user_folder: Path | None = None,
) -> Resolved:
    user = profiles.user
    values = {k: default for k, (default, _) in SETTINGS.items()}
    origin = dict.fromkeys(values, "default")

    def apply(layer: str, settings: dict[str, Any], shift: tuple[str, ...] = ()) -> None:
        for key, value in settings.items():
            if key in shift:
                values[key] = min(4, max(0, values[key] + value))
            else:
                values[key] = value
            origin[key] = layer

    apply(f"content:{profiles.content}", CONTENT.get(profiles.content, {}))
    apply(f"viewing:{profiles.viewing}", VIEWING.get(profiles.viewing, {}), shift=("deband",))
    apply(f"audio:{profiles.audio}", AUDIO.get(profiles.audio, {}))
    if user:
        apply(f"user:{user}", load_user_profile(user, user_folder))
    if overrides:
        apply("override", {k: validate(k, v) for k, v in overrides.items()})
    return Resolved(values, origin)
