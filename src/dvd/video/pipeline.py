"""VapourSynth chain from a source file to a DVD-sized clip (Phase 1: correct, not yet tuned).

Steps: open the source, decide the DVD frame (PAL/NTSC, 16:9 or 4:3), scale the picture into it
with black bars where the shapes differ, convert BT.709 to BT.601 for SD, and retime film to 25 fps
for PAL. Pre-processing for quality (deband, dither, grain, crop detection) comes in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import vapoursynth as vs

from dvd.probe import VideoTrack
from dvd.project.model import Crop, Standard, Video
from dvd.video.preprocess import Preprocess

DEFAULT_PREPROCESS = Preprocess()

core = vs.core

FILM_RATES = (Fraction(24000, 1001), Fraction(24))
PAL_RATE = Fraction(25)
NTSC_RATES = (Fraction(30000, 1001),)
WIDESCREEN_FROM = Fraction(3, 2)  # sources wider than this get a 16:9 frame


class UnsupportedSource(Exception):
    pass


@dataclass(frozen=True)
class Target:
    """The DVD picture a title is encoded into."""

    standard: Standard
    width: int
    height: int
    fps: Fraction
    aspect: str  # "16:9" or "4:3"
    pulldown: bool  # NTSC film: encode 23.976 progressive, flag for 29.97 playback
    speedup: Fraction  # PAL film: playback speed factor (audio must match)
    active_width: int
    active_height: int
    crop: Crop = field(default_factory=Crop)  # applied to the source before scaling
    pad_left: int = 0
    pad_top: int = 0

    @property
    def dar(self) -> Fraction:
        return Fraction(16, 9) if self.aspect == "16:9" else Fraction(4, 3)


def _close(a: Fraction, b: Fraction) -> bool:
    return abs(a - b) < Fraction(1, 100)


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def check_supported(v: VideoTrack) -> None:
    if v.hdr:
        raise UnsupportedSource("HDR sources need tone mapping, planned for Phase 2")
    if v.interlaced:
        raise UnsupportedSource("interlaced sources need deinterlacing, planned for Phase 2")
    if v.maybe_vfr:
        raise UnsupportedSource("variable frame rate sources are planned for Phase 2")


def crop_values(video: Video, detected: Crop | None = None) -> Crop:
    """The project's crop: explicit values, the detected bars for "auto", or nothing."""
    if isinstance(video.crop, Crop):
        return video.crop
    if video.crop == "auto" and detected is not None:
        return detected
    return Crop()


def _round16(x: float, limit: int) -> int:
    return max(16, min(limit, round(x / 16) * 16))


def _split_even(total: int) -> tuple[int, int]:
    first = total // 2 // 2 * 2
    return first, total - first


