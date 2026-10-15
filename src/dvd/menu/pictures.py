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


def lively(image: QImage) -> float:
    """How usable a frame is as a button picture: its contrast, near zero for a black, white
    or flat frame (fades, titles cards on black count low too)."""
    import numpy as np

    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    view = np.frombuffer(gray.constBits(), np.uint8).reshape(gray.height(), gray.bytesPerLine())
    luma = view[:, : gray.width()].astype(np.float32)
    mean = float(luma.mean())
    spread = float(luma.std())
    return spread if 28 <= mean <= 230 else spread * 0.25


GOOD_ENOUGH = 18.0  # `lively` score at which the first candidate is taken


def pick_frames(source: Path, info: SourceInfo, wanted: dict[float, tuple[float, ...]],
                size: tuple[int, int]) -> dict[float, QImage]:  # fmt: skip
    """For each key time, the first candidate frame that is lively enough, else the liveliest
    one. Keys without candidates show their own time."""
    candidates = {key: choices or (key,) for key, choices in wanted.items()}
    images = frame_images(source, info, sorted({t for c in candidates.values() for t in c}), size)
    out = {}
    for key, choices in candidates.items():
        scored = [(lively(images[t]), t) for t in choices]
        good = next((t for score, t in scored if score >= GOOD_ENOUGH), None)
        out[key] = images[good if good is not None else max(scored)[1]]
    return out


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


def button_pictures(pages: list, sources: list[Path], infos: list[SourceInfo],
                    display: tuple[int, int]) -> dict[tuple[int, float], QImage]:  # fmt: skip
    """The frames the chapter and episode buttons show, keyed by (title index, time)."""
    wanted: dict[int, dict[float, tuple[float, ...]]] = {}
    for page in pages:
        for b in page.buttons:
            if b.thumb is not None:
                wanted.setdefault(b.thumb_title, {})[b.thumb] = b.thumb_choices
    width = round(0.22 * display[0])
    size = (width, round(width * 9 / 16))
    out = {}
    for k, times in wanted.items():
        images = pick_frames(sources[k], infos[k], times, size)
        out.update({(k, t): image for t, image in images.items()})
    return out
