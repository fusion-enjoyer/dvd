"""Preview frames as they will look on the disc (DVD frame, SD colours)."""

from __future__ import annotations

from pathlib import Path

import vapoursynth as vs
from PySide6.QtGui import QImage

from dvd.probe import SourceInfo
from dvd.project.model import Standard, Title
from dvd.video.pipeline import UnsupportedSource, build_clip, plan_target

core = vs.core


def disc_frame(source: Path, info: SourceInfo, title: Title, standard: Standard,
               position: float = 0.4) -> tuple[QImage, float]:  # fmt: skip
    """RGB frame at `position` of the film and the aspect ratio it is displayed at."""
    v = info.main_video
    try:
        target = plan_target(v, standard, title.video)
        clip = build_clip(source, v, target, title.video)
        matrix = "470bg" if standard == "pal" else "170m"
        aspect = float(target.dar)
    except UnsupportedSource:
        clip = core.bs.VideoSource(str(source), track=v.index)
        matrix = "709" if v.height > 576 else "170m"
        aspect = float(v.dar)
    rgb = core.resize.Bicubic(clip, format=vs.RGB24, matrix_in_s=matrix)
    n = min(rgb.num_frames - 1, int(rgb.num_frames * position))
    with rgb.get_frame(n) as f:
        w, h = f.width, f.height
        planes = [memoryview(f[i]).tobytes() for i in range(3)]
    packed = bytearray(w * h * 3)
    for i in range(3):
        packed[i::3] = planes[i]
    image = QImage(bytes(packed), w, h, w * 3, QImage.Format.Format_RGB888).copy()
    return image, aspect