def plan_target(
    v: VideoTrack,
    standard: Standard,
    video: Video,
    detected: Crop | None = None,
    align: bool = True,
) -> Target:
    """Frame, scale and bars for a source.

    With `align`, the picture size and the bars sit on 16-pixel macroblock boundaries, so no
    macroblock straddles the edge between picture and black. To keep the shape exact, a few
    more source pixels are cropped instead of stretching; an odd bar goes to the bottom/right.
    """
    if v.fps is None:
        raise UnsupportedSource("source frame rate is unknown")
    crop = crop_values(video, detected)
    width = v.width - crop.left - crop.right
    height = v.height - crop.top - crop.bottom
    if width <= 0 or height <= 0:
        raise UnsupportedSource("crop removes the whole picture")
    content_dar = Fraction(width, height) * v.sar

    aspect = video.aspect
    if aspect == "auto":
        aspect = "16:9" if content_dar >= WIDESCREEN_FROM else "4:3"
    frame_dar = Fraction(16, 9) if aspect == "16:9" else Fraction(4, 3)

    film = any(_close(v.fps, r) for r in FILM_RATES)
    if standard == "pal":
        if _close(v.fps, PAL_RATE):
            fps, speedup = PAL_RATE, Fraction(1)
        elif film:
            fps, speedup = PAL_RATE, PAL_RATE / v.fps
        else:
            raise UnsupportedSource(f"{float(v.fps):g} fps to PAL needs frame rate conversion")
        frame_w, frame_h, pulldown = 720, 576, False
    else:
        if film:
            fps, pulldown = Fraction(24000, 1001), True
        elif any(_close(v.fps, r) for r in NTSC_RATES):
            fps, pulldown = Fraction(30000, 1001), False
        else:
            raise UnsupportedSource(f"{float(v.fps):g} fps to NTSC needs frame rate conversion")
        frame_w, frame_h, speedup = 720, 480, Fraction(1)

    left, right, top, bottom = crop.left, crop.right, crop.top, crop.bottom
    if content_dar >= frame_dar:  # wider: full width, bars top and bottom
        ideal = frame_h * frame_dar / content_dar
        active_w = frame_w
        active_h = _round16(ideal, frame_h) if align else min(frame_h, _even(ideal))
    else:  # narrower: full height, bars left and right
        ideal = frame_w * content_dar / frame_dar
        active_h = frame_h
        active_w = _round16(ideal, frame_w) if align else min(frame_w, _even(ideal))
    if align:
        # Shape the picture actually gets; crop the source to match it instead of stretching.
        shown = frame_dar * Fraction(active_w, frame_w) / Fraction(active_h, frame_h)
        if shown < content_dar:
            keep = _even(height * shown / v.sar)
            a, b = _split_even(width - keep)
            left, right = left + a, right + b
        elif shown > content_dar:
            keep = _even(width * v.sar / shown)
            a, b = _split_even(height - keep)
            top, bottom = top + a, bottom + b
    step = 16 if align else 2
    pad_left = (frame_w - active_w) // 2 // step * step
    pad_top = (frame_h - active_h) // 2 // step * step
    return Target(
        standard, frame_w, frame_h, fps, aspect, pulldown, speedup, active_w, active_h,
        Crop(left=left, right=right, top=top, bottom=bottom), pad_left, pad_top,
    )  # fmt: skip


def _matrix(v: VideoTrack) -> str:
    if v.color_matrix in ("bt709", "bt470bg", "smpte170m", "bt2020nc"):
        return {"bt709": "709", "bt470bg": "470bg", "smpte170m": "170m", "bt2020nc": "2020ncl"}[
            v.color_matrix
        ]
    return "709" if v.height > 576 else "170m"


_KERNEL = {"spline36": "Spline36", "lanczos": "Lanczos", "bicubic": "Bicubic"}


def build_clip(
    source: Path,
    v: VideoTrack,
    target: Target,
    video: Video,
    pre: Preprocess = DEFAULT_PREPROCESS,
) -> vs.VideoNode:
    """Source -> DVD frame. Scaling, matrix conversion, deband and bars run at 16 bits; the
    single step down to 8 bits is the final dither, so no stage adds its own rounding bands."""
    check_supported(v)
    clip = core.bs.VideoSource(str(source), track=v.index)
    crop = target.crop
    if any((crop.left, crop.right, crop.top, crop.bottom)):
        clip = core.std.Crop(clip, crop.left, crop.right, crop.top, crop.bottom)
    out_matrix = "470bg" if target.standard == "pal" else "170m"
    scale = getattr(core.resize, _KERNEL[pre.kernel])
    clip = scale(
        clip,
        width=target.active_width,
        height=target.active_height,
        format=vs.YUV420P16,
        matrix_in_s=_matrix(v),
        matrix_s=out_matrix,
        range_in_s="full" if v.color_range == "pc" else "limited",
        range_s="limited",
    )
    if pre.deband_args:
        radius, threshold = pre.deband_args
        clip = core.vszip.Deband(clip, range=radius, thr=[threshold], keep_tv_range=True)
    pad_w = target.width - target.active_width
    pad_h = target.height - target.active_height
    if pad_w or pad_h:
        clip = core.std.AddBorders(
            clip,
            left=target.pad_left,
            right=pad_w - target.pad_left,
            top=target.pad_top,
            bottom=pad_h - target.pad_top,
            color=[16 << 8, 128 << 8, 128 << 8],
        )
    clip = core.resize.Point(clip, format=vs.YUV420P8, dither_type=pre.dither)
    return core.std.AssumeFPS(clip, fpsnum=target.fps.numerator, fpsden=target.fps.denominator)
