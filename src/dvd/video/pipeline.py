"""VapourSynth chain from a source file to a DVD-sized clip (Phase 1: correct, not yet tuned).

Steps: open the source, decide the DVD frame (PAL/NTSC, 16:9 or 4:3), scale the picture into it
with black bars where the shapes differ, convert BT.709 to BT.601 for SD, and retime film to 25 fps
for PAL. 50 and 60 fps sources become interlaced video (25i / 29.97i): each output frame
carries two source frames as its top and bottom field, so motion stays as smooth as the source.
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
NTSC_RATE = Fraction(30000, 1001)
SLOWDOWN = Fraction(1000, 1001)  # 30.000 -> 29.97 and 60.000 -> 59.94
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
    interlaced: bool = False  # two source frames per DVD frame, top field first

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


def open_source(source: Path, v: VideoTrack) -> vs.VideoNode:
    """The source as constant frame rate video at `v.playback_fps`.

    BestSource reports the true average rate; when it differs from the planned rate (variable
    frame rate phone video, or a container that misreports), the source is reopened with a
    fixed rate: frames are repeated or dropped by their timestamps, so audio stays in sync.
    Rotation metadata is applied by BestSource."""
    clip = core.bs.VideoSource(str(source), track=v.index)
    rate = v.playback_fps
    if rate and abs(Fraction(clip.fps_num, clip.fps_den) - rate) / rate > Fraction(1, 1000):
        clip = core.bs.VideoSource(str(source), track=v.index, fpsnum=rate.numerator,
                                   fpsden=rate.denominator)  # fmt: skip
    return clip


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
    rate = v.playback_fps
    if rate is None:
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

    film = any(_close(rate, r) for r in FILM_RATES)
    pulldown, interlaced, speedup = False, False, Fraction(1)
    if standard == "pal":
        frame_w, frame_h, fps = 720, 576, PAL_RATE
        if _close(rate, 2 * PAL_RATE):
            interlaced = True
        elif film:
            speedup = PAL_RATE / rate
        elif not _close(rate, PAL_RATE):
            raise UnsupportedSource(f"{float(rate):g} fps to PAL needs frame rate conversion")
    else:
        frame_w, frame_h, fps = 720, 480, NTSC_RATE
        if film:
            fps, pulldown = Fraction(24000, 1001), True
        elif _close(rate, NTSC_RATE) or _close(rate, Fraction(30)):
            speedup = Fraction(1) if _close(rate, NTSC_RATE) else SLOWDOWN
        elif _close(rate, 2 * NTSC_RATE) or _close(rate, Fraction(60)):
            interlaced = True
            speedup = Fraction(1) if _close(rate, 2 * NTSC_RATE) else SLOWDOWN
        else:
            raise UnsupportedSource(f"{float(rate):g} fps to NTSC needs frame rate conversion")

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
        Crop(left=left, right=right, top=top, bottom=bottom), pad_left, pad_top, interlaced,
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
    clip = open_source(source, v)
    crop = target.crop
    if any((crop.left, crop.right, crop.top, crop.bottom)):
        clip = core.std.Crop(clip, crop.left, crop.right, crop.top, crop.bottom)
    out_matrix = "470bg" if target.standard == "pal" else "170m"
    scale = getattr(core.resize, _KERNEL[pre.kernel])
    clip = scale(
        clip,
        width=target.active_width,
        height=target.active_height,
        # Interlaced output subsamples chroma per field at the end, so keep it full until then.
        format=vs.YUV444P16 if target.interlaced else vs.YUV420P16,
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
    if pad_w and not pad_h and pre.side_fill == "blur":
        clip = _blurred_sides(clip, target)
    elif pad_w or pad_h:
        clip = core.std.AddBorders(
            clip,
            left=target.pad_left,
            right=pad_w - target.pad_left,
            top=target.pad_top,
            bottom=pad_h - target.pad_top,
            color=[16 << 8, 128 << 8, 128 << 8],
        )
    if target.interlaced:
        clip = interlace(clip, pre.dither)
    else:
        clip = core.resize.Point(clip, format=vs.YUV420P8, dither_type=pre.dither)
    return core.std.AssumeFPS(clip, fpsnum=target.fps.numerator, fpsden=target.fps.denominator)


def _blurred_sides(clip: vs.VideoNode, target: Target) -> vs.VideoNode:
    """Fill the side bars with the picture itself, enlarged to the frame width, heavily
    blurred, darkened and desaturated, as TV does with portrait phone video. The blur is a
    1/16 downscale and back, which also keeps the bars cheap to encode."""
    scale = target.width / target.active_width
    height = round(target.height * scale / 2) * 2
    small = core.resize.Bilinear(clip, width=max(2, target.width // 16 // 2 * 2),
                                 height=max(2, height // 16 // 2 * 2))  # fmt: skip
    bg = core.resize.Bicubic(small, width=target.width, height=height)
    top = (height - target.height) // 4 * 2
    bg = core.std.Crop(bg, top=top, bottom=height - target.height - top)
    bg = core.std.Expr(bg, ["x 4096 - 0.45 * 4096 +", "x 32768 - 0.5 * 32768 +"])
    left = core.std.Crop(bg, right=target.width - target.pad_left)
    right = core.std.Crop(bg, left=target.pad_left + target.active_width)
    return core.std.StackHorizontal([left, clip, right])


def interlace(clip: vs.VideoNode, dither: str) -> vs.VideoNode:
    """50/60p -> 25/30i, top field first: the top field of output frame n comes from source
    frame 2n, the bottom field from 2n+1. Chroma is subsampled per field (4:2:0 interlaced)."""
    fields = core.std.SeparateFields(clip, tff=True)
    fields = core.std.SelectEvery(fields, 4, [0, 3])  # top of even frames, bottom of odd ones
    fields = core.resize.Bicubic(fields, format=vs.YUV420P8, dither_type=dither)
    woven = core.std.DoubleWeave(fields, tff=True)[::2]
    return core.std.SetFieldBased(woven, 2)
