"""Pictures for menus taken from the film: chapter frames and the background frame."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QImage

from dvd.probe import SourceInfo
from dvd.project.model import MenuBackground, parse_timecode


def to_qimage(rgb, n: int) -> QImage:
    """Frame `n` of an RGB24 VapourSynth clip as a QImage."""
    import numpy as np

    with rgb.get_frame(n) as f:
        pixels = np.ascontiguousarray(np.dstack([np.asarray(f[i]) for i in range(3)]))
    h, w, _ = pixels.shape
    return QImage(pixels.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()


def frame_images(source: Path, info: SourceInfo, times: list[float],
                 size: tuple[int, int]) -> dict[float, QImage]:  # fmt: skip
    """Frames at source times, scaled to `size` (square pixels), tone mapped like the disc."""
    import vapoursynth as vs

    from dvd.video.pipeline import open_source, scale_to_sd

    v = info.main_video
    clip = open_source(source, v)
    w, h = size
    small = scale_to_sd(clip, v, w, h, "bicubic", "709", vs.YUV444P16)
    rgb = vs.core.resize.Point(small, format=vs.RGB24, matrix_in_s="709")
    fps = clip.fps_num / clip.fps_den
    return {at: to_qimage(rgb, min(rgb.num_frames - 1, round(at * fps))) for at in times}


def background_image(bg: MenuBackground, source: Path, info: SourceInfo, project_dir: Path,
                     size: tuple[int, int]) -> QImage:  # fmt: skip
    """The page backdrop: a film frame, a picture file, or the plain colour."""
    if bg.frame is not None and info.main_video is not None:
        at = parse_timecode(bg.frame)
        return frame_images(source, info, [at], size)[at]
    if bg.image is not None:
        path = Path(bg.image)
        image = QImage(str(path if path.is_absolute() else project_dir / path))
        if image.isNull():
            raise ValueError(f"cannot read menu background {bg.image}")
        return image
    image = QImage(*size, QImage.Format.Format_RGB32)
    image.fill(QColor(bg.color))
    return image


def logo_image(path: str | None, project_dir: Path) -> QImage | None:
    """The menu logo picture (PNG with transparency, usually from TMDB), if one is set."""
    if not path:
        return None
    p = Path(path)
    image = QImage(str(p if p.is_absolute() else project_dir / p))
    if image.isNull():
        raise ValueError(f"cannot read menu logo {path}")
    return image
