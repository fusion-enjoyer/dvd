"""Chapter suggestions: points every N minutes, each moved to the nearest scene cut.

Only a window around each wanted point is decoded, by FFmpeg seeking straight to it and
scaling to 64×36 grey, so a feature film takes about a second per chapter and the whole file
is never indexed. A cut is the frame whose picture differs most from the one before it; when
nothing in the window looks like a cut (a long take), the wanted point is kept.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import numpy as np

from dvd import toolchain
from dvd.probe import VideoTrack

WINDOW = 15.0  # seconds searched on each side of a wanted point
MIN_CUT = 0.06  # mean absolute difference (0..1) that counts as a cut
SMALL = (64, 36)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def window_frames(source: Path, v: VideoTrack, start: float, seconds: float) -> np.ndarray:
    """(frames, 36, 64) grey pictures from `start` for `seconds`, at the source's rate."""
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found; run `dvd doctor`")
    w, h = SMALL
    proc = subprocess.run(
        [str(ffmpeg), "-v", "error", "-nostdin", "-ss", f"{max(0.0, start):.3f}",
         "-t", f"{seconds:.3f}", "-i", str(source), "-map", f"0:{v.index}", "-an", "-sn",
         "-vf", f"scale={w}:{h}:flags=bilinear,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, creationflags=_NO_WINDOW,
    )  # fmt: skip
    frames = len(proc.stdout) // (w * h)
    return np.frombuffer(proc.stdout[: frames * w * h], np.uint8).reshape(frames, h, w)


def cut_in(frames: np.ndarray, fps: float, start: float, at: float, window: float) -> float:
    """The scene cut nearest `at` among `frames` (the first one shown at `start`)."""
    if len(frames) < 2:
        return at
    diffs = np.abs(frames[1:].astype(np.int16) - frames[:-1]).mean(axis=(1, 2)) / 255
    times = start + np.arange(1, len(frames)) / fps
    # Prefer cuts closer to the wanted point when two are about as strong.
    scores = diffs - 0.01 * np.abs(times - at) / window
    best = int(np.argmax(scores))
    return at if scores[best] <= MIN_CUT else float(times[best])


def suggest_chapters(
    source: Path,
    v: VideoTrack,
    duration: float,
    every_minutes: float = 5.0,
    progress: Callable[[float], None] | None = None,
    window: float = WINDOW,
) -> list[float]:
    """Chapter starts in source seconds: 0, then about every `every_minutes`, on scene cuts."""
    fps = float(v.playback_fps or v.fps or 25)
    step = every_minutes * 60
    gap = min(30.0, step / 2)  # no chapter this close to another one or to the end
    wanted = [i * step for i in range(1, int(duration // step) + 1) if i * step < duration - gap]
    times = [0.0]
    for i, at in enumerate(wanted):
        start = max(0.0, at - window)
        frames = window_frames(source, v, start, at + window - start)
        cut = cut_in(frames, fps, start, at, window)
        if cut - times[-1] > gap and cut < duration - gap:
            times.append(round(cut, 3))
        if progress:
            progress((i + 1) / len(wanted))
    return times
