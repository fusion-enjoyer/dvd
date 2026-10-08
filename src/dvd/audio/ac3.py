"""AC-3 encode of one source audio track with FFmpeg: 48 kHz, DVD channel layouts, PAL speedup."""

from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path

from dvd import toolchain


class AudioError(Exception):
    pass


def ffmpeg_args(
    source: Path,
    stream_index: int,
    out: Path,
    channels: str,
    bitrate: int,
    speedup: Fraction = Fraction(1),
) -> list[str]:
    filters = []
    if speedup != 1:
        # Keep the pitch: the film plays 4% faster on PAL but voices should not rise a semitone.
        filters.append(f"atempo={float(speedup):.10f}")
    args = [
        "-v", "error", "-y", "-i", str(source),
        "-map", f"0:{stream_index}", "-vn", "-sn", "-dn",
        "-c:a", "ac3", "-b:a", f"{bitrate}k",
        "-ac", "6" if channels == "5.1" else "2",
        "-ar", "48000",
    ]  # fmt: skip
    if filters:
        args += ["-af", ",".join(filters)]
    return [*args, str(out)]


def encode_ac3(
    source: Path,
    stream_index: int,
    out: Path,
    channels: str,
    bitrate: int,
    speedup: Fraction = Fraction(1),
    ffmpeg: Path | None = None,
) -> Path:
    ffmpeg = ffmpeg or toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise AudioError("ffmpeg not found")
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(ffmpeg), *ffmpeg_args(source, stream_index, out, channels, bitrate, speedup)],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0 or not out.is_file():
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise AudioError(f"AC-3 encode of stream {stream_index} failed: {message}")
    return out
