"""Small reusable widgets drawn to the design system."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
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

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), color("video"))
        r = QRectF(self.rect())
        target_w = min(r.width(), r.height() * self.aspect)
        target = QRectF(0, 0, target_w, target_w / self.aspect)
        target.moveCenter(r.center())
        if self.image is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, self.image)
        elif self.message:
            painter.setPen(QPen(color("metin_3")))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, self.message)
        painter.end()


class CompareWell(VideoWell):
    """Video well that shows one of two pictures, or both split by a draggable line."""

    def __init__(self) -> None:
        super().__init__()
        self.other: QImage | None = None
        self.mode = "b"  # "a", "b" or "split"
        self.split = 0.5
        self.labels = ("", "")
        self.setMouseTracking(False)

    def set_pair(self, a: QImage, b: QImage, aspect: float, labels: tuple[str, str]) -> None:
        self.other, self.labels = a, labels
        self.set_image(b, aspect)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()

    def _target(self) -> QRectF:
        r = QRectF(self.rect())
        w = min(r.width(), r.height() * self.aspect)
        target = QRectF(0, 0, w, w / self.aspect)
        target.moveCenter(r.center())
        return target

    def _drag(self, event) -> None:
        if self.mode == "split":
            t = self._target()
            self.split = min(1.0, max(0.0, (event.position().x() - t.left()) / t.width()))
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._drag(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._drag(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self.image is None or self.other is None or self.mode == "b":
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), color("video"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        t = self._target()
        painter.drawImage(t, self.other)
        if self.mode == "split":
            x = t.left() + self.split * t.width()
            painter.save()
            painter.setClipRect(QRectF(x, t.top(), t.right() - x, t.height()))
            painter.drawImage(t, self.image)
            painter.restore()
            painter.setPen(QPen(color("amber"), 2))
            painter.drawLine(int(x), int(t.top()), int(x), int(t.bottom()))
            painter.setPen(QPen(color("metin")))
            margin = 8
            painter.drawText(QRectF(t.left() + margin, t.top() + margin, 300, 20), self.labels[0])
            right = QRectF(t.right() - 300 - margin, t.top() + margin, 300, 20)
            painter.drawText(right, Qt.AlignmentFlag.AlignRight, self.labels[1])
        painter.end()
