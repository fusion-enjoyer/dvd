"""Pull an embedded text subtitle track out of a source file as SRT."""

from __future__ import annotations

import subprocess
from pathlib import Path

from dvd import toolchain
from dvd.subs.srt import SubtitleError


def extract_text_track(source: Path, stream_index: int, out: Path) -> Path:
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise SubtitleError("ffmpeg not found")
    proc = subprocess.run(
        [str(ffmpeg), "-v", "error", "-y", "-i", str(source),
         "-map", f"0:{stream_index}", "-c:s", "srt", str(out)],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise SubtitleError(f"cannot extract subtitle stream {stream_index}: {message}")
    return out
