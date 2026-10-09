"""Choice of MPEG-2 encoder: HCEnc (default) or FFmpeg."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import vapoursynth as vs

from dvd import toolchain
from dvd.video import ffmpeg_enc, hcenc
from dvd.video.hcenc import EncodeError, EncodeSettings

ENCODERS = {"hcenc": hcenc.encode, "ffmpeg": ffmpeg_enc.encode}


def hcenc_available() -> bool:
    dirs = toolchain.tool_dirs()
    return all(toolchain.find_executable([p], dirs) for p in ("HCenc_*.exe", "DvdSource.dll"))


def choose(wanted: str, pulldown: bool) -> tuple[str, str | None]:
    """The encoder to use and a warning when it differs from the one asked for."""
    if wanted == "hcenc" and not hcenc_available():
        if pulldown:
            raise EncodeError("NTSC film needs HCEnc, which is not installed")
        return "ffmpeg", "HCEnc is not installed; encoded with FFmpeg"
    if wanted == "ffmpeg" and pulldown:
        return "hcenc", "FFmpeg cannot write soft pulldown; encoded NTSC film with HCEnc"
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
