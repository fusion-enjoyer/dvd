"""Menu page pictures: the background video frame and the button highlight subpictures.

Labels, the page title and chapter pictures are part of the background (full colour). The
subpicture overlay only marks the buttons, in at most 4 colours (transparent, a colour and
its half-transparent edge): `highlight` when the remote's cursor is on a button, `select`
for the moment it is pressed. Everything is drawn with square pixels at display size
(1024x576 for 16:9 PAL) and squeezed to the 720-pixel disc width at the end, like the
subtitles, so circles stay round on the TV.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

from dvd.menu.layout import Button, Page
from dvd.subs.render import _qt

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"
LEFT_MIDDLE = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


@dataclass(frozen=True)
class Template:
    text: tuple[int, int, int] = (226, 221, 212)  # labels: off-white, inside video levels
    title: tuple[int, int, int] = (236, 231, 222)
    muted: tuple[int, int, int] = (160, 154, 144)
    highlight: tuple[int, int, int] = (240, 180, 73)  # amber, as in the app
    select: tuple[int, int, int] = (250, 246, 238)
    shade: float = 0.62  # darkening of the background behind the text column
    label_size: float = 0.040  # of the frame height
    title_size: float = 0.070


TEMPLATES = {"minimal": Template()}


@dataclass
class RenderedPage:
    background: QImage  # disc frame size (720 wide), RGB
    highlight: np.ndarray  # (h, w, 4) uint8, at most 4 colours
    select: np.ndarray
    buttons: list[tuple[Button, tuple[int, int, int, int]]]  # disc pixels x0, y0, x1, y1


def _fonts() -> None:
    _qt()
    for name in ("BricolageGrotesque", "SourceSans3"):
        QFontDatabase.addApplicationFont(str(FONTS / f"{name}.ttf"))


def _font(family: str, px: float, weight: int) -> QFont:
    font = QFont(family)
    font.setPixelSize(max(8, round(px)))
    font.setWeight(QFont.Weight(weight))
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def _px(rect: tuple[float, float, float, float], w: int, h: int) -> QRectF:
    x, y, rw, rh = rect
    return QRectF(x * w, y * h, rw * w, rh * h)


def _quantize(image: QImage, rgb: tuple[int, int, int]) -> np.ndarray:
    """An overlay drawn in one colour with antialiased edges -> 3 entries: transparent, the
    colour at half opacity (the edge) and the solid colour."""
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = image.width(), image.height()
    alpha = np.frombuffer(image.constBits(), np.uint8).reshape(h, image.bytesPerLine())
    alpha = alpha[:, 3 : w * 4 : 4]
    out = np.zeros((h, w, 4), np.uint8)
    out[alpha >= 64] = (*rgb, 128)
    out[alpha >= 170] = (*rgb, 255)
    return out


def render_page(
    page: Page,
    frame: tuple[int, int, Fraction],
    background: QImage | None = None,
    thumbs: dict[float, QImage] | None = None,
    template: Template | None = None,
) -> RenderedPage:
    """`frame`: disc frame width, height and display aspect. `background`: any size, it is
    scaled to cover the frame; None draws the template's plain backdrop."""
    _fonts()
    t = template or TEMPLATES["minimal"]
    fw, fh, aspect = frame
    dw = round(fh * aspect)  # square-pixel width
    canvas = QImage(dw, fh, QImage.Format.Format_RGB32)
    canvas.fill(QColor(20, 20, 20))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if background is not None and not background.isNull():
        scaled = background.scaled(dw, fh, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)  # fmt: skip
        p.drawImage(QPointF((dw - scaled.width()) / 2, (fh - scaled.height()) / 2), scaled)
    # Shade from the left so light text reads on any picture.
    shade = QLinearGradient(0, 0, dw, 0)
    shade.setColorAt(0, QColor(0, 0, 0, round(255 * t.shade)))
    shade.setColorAt(0.65, QColor(0, 0, 0, round(255 * t.shade * 0.55)))
    shade.setColorAt(1, QColor(0, 0, 0, round(255 * t.shade * 0.25)))
    p.fillRect(canvas.rect(), shade)

    title_font = _font("Bricolage Grotesque", t.title_size * fh, 600)
    label_font = _font("Source Sans 3", t.label_size * fh, 600)
    if page.title:
        p.setFont(title_font)
        p.setPen(QColor(*t.title))
        title_rect = QRectF(0.10 * dw, 0.08 * fh, 0.80 * dw, 0.11 * fh)
        p.drawText(title_rect, LEFT_MIDDLE, page.title)
    p.setFont(label_font)
    for text, rect in page.headings:
        p.setPen(QColor(*t.muted))
        p.drawText(_px(rect, dw, fh), Qt.AlignmentFlag.AlignVCenter, text)

    overlays = {k: QImage(dw, fh, QImage.Format.Format_ARGB32_Premultiplied)
                for k in ("highlight", "select")}  # fmt: skip
    for img in overlays.values():
        img.fill(Qt.GlobalColor.transparent)
    painters = {k: QPainter(img) for k, img in overlays.items()}
    for q in painters.values():
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
    colours = {"highlight": t.highlight, "select": t.select}

    for b in page.buttons:
        r = _px(b.rect, dw, fh)
        if b.thumb is not None:
            pic = QRectF(r.left(), r.top(), r.width(), r.width() * 9 / 16)
            image = (thumbs or {}).get(b.thumb)
            if image is not None:
                p.drawImage(pic, image)
            else:
                p.fillRect(pic, QColor(45, 45, 45))
            p.setPen(QColor(*t.text))
            label = QRectF(r.left(), pic.bottom() + 0.008 * fh, r.width(),
                           r.bottom() - pic.bottom())  # fmt: skip
            p.drawText(label, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, b.label)
            for k, q in painters.items():  # a frame around the picture
                q.setPen(QPen(QColor(*colours[k]), max(3.0, 0.006 * fh)))
                q.setBrush(Qt.BrushStyle.NoBrush)
                q.drawRect(pic.adjusted(-3, -3, 3, 3))
            continue
        p.setPen(QColor(*t.text))
        text_rect = r.adjusted(0.028 * dw, 0, 0, 0)
        p.drawText(text_rect, LEFT_MIDDLE, b.label)
        # Overlay: the label redrawn in the state colour plus a bar in front of it.
        metrics_path = QPainterPath()
        baseline = r.center().y() + label_font.pixelSize() * 0.36
        metrics_path.addText(QPointF(text_rect.left(), baseline), label_font, b.label)
        for k, q in painters.items():
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(QColor(*colours[k]))
            q.drawPath(metrics_path)
            bar_h = r.height() * 0.55
            q.drawRect(QRectF(r.left(), r.center().y() - bar_h / 2, 0.008 * dw, bar_h))
    for q in painters.values():
        q.end()
    p.end()

    def squeeze(img: QImage) -> QImage:
        return img.scaled(fw, fh, Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)  # fmt: skip

    sx = fw / dw
    boxes = []
    for b in page.buttons:
        # Room for the picture frame; text buttons keep their rows so areas never overlap.
        pad = 6 if b.thumb is not None else 0
        r = _px(b.rect, dw, fh).adjusted(-pad, -pad, pad, pad)
        x0 = max(0, int(r.left() * sx)) // 2 * 2
        x1 = min(fw, int(r.right() * sx) + 2) // 2 * 2
        y0 = max(0, int(r.top())) // 2 * 2
        y1 = min(fh, int(r.bottom()) + 2) // 2 * 2
        boxes.append((b, (x0, y0, x1, y1)))
    return RenderedPage(
        squeeze(canvas).convertToFormat(QImage.Format.Format_RGB888),
        _quantize(squeeze(overlays["highlight"]), t.highlight),
        _quantize(squeeze(overlays["select"]), t.select),
        boxes,
    )


def save_rgba(rgba: np.ndarray, path: Path) -> None:
    h, w = rgba.shape[:2]
    data = np.ascontiguousarray(rgba)
    if not QImage(data.data, w, h, w * 4, QImage.Format.Format_RGBA8888).save(str(path), "PNG"):
        raise OSError(f"cannot write {path}")
