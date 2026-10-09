"""Quality of an encode against the picture that went into the encoder.

The reference is the pre-processed DVD frame (`build.disc_clip`), so the score isolates what
MPEG-2 compression lost; scaling and pre-processing are judged separately by eye and A/B.
Per frame: XPSNR (luma, dB) and SSIMULACRA2 (0-100, perceptual). Worst scenes are the
lowest one-second averages, non-overlapping.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import vapoursynth as vs

core = vs.core


@dataclass(frozen=True)
class FrameScore:
    frame: int
    xpsnr: float
    ssimu2: float


@dataclass(frozen=True)
class Scene:
    start: int  # frame
    end: int  # frame, exclusive
    ssimu2: float
    xpsnr: float

    def timecode(self, fps: Fraction) -> str:
        s = int(self.start / fps)
        return f"{s // 3600}:{s // 60 % 60:02}:{s % 60:02}"


@dataclass
class Measurement:
    fps: Fraction
    scores: list[FrameScore] = field(default_factory=list)

    def _values(self, name: str) -> list[float]:
        return [getattr(s, name) for s in self.scores if math.isfinite(getattr(s, name))]

    def mean(self, name: str) -> float:
        values = self._values(name)
        return sum(values) / len(values) if values else float("nan")

    def percentile(self, name: str, p: float) -> float:
        values = sorted(self._values(name))
        if not values:
            return float("nan")
        return values[min(len(values) - 1, int(p / 100 * len(values)))]

    def worst_scenes(self, count: int = 10, seconds: float = 1.0) -> list[Scene]:
        """Lowest SSIMULACRA2 averages over windows of `seconds`, not overlapping."""
        if not self.scores:
            return []
        frames = [s.frame for s in self.scores]
        step = frames[1] - frames[0] if len(frames) > 1 else 1
        width = max(1, round(seconds * float(self.fps) / step))
        windows = []
        for i in range(0, max(1, len(self.scores) - width + 1)):
            chunk = self.scores[i : i + width]
            ss = sum(c.ssimu2 for c in chunk) / len(chunk)
            xp = [c.xpsnr for c in chunk if math.isfinite(c.xpsnr)]
            windows.append((ss, i, sum(xp) / len(xp) if xp else float("inf")))
        chosen: list[Scene] = []
        used: list[tuple[int, int]] = []
        for ss, i, xp in sorted(windows):
            lo, hi = i, i + width
            if any(lo < b and a < hi for a, b in used):
                continue
            used.append((lo, hi))
            last = self.scores[min(hi, len(self.scores)) - 1].frame + step
            chosen.append(Scene(self.scores[lo].frame, last, ss, xp))
            if len(chosen) == count:
                break
        return chosen


def _rgb(clip: vs.VideoNode, matrix: str) -> vs.VideoNode:
    return core.resize.Bicubic(clip, format=vs.RGBS, matrix_in_s=matrix)


def measure(
    reference: vs.VideoNode,
    encoded: Path,
    standard: str,
    step: int = 1,
    progress: Callable[[float], None] | None = None,
) -> Measurement:
    """Score every `step`-th frame of `encoded` (an .m2v) against `reference`."""
    distorted = core.bs.VideoSource(str(encoded))
    count = min(reference.num_frames, distorted.num_frames)
    ref = reference[:count]
    dist = core.std.AssumeFPS(distorted[:count], src=ref)
    if step > 1:
        ref, dist = core.std.SelectEvery(ref, step, 0), core.std.SelectEvery(dist, step, 0)
    matrix = "470bg" if standard == "pal" else "170m"
    xpsnr = core.vszip.XPSNR(ref, dist, verbose=0)
    ssimu2 = core.vszip.SSIMULACRA2(_rgb(ref, matrix), _rgb(dist, matrix))
    result = Measurement(reference.fps)
    total = xpsnr.num_frames
    for i, (fx, fs) in enumerate(zip(xpsnr.frames(), ssimu2.frames(), strict=True)):
        result.scores.append(
            FrameScore(i * step, float(fx.props["XPSNR_Y"]), float(fs.props["SSIMULACRA2"]))
        )
        if progress and i % 25 == 0:
            progress(i / total)
    if progress:
        progress(1.0)
    return result
