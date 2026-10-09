"""Choice of MPEG-2 encoder: HCEnc (default) or FFmpeg."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import vapoursynth as vs

from dvd import toolchain
from dvd.video import ffmpeg_enc, hcenc
from dvd.video.hcenc import EncodeSettings

ENCODERS = {"hcenc": hcenc.encode, "ffmpeg": ffmpeg_enc.encode}


def hcenc_available() -> bool:
    dirs = toolchain.tool_dirs()
    return all(toolchain.find_executable([p], dirs) for p in ("HCenc_*.exe", "DvdSource.dll"))


def choose(wanted: str) -> tuple[str, str | None]:
    """The encoder to use and a warning when it differs from the one asked for."""
    if wanted == "hcenc" and not hcenc_available():
        return "ffmpeg", "HCEnc is not installed; encoded with FFmpeg"
    return wanted, None


def encode(
    name: str,
    clip: vs.VideoNode,
    out: Path,
    settings: EncodeSettings,
    workdir: Path,
    progress: Callable[[float], None] | None = None,
) -> Path:
    return ENCODERS[name](clip, out, settings, workdir, progress)
