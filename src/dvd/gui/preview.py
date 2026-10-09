"""Preview frames: the source and the disc picture at the same place, same geometry, so they
can be compared with a split view."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import vapoursynth as vs
from PySide6.QtGui import QImage

from dvd.probe import SourceInfo
from dvd.project.model import Crop, Profiles, Standard, Title
from dvd.video.crop import detect_crop
from dvd.video.pipeline import UnsupportedSource, build_clip, check_supported, plan_target
from dvd.video.preprocess import resolve

core = vs.core


@dataclass
class PreviewFrames:
    source: QImage  # source picture framed like the disc (crop, bars), before any processing
    disc: QImage  # what the encoder receives: scaled, SD colours, debanded, dithered
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


def _matrix(v) -> str:
    return "709" if (v.color_matrix == "bt709" or v.height > 576) else "170m"


def preview_frames(
    source: Path,
    info: SourceInfo,
    title: Title,
    standard: Standard,
    profiles: Profiles | None = None,
    position: float = 0.4,
) -> PreviewFrames:
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
        raw = core.bs.VideoSource(str(source), track=v.index)
        rgb = core.resize.Bicubic(raw, format=vs.RGB24, matrix_in_s=_matrix(v))
        n = min(rgb.num_frames - 1, int(rgb.num_frames * position))
        image = to_qimage(rgb, n)
        return PreviewFrames(
            image, image, float(v.dar), None, n, n / float(raw.fps), raw.num_frames
        )

    n = min(disc.num_frames - 1, int(disc.num_frames * position))
    aspect = float(target.dar)
    width = round(target.height * aspect / 2) * 2
    sx = width / target.width
    sd_matrix = "470bg" if standard == "pal" else "170m"
    disc_rgb = core.resize.Spline36(disc, width=width, format=vs.RGB24, matrix_in_s=sd_matrix)
    # The source through the same crop and bars, scaled straight to display size.
    c = target.crop
    raw = core.bs.VideoSource(str(source), track=v.index)
    if any((c.left, c.right, c.top, c.bottom)):
        raw = core.std.Crop(raw, c.left, c.right, c.top, c.bottom)
    active_w = round(target.active_width * sx / 2) * 2
    src_rgb = core.resize.Spline36(raw, width=active_w, height=target.active_height,
                                   format=vs.RGB24, matrix_in_s=_matrix(v))  # fmt: skip
    left = round(target.pad_left * sx)
    bottom = target.height - target.active_height - target.pad_top
    src_rgb = core.std.AddBorders(
        src_rgb, left=left, right=width - active_w - left, top=target.pad_top, bottom=bottom
    )
    return PreviewFrames(
        to_qimage(src_rgb, n), to_qimage(disc_rgb, n), aspect, detected, n,
        n / float(target.fps), disc.num_frames,
    )  # fmt: skip
