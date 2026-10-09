"""Preview frames: the source and the disc picture at the same place, same framing, so they
can be compared with a split view. The disc picture keeps its stored pixels (720 wide, drawn
at its display aspect); the source keeps about its own resolution, so zooming in shows what
the downscale lost."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import vapoursynth as vs
from PySide6.QtGui import QImage

from dvd.probe import SourceInfo
from dvd.project.model import Crop, Profiles, Standard, Title
from dvd.video.crop import detect_crop
from dvd.video.pipeline import (
    UnsupportedSource,
    build_clip,
    check_supported,
    open_source,
    plan_target,
)
from dvd.video.preprocess import resolve

core = vs.core


@dataclass
class PreviewFrames:
    source: QImage  # source picture framed like the disc (crop, bars), before any processing
    disc: QImage  # what the encoder receives, at disc resolution: SD colours, debanded, dithered
    aspect: float  # display aspect of both images
    detected: Crop | None
    frame: int
    seconds: float  # playback position of `frame`
    frames: int


def to_qimage(rgb: vs.VideoNode, n: int) -> QImage:
    with rgb.get_frame(n) as f:
        pixels = np.ascontiguousarray(np.dstack([np.asarray(f[i]) for i in range(3)]))
    h, w, _ = pixels.shape
    return QImage(pixels.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()


def _frame_number(frames: int, position: float, frame: int | None) -> int:
    n = int(frames * position) if frame is None else frame
    return min(frames - 1, max(0, n))


def _matrix(v) -> str:
    return "709" if (v.color_matrix == "bt709" or v.height > 576) else "170m"


def preview_frames(
    source: Path,
    info: SourceInfo,
    title: Title,
    standard: Standard,
    profiles: Profiles | None = None,
    position: float = 0.4,
    frame: int | None = None,
) -> PreviewFrames:
    """The frame at `position` (0..1 of the film), or frame number `frame` when given."""
    v = info.main_video
    detected = None
    try:
        if title.video.crop == "auto":
            check_supported(v)
            detected = detect_crop(source, v)
        target = plan_target(v, standard, title.video, detected)
        pre = resolve(profiles or Profiles(), title.video.overrides)
        disc = build_clip(source, v, target, title.video, pre)
    except UnsupportedSource:
        raw = open_source(source, v)
        rgb = core.resize.Bicubic(raw, format=vs.RGB24, matrix_in_s=_matrix(v))
        n = _frame_number(rgb.num_frames, position, frame)
        image = to_qimage(rgb, n)
        return PreviewFrames(
            image, image, float(v.dar), None, n, n / float(raw.fps), raw.num_frames
        )

    n = _frame_number(disc.num_frames, position, frame)
    aspect = float(target.dar)
    sd_matrix = "470bg" if standard == "pal" else "170m"
    disc_rgb = core.resize.Point(disc, format=vs.RGB24, matrix_in_s=sd_matrix)
    # The source through the same crop and bars, at about its own line count: the whole frame
    # is `scale` times the disc frame in height and has the display aspect.
    c = target.crop
    raw = open_source(source, v)
    if any((c.left, c.right, c.top, c.bottom)):
        raw = core.std.Crop(raw, c.left, c.right, c.top, c.bottom)
    scale = max(1.0, raw.height / target.active_height)
    height = round(target.height * scale / 2) * 2
    width = round(height * aspect / 2) * 2
    active_w = round(width * target.active_width / target.width / 2) * 2
    active_h = round(target.active_height * scale / 2) * 2
    src_rgb = core.resize.Spline36(raw, width=active_w, height=active_h,
                                   format=vs.RGB24, matrix_in_s=_matrix(v))  # fmt: skip
    left = round(width * target.pad_left / target.width)
    top = round(target.pad_top * scale)
    src_rgb = core.std.AddBorders(src_rgb, left=left, right=width - active_w - left, top=top,
                                  bottom=height - active_h - top)  # fmt: skip
    return PreviewFrames(
        to_qimage(src_rgb, n), to_qimage(disc_rgb, n), aspect, detected, n,
        n / float(target.fps), disc.num_frames,
    )  # fmt: skip
