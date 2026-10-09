"""Small reusable widgets drawn to the design system."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QWidget

from dvd.budget.planner import Plan
from dvd.gui.theme import color


class ModeSwitch(QWidget):
    """Segmented control: Basit | Profesyonel."""

    changed = Signal(str)

    def __init__(self, labels: dict[str, str], current: str) -> None:
        super().__init__()
        self.setObjectName("modeSwitch")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in labels.items():
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(key == current)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            layout.addWidget(b)
            self.buttons[key] = b

    def set_mode(self, mode: str) -> None:
        self.buttons[mode].setChecked(True)


class BudgetBar(QWidget):
    """Disc usage: one green bar in simple mode, segments per stream type in pro mode."""

    def __init__(self) -> None:
        super().__init__()
        self.plan: Plan | None = None
        self.mode = "basit"
        self.setMinimumHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_plan(self, plan: Plan | None, mode: str) -> None:
        self.plan, self.mode = plan, mode
        self.setFixedHeight(10 if mode == "basit" else 8)
        self.update()

    def segments(self) -> list[tuple[float, QColor]]:
        p = self.plan
        if p is None:
            return []
        total = p.capacity_bytes
        size = p.duration / 8 * 1000 / (1 - 0.03)  # bytes per kbit/s over the film
        parts = [(p.video_kbps * size, color("amber")), (p.audio_kbps * size, color("bilgi")),
                 (p.subtitle_kbps * size, color("menu_seg"))]  # fmt: skip
        if self.mode == "basit":
            used = sum(v for v, _ in parts)
            state = "basari" if p.fits and not p.warnings else "uyari" if p.fits else "hata"
            return [(min(used, total) / total, color(state))]
        return [(min(v, total) / total, c) for v, c in parts]

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        radius = r.height() / 2 if self.mode == "basit" else 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color("girdi"), Qt.BrushStyle.SolidPattern))
        painter.drawRoundedRect(r, radius, radius)
        painter.setBrush(QBrush(color("cizgi_zayif"), Qt.BrushStyle.BDiagPattern))
        painter.drawRoundedRect(r, radius, radius)
        x = 0.0
        painter.setClipRect(r)
        for fraction, c in self.segments():
            w = fraction * r.width()
            painter.setBrush(c)
            painter.drawRect(QRectF(x, 0, w, r.height()))
            x += w
        painter.end()


class VideoWell(QWidget):
    """Neutral black frame for previews; the picture keeps its display aspect ratio."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("videoWell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.image: QImage | None = None
        self.message = ""
        self.aspect = 16 / 9
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_image(self, image: QImage | None, aspect: float, message: str = "") -> None:
        self.image, self.aspect, self.message = image, aspect, message
        self.update()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return round(width / self.aspect)

    def _target(self) -> QRectF:
        """Where the picture is drawn: as large as fits, centred."""
        r = QRectF(self.rect())
        w = min(r.width(), r.height() * self.aspect)
        target = QRectF(0, 0, w, w / self.aspect)
        target.moveCenter(r.center())
        return target

    def _smooth(self) -> bool:
        return True

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), color("video"))
        r = QRectF(self.rect())
        if self.image is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._smooth())
            painter.drawImage(self._target(), self.image)
        elif self.message:
            painter.setPen(QPen(color("metin_3")))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, self.message)
        painter.end()


class CompareWell(VideoWell):
    """Video well that shows one of two pictures, or both split by a draggable line.

    Zoom 0 fits the picture; 1, 2, 4 show that many screen pixels per picture pixel, around
    `center` (picture coordinates, 0..1). Dragging pans a zoomed picture; in split view the
    left button moves the line and the right button pans."""

    def __init__(self) -> None:
        super().__init__()
        self.other: QImage | None = None
        self.mode = "b"  # "a", "b" or "split"
        self.split = 0.5
        self.labels = ("", "")
        self.zoom = 0
        self.center = QPointF(0.5, 0.5)
        self._pan_from: QPointF | None = None
        self.setMouseTracking(False)

    def set_zoom(self, zoom: int) -> None:
        self.zoom = zoom
        self.update()

    def set_pair(self, a: QImage, b: QImage, aspect: float, labels: tuple[str, str]) -> None:
        self.other, self.labels = a, labels
        self.set_image(b, aspect)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()

    def _target(self) -> QRectF:
        if not self.zoom or self.image is None:
            return super()._target()
        # Zoom counts screen pixels per picture line, so 200% shows every disc line twice.
        r = QRectF(self.rect())
        h = self.image.height() * self.zoom
        w = h * self.aspect

        def clamp(c: float, view: float, size: float) -> float:
            half = view / 2 / size  # keep the picture covering the well where it is larger
            return min(max(c, half), 1 - half) if size > view else 0.5

        self.center = QPointF(clamp(self.center.x(), r.width(), w),
                              clamp(self.center.y(), r.height(), h))  # fmt: skip
        return QRectF(r.center().x() - self.center.x() * w, r.center().y() - self.center.y() * h,
                      w, h)  # fmt: skip

    def _smooth(self) -> bool:
        return self.zoom < 2  # show whole pixels when magnified

    def _visible(self) -> QRectF:
        """The part of the well the picture covers; the split line is placed across it."""
        return self._target().intersected(QRectF(self.rect()))

    def _pans(self, event) -> bool:
        if not self.zoom:
            return False
        return self.mode != "split" or event.buttons() & Qt.MouseButton.RightButton

    def _drag(self, event) -> None:
        if self._pans(event):
            if self._pan_from is not None:
                t = self._target()
                d = event.position() - self._pan_from
                self.center = QPointF(
                    min(1.0, max(0.0, self.center.x() - d.x() / t.width())),
                    min(1.0, max(0.0, self.center.y() - d.y() / t.height())),
                )
            self._pan_from = event.position()
            self.update()
        elif self.mode == "split":
            v = self._visible()
            self.split = min(1.0, max(0.0, (event.position().x() - v.left()) / v.width()))
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._pan_from = None
        self._drag(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._drag(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pan_from = None

    def paintEvent(self, event) -> None:  # noqa: N802
        if self.image is None or self.other is None or self.mode == "b":
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), color("video"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._smooth())
        t = self._target()
        painter.drawImage(t, self.other)
        if self.mode == "split":
            v = self._visible()
            x = v.left() + self.split * v.width()
            painter.save()
            painter.setClipRect(QRectF(x, t.top(), t.right() - x, t.height()))
            painter.drawImage(t, self.image)
            painter.restore()
            painter.setPen(QPen(color("amber"), 2))
            painter.drawLine(int(x), int(v.top()), int(x), int(v.bottom()))
            margin, fm = 8, painter.fontMetrics()
            for text, left in ((self.labels[0], True), (self.labels[1], False)):
                if not text:
                    continue
                w, h = fm.horizontalAdvance(text) + 12, fm.height() + 6
                x0 = v.left() + margin if left else v.right() - margin - w
                box = QRectF(x0, v.top() + margin, w, h)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 160))  # readable over any picture
                painter.drawRoundedRect(box, 3, 3)
                painter.setPen(QPen(color("metin")))
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
