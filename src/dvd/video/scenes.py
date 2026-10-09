"""Chapter suggestions: points every N minutes, each moved to the nearest scene cut.

Only a window around each wanted point is decoded, at 64×36 grey, so a feature film takes
seconds per chapter rather than a full pass. A cut is the frame whose picture differs most
from the one before it; when nothing in the window looks like a cut (a long take), the
wanted point is kept.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import vapoursynth as vs

from dvd.probe import VideoTrack
from dvd.video.pipeline import open_source

core = vs.core

WINDOW = 15.0  # seconds searched on each side of a wanted point
MIN_CUT = 0.06  # mean absolute difference (0..1) that counts as a cut


def scene_cut_near(diff: vs.VideoNode, fps: float, at: float, window: float = WINDOW) -> float:
    """`diff`: frame n carries PlaneStatsDiff between source frames n and n+1."""
    first = max(0, int((at - window) * fps))
    last = min(diff.num_frames - 1, int((at + window) * fps))
    best, best_frame = MIN_CUT, None
    for n in range(first, last + 1):
        with diff.get_frame(n) as f:
            d = f.props["PlaneStatsDiff"]
        # Prefer cuts closer to the wanted point when two are about as strong.
        score = d - 0.01 * abs((n + 1) / fps - at) / window
        if score > best:
            best, best_frame = score, n + 1
    return at if best_frame is None else best_frame / fps


def suggest_chapters(
    source: Path,
    v: VideoTrack,
    duration: float,
    every_minutes: float = 5.0,
    progress: Callable[[float], None] | None = None,
    window: float = WINDOW,
) -> list[float]:
    """Chapter starts in source seconds: 0, then about every `every_minutes`, on scene cuts."""
    clip = open_source(source, v)
    small = core.resize.Bilinear(clip, 64, 36, format=vs.GRAY8, matrix_in_s="709")
    diff = core.std.PlaneStats(small[1:], small[:-1])
    fps = clip.fps_num / clip.fps_den
    step = every_minutes * 60
    gap = min(30.0, step / 2)  # no chapter this close to another one or to the end
    wanted = [i * step for i in range(1, int(duration // step) + 1) if i * step < duration - gap]
    times = [0.0]
    for i, at in enumerate(wanted):
        cut = scene_cut_near(diff, fps, at, window)
        if cut - times[-1] > gap and cut < duration - gap:
            times.append(round(cut, 3))
        if progress:
            progress((i + 1) / len(wanted))
    return times
