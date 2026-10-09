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
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from dvd.menu.layout import Button, Page
from dvd.menu.templates import Template
from dvd.menu.templates import template as get_template
from dvd.subs.render import _qt

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"
LEFT_MIDDLE = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


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


def _case(text: str, t: Template) -> str:
    # Turkish capitals: i -> İ, ı -> I (str.upper would turn i into a dotless I).
    return text.replace("i", "İ").replace("ı", "I").upper() if t.uppercase else text


def _text(p: QPainter, rect: QRectF, flags, text: str, rgb, shadow: bool) -> None:
    if shadow:
        p.setPen(QColor(0, 0, 0, 170))
        p.drawText(rect.translated(2, 2), flags, text)
    p.setPen(QColor(*rgb))
    p.drawText(rect, flags, text)


def _shade(p: QPainter, t: Template, w: int, h: int) -> None:
    """Darken where the text goes, so light text reads on any picture."""
    a = t.shade_strength
    if t.shade == "bottom":
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor(0, 0, 0, round(255 * a * 0.15)))
        g.setColorAt(0.45, QColor(0, 0, 0, round(255 * a * 0.25)))
        g.setColorAt(1, QColor(0, 0, 0, round(255 * a)))
        p.fillRect(0, 0, w, h, g)
    elif t.shade == "vignette":
        g = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
        g.setColorAt(0, QColor(0, 0, 0, round(255 * a * 0.35)))
        g.setColorAt(1, QColor(0, 0, 0, round(255 * a)))
        p.fillRect(0, 0, w, h, g)
    else:
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0, QColor(0, 0, 0, round(255 * a)))
        g.setColorAt(0.65, QColor(0, 0, 0, round(255 * a * 0.55)))
        g.setColorAt(1, QColor(0, 0, 0, round(255 * a * 0.25)))
        p.fillRect(0, 0, w, h, g)


def _marker(t: Template, left: float, width: float, r: QRectF, dw: int, px: int) -> QPainterPath:
    """The cursor mark beside a text button: a bar, an underline or an arrow."""
    path = QPainterPath()
    if t.marker == "underline":
        y = r.center().y() + px * 0.62
        path.addRect(QRectF(left, y, width, max(2.0, px * 0.08)))
    elif t.marker == "arrow":
        s = px * 0.55
        x, cy = left - 0.024 * dw, r.center().y()
        path.moveTo(x, cy - s / 2)
        path.lineTo(x + s * 0.8, cy)
        path.lineTo(x, cy + s / 2)
        path.closeSubpath()
    else:
        bar_h = r.height() * 0.55
        path.addRect(QRectF(left - 0.028 * dw, r.center().y() - bar_h / 2, 0.008 * dw, bar_h))
    return path


def render_page(
    page: Page,
    frame: tuple[int, int, Fraction],
    background: QImage | None = None,
    thumbs: dict[float, QImage] | None = None,
    template: Template | None = None,
    logo: QImage | None = None,
) -> RenderedPage:
    """`frame`: disc frame width, height and display aspect. `background`: any size, it is
    scaled to cover the frame; None draws the template's plain backdrop."""
    _fonts()
    t = template or get_template("minimal")
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
    if t.tint is not None:
        p.fillRect(canvas.rect(), QColor(*t.tint, 90))
    _shade(p, t, dw, fh)

    title_font = _font(t.title_font, t.title_size * fh, 600)
    label_font = _font(t.label_font, t.label_size * fh, 600)
    centred = t.title_align == "center"
    align = Qt.AlignmentFlag.AlignHCenter if centred else Qt.AlignmentFlag.AlignLeft
    if page.kind == "main" and logo is not None and not logo.isNull():
        # The film's logo in place of the title: up to half the width, 18 % of the height.
        box = QRectF(0.10 * dw, t.title_y * fh, 0.80 * dw, 0.18 * fh)
        keep = Qt.AspectRatioMode.KeepAspectRatio
        scaled = logo.scaled(round(0.5 * dw), round(box.height()), keep,
                             Qt.TransformationMode.SmoothTransformation)  # fmt: skip
        x = box.center().x() - scaled.width() / 2 if centred else box.left()
        p.drawImage(QPointF(x, box.top()), scaled)
    elif page.title:
        p.setFont(title_font)
        title_rect = QRectF(0.10 * dw, t.title_y * fh, 0.80 * dw, 0.11 * fh)
        _text(p, title_rect, align | Qt.AlignmentFlag.AlignVCenter, page.title, t.title, t.shadow)
    if page.subtitle:  # under the title (or the logo)
        p.setFont(label_font)
        sub_rect = QRectF(0.10 * dw, (t.title_y + 0.11) * fh, 0.80 * dw, 0.06 * fh)
        _text(p, sub_rect, align | Qt.AlignmentFlag.AlignVCenter, page.subtitle, t.muted,
              t.shadow)  # fmt: skip
    p.setFont(label_font)
    for text, rect in page.headings:
        _text(p, _px(rect, dw, fh), Qt.AlignmentFlag.AlignVCenter, _case(text, t), t.muted,
              t.shadow)  # fmt: skip

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
            image = (thumbs or {}).get((b.thumb_title, b.thumb))
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
        label = _case(b.label, t)
        width = QFontMetricsF(label_font).horizontalAdvance(label)
        indent = 0.0 if t.marker == "underline" else 0.028 * dw  # room for the bar or arrow
        left = r.center().x() - width / 2 if centred else r.left() + indent
        baseline = r.center().y() + label_font.pixelSize() * 0.36
        _text(p, QRectF(left, r.top(), width + 4, r.height()), LEFT_MIDDLE, label, t.text,
              t.shadow)  # fmt: skip
        # Overlay: the label redrawn in the state colour plus the template's marker.
        glyphs = QPainterPath()
        glyphs.addText(QPointF(left, baseline), label_font, label)
        for k, q in painters.items():
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(QColor(*colours[k]))
            q.drawPath(glyphs)
            q.drawPath(_marker(t, left, width, r, dw, label_font.pixelSize()))
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
