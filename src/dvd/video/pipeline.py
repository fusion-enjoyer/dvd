"""VapourSynth chain from a source file to a DVD-sized clip (Phase 1: correct, not yet tuned).

Steps: open the source, decide the DVD frame (PAL/NTSC, 16:9 or 4:3), scale the picture into it
with black bars where the shapes differ, convert BT.709 to BT.601 for SD, and retime film to 25 fps
for PAL. Pre-processing for quality (deband, dither, grain, crop detection) comes in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import vapoursynth as vs

from dvd.probe import VideoTrack
from dvd.project.model import Crop, Standard, Video

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


def crop_values(video: Video) -> Crop:
    # "auto" becomes real black-bar detection in Phase 2; until then the bars are scaled with
    # the picture, which looks the same but spends a few bits on black.
    return video.crop if isinstance(video.crop, Crop) else Crop()


def plan_target(v: VideoTrack, standard: Standard, video: Video) -> Target:
    if v.fps is None:
        raise UnsupportedSource("source frame rate is unknown")
    crop = crop_values(video)
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

    if content_dar >= frame_dar:  # wider: full width, bars top and bottom
        active_w, active_h = frame_w, _even(frame_h * frame_dar / content_dar)
    else:  # narrower: full height, bars left and right
        active_w, active_h = _even(frame_w * content_dar / frame_dar), frame_h
    return Target(
        standard, frame_w, frame_h, fps, aspect, pulldown, speedup,
        min(active_w, frame_w), min(active_h, frame_h),
    )  # fmt: skip


def _matrix(v: VideoTrack) -> str:
    if v.color_matrix in ("bt709", "bt470bg", "smpte170m", "bt2020nc"):
        return {"bt709": "709", "bt470bg": "470bg", "smpte170m": "170m", "bt2020nc": "2020ncl"}[
            v.color_matrix
        ]
    return "709" if v.height > 576 else "170m"


def build_clip(source: Path, v: VideoTrack, target: Target, video: Video) -> vs.VideoNode:
    check_supported(v)
    clip = core.bs.VideoSource(str(source), track=v.index)
    crop = crop_values(video)
    if any((crop.left, crop.right, crop.top, crop.bottom)):
        clip = core.std.Crop(clip, crop.left, crop.right, crop.top, crop.bottom)
    out_matrix = "470bg" if target.standard == "pal" else "170m"
    clip = core.resize.Spline36(
        clip,
        width=target.active_width,
        height=target.active_height,
        format=vs.YUV420P8,
        matrix_in_s=_matrix(v),
        matrix_s=out_matrix,
        range_in_s="full" if v.color_range == "pc" else "limited",
        range_s="limited",
    )
    pad_w = target.width - target.active_width
    pad_h = target.height - target.active_height
    if pad_w or pad_h:
        clip = core.std.AddBorders(
            clip,
            left=pad_w // 2 // 2 * 2,
            right=pad_w - pad_w // 2 // 2 * 2,
            top=pad_h // 2 // 2 * 2,
            bottom=pad_h - pad_h // 2 // 2 * 2,
            color=[16, 128, 128],
        )
    return core.std.AssumeFPS(clip, fpsnum=target.fps.numerator, fpsden=target.fps.denominator)
