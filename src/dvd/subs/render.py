"""Subtitle cue -> DVD subpicture bitmap (4 colours) with Qt.

DVD subpictures are 2-bit images: at most 4 colours, each with a 4-bit contrast (alpha). We use
  0 transparent, 1 text fill, 2 outline, 3 half-transparent outline for the anti-aliased rim.
Text is drawn on a square-pixel canvas (1024x576 for PAL 16:9) and squeezed to the 720-pixel
DVD width, so the player's horizontal stretch restores the letter shapes (anamorphic correction).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)

from dvd.subs.srt import Cue

FONT_FILE = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "SourceSans3.ttf"
RGB = tuple[int, int, int]


@dataclass(frozen=True)
class SubStyle:
    family: str = "Source Sans 3"
    weight: int = 600
    size: float = 0.058  # font pixel size as a fraction of the frame height
    fill: RGB = (235, 235, 235)
    outline: RGB = (16, 16, 16)
    outline_width: float = 0.0055  # fraction of frame height, each side of the glyph edge
    bottom: float = 0.075  # gap between the last line and the frame bottom, fraction of height
    max_width: float = 0.88  # of the visible picture width
    line_spacing: float = 1.08


DEFAULT_STYLE = SubStyle()


def style_for(size: float, safe_area: float) -> SubStyle:
    """Default style scaled for the viewing profile: larger text and a wider margin where
    the screen is small or the TV crops the picture edges (overscan)."""
    margin = (1 - safe_area) / 2
    return SubStyle(
        size=DEFAULT_STYLE.size * size,
        bottom=max(DEFAULT_STYLE.bottom, margin + 0.02),
        max_width=min(DEFAULT_STYLE.max_width, safe_area - 0.04),
    )


@dataclass(frozen=True)
class Bitmap:
    rgba: np.ndarray  # (h, w, 4) uint8, at most 4 distinct RGBA values
    x: int
    y: int

    @property
    def width(self) -> int:
        return self.rgba.shape[1]

    @property
    def height(self) -> int:
        return self.rgba.shape[0]


@cache
def _qt() -> QGuiApplication:
    app = QGuiApplication.instance()
    if app is None:
        # A full QApplication, so the desktop UI can still open windows in this process.
        from PySide6.QtWidgets import QApplication

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    if QFontDatabase.addApplicationFont(str(FONT_FILE)) < 0:
        raise RuntimeError(f"cannot load font {FONT_FILE}")
    return app


def _font(style: SubStyle, height: int, italic: bool) -> QFont:
    font = QFont(style.family)
    font.setPixelSize(max(8, round(style.size * height)))
    font.setWeight(QFont.Weight(style.weight))
    font.setItalic(italic)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def wrap(lines: tuple[str, ...], metrics: QFontMetricsF, max_px: float) -> list[str]:
    out = []
    for line in lines:
        words, current = line.split(), ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and metrics.horizontalAdvance(candidate) > max_px:
                out.append(current)
                current = word
            else:
                current = candidate
        if current:
            out.append(current)
    return out


def _alpha(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    view = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    return view[:, 3 : image.width() * 4 : 4].copy()  # little-endian BGRA -> alpha byte


def render_cue(
    cue: Cue,
    frame_width: int,
    frame_height: int,
    aspect: Fraction,
    style: SubStyle = DEFAULT_STYLE,
) -> Bitmap:
    _qt()
    canvas_w = round(frame_height * aspect)  # square-pixel width of the displayed picture
    font = _font(style, frame_height, cue.italic)
    metrics = QFontMetricsF(font)
    lines = wrap(cue.lines, metrics, style.max_width * canvas_w)
    step = metrics.height() * style.line_spacing
    baseline = frame_height * (1 - style.bottom) - metrics.descent() - step * (len(lines) - 1)

    path = QPainterPath()
    for i, line in enumerate(lines):
        x = (canvas_w - metrics.horizontalAdvance(line)) / 2
        path.addText(QPointF(x, baseline + i * step), font, line)

    def draw(outline: bool) -> np.ndarray:
        img = QImage(canvas_w, frame_height, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if outline:
            pen = QPen(QColor(255, 255, 255), 2 * style.outline_width * frame_height)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.strokePath(path, pen)
        p.fillPath(path, QBrush(QColor(255, 255, 255)))
        p.end()
        squeezed = img.scaled(
            frame_width,
            frame_height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return _alpha(squeezed)

    fill_a, outline_a = draw(False), draw(True)
    return quantize(fill_a, outline_a, style)


def quantize(fill_a: np.ndarray, outline_a: np.ndarray, style: SubStyle) -> Bitmap:
    h, w = fill_a.shape
    rgba = np.zeros((h, w, 4), np.uint8)
    rim = outline_a >= 64
    solid = outline_a >= 170
    text = fill_a >= 128
    # Rim colour differs by one step from the outline so tools that key colours on RGB alone
    # still see four distinct entries.
    rim_rgb = tuple(min(255, c + 1) for c in style.outline)
    rgba[rim] = (*rim_rgb, 128)
    rgba[solid] = (*style.outline, 255)
    rgba[text] = (*style.fill, 255)
    ys, xs = np.nonzero(rgba[:, :, 3])
    if len(ys) == 0:
        return Bitmap(np.zeros((2, 2, 4), np.uint8), 0, 0)
    # Even origin and size: subpicture lines are interlaced, odd offsets shift the field order.
    y0, x0 = ys.min() // 2 * 2, xs.min() // 2 * 2
    y1, x1 = min(h, (ys.max() + 2) // 2 * 2), min(w, (xs.max() + 2) // 2 * 2)
    return Bitmap(np.ascontiguousarray(rgba[y0:y1, x0:x1]), int(x0), int(y0))


def save_png(bitmap: Bitmap, path: Path) -> None:
    h, w = bitmap.height, bitmap.width
    img = QImage(bitmap.rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    if not img.save(str(path), "PNG"):
        raise OSError(f"cannot write {path}")
