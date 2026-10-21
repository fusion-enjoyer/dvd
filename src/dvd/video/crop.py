"""Black-bar detection: how many rows and columns are black in every sampled frame."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import vapoursynth as vs

from dvd.probe import VideoTrack
from dvd.project.model import Crop

core = vs.core

SAMPLES = 24
DARK_FRAME = 0.12  # frames darker than this on average (fades, night scenes) are skipped
BAR_LEVEL = 0.035  # a line is black if its average is within this of black and
BAR_PEAK = 0.12  # no more than a few pixels rise above this (grain, compression noise)


def _black_lines(luma: np.ndarray, black: float, white: float, axis: int) -> np.ndarray:
    """Boolean per row (axis=1) or column (axis=0): is this line black?"""
    span = white - black
    level = (luma.mean(axis=axis) - black) / span
    peak = (np.percentile(luma, 98, axis=axis) - black) / span
    return (level <= BAR_LEVEL) & (peak <= BAR_PEAK)


def _run(flags: np.ndarray) -> int:
    """Length of the run of True values at the start."""
    false = np.flatnonzero(~flags)
    return int(false[0]) if len(false) else len(flags)


def bars_in_frame(luma: np.ndarray, black: float, white: float) -> tuple[int, int, int, int]:
    rows = _black_lines(luma, black, white, axis=1)
    cols = _black_lines(luma, black, white, axis=0)
    return _run(cols), _run(cols[::-1]), _run(rows), _run(rows[::-1])  # left, right, top, bottom


def detect_crop(source: Path, v: VideoTrack, samples: int = SAMPLES,
                duration: float | None = None) -> Crop | None:  # fmt: skip
    """Bars present in all bright-enough sampled frames, rounded down to even sizes.

    None when too few frames are bright enough to tell (a very dark film or a short clip).
    With `duration` the frames are taken by seeking (fast, no index of the whole file).
    """
    if duration:
        from dvd.video.frames import grab

        times = [duration * (0.05 + 0.9 * i / max(1, samples - 1)) for i in range(samples)]
        clips = [grab(source, v, at) for at in times]
    else:
        clip = core.bs.VideoSource(str(source), track=v.index)
        n = clip.num_frames
        picks = sorted({int(n * (0.05 + 0.9 * i / max(1, samples - 1))) for i in range(samples)})
        clips = [clip[min(p, n - 1)] for p in picks]
    depth = clips[0].format.bits_per_sample
    scale = 1 << (depth - 8)
    full = v.color_range == "pc"
    black, white = (0, 255 * scale) if full else (16 * scale, 235 * scale)
    positions = clips
    found = []
    for one in clips:
        with one.get_frame(0) as f:
            luma = np.asarray(f[0], dtype=np.float32)
        if (luma.mean() - black) / (white - black) < DARK_FRAME:
            continue
        found.append(bars_in_frame(luma, black, white))
    if len(found) < min(3, len(positions)):
        return None
    left, right, top, bottom = (min(side) // 2 * 2 for side in zip(*found, strict=True))
    if left + right >= v.width or top + bottom >= v.height:
        return None
    return Crop(left=left, right=right, top=top, bottom=bottom)
