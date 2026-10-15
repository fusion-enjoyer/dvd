"""Menu editor canvas: the page picture with its buttons and layers as boxes that can be
moved and resized, the TV safe areas, and the remote's arrow paths between buttons."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from dvd.gui.theme import color
from dvd.menu.layout import overlapping

GRID = 0.005  # positions snap to half a percent of the frame
HANDLE = 10  # px, the resize corner
LAYER = "layer-"  # id prefix of layer boxes ("layer-0" is the page's first layer)


class MenuCanvas(QWidget):
    selected = Signal(str)  # button id
    edited = Signal(str, tuple)  # button id, new rect (fractions of the frame)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.image: QImage | None = None
        self.aspect = 16 / 9
        self.buttons: list = []  # menu.layout.Button
        self.layer_ids: list[str] = []
        self.rects: dict[str, tuple[float, float, float, float]] = {}
        self.current: str | None = None
        self.show_nav = False
        self._drag: tuple[str, str, QPointF, tuple] | None = None  # id, move|resize, start, rect

    def set_page(self, buttons: list, image: QImage | None, aspect: float,
                 layers: list | None = None) -> None:  # fmt: skip
        """`layers`: the page's MenuLayer list; their boxes are "layer-0", "layer-1", ..."""
        self.buttons, self.image, self.aspect = buttons, image, aspect
        self.layer_ids = [f"{LAYER}{i}" for i in range(len(layers or []))]
        self.rects = {b.id: tuple(b.rect) for b in buttons}
        self.rects.update({f"{LAYER}{i}": tuple(x.rect) for i, x in enumerate(layers or [])})
        if self.current not in self.rects:
            self.current = buttons[0].id if buttons else None
        self.update()

    # ---------------------------------------------------------------- geometry

    def _frame(self) -> QRectF:
        r = QRectF(self.rect())
        w = min(r.width(), r.height() * self.aspect)
        f = QRectF(0, 0, w, w / self.aspect)
        f.moveCenter(r.center())
        return f

    def _px(self, rect) -> QRectF:
        f = self._frame()
        x, y, w, h = rect
        return QRectF(f.left() + x * f.width(), f.top() + y * f.height(), w * f.width(),
                      h * f.height())  # fmt: skip

    def _hit(self, pos: QPointF) -> tuple[str | None, str]:
        """Buttons lie over the layers; the last layer over the earlier ones."""
        for bid in [*(b.id for b in reversed(self.buttons)), *reversed(self.layer_ids)]:
            r = self._px(self.rects[bid])
            corner = QRectF(r.right() - HANDLE, r.bottom() - HANDLE, 2 * HANDLE, 2 * HANDLE)
            if bid == self.current and corner.contains(pos):
                return bid, "resize"
            if r.contains(pos):
                return bid, "move"
        return None, ""

    def button_rects(self) -> dict[str, tuple]:
        return {k: v for k, v in self.rects.items() if not k.startswith(LAYER)}

    @staticmethod
    def _snap(v: float) -> float:
        return round(v / GRID) * GRID

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        bid, mode = self._hit(event.position())
        if bid is None:
            return
        self.current = bid
        self.selected.emit(bid)
        self._drag = (bid, mode, event.position(), self.rects[bid])
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            cursor = Qt.CursorShape.SizeFDiagCursor if self._hit(event.position())[1] == "resize" \
                else Qt.CursorShape.ArrowCursor  # fmt: skip
            self.setCursor(cursor)
            return
        bid, mode, start, (x, y, w, h) = self._drag
        f = self._frame()
        dx = (event.position().x() - start.x()) / f.width()
        dy = (event.position().y() - start.y()) / f.height()
        if mode == "move":
            nx = min(max(0.0, self._snap(x + dx)), 1 - w)
            ny = min(max(0.0, self._snap(y + dy)), 1 - h)
            self.rects[bid] = (nx, ny, w, h)
        else:
            nw = min(max(0.04, self._snap(w + dx)), 1 - x)
            nh = min(max(0.03, self._snap(h + dy)), 1 - y)
            self.rects[bid] = (x, y, nw, nh)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            bid, _mode, _start, before = self._drag
            self._drag = None
            if self.rects[bid] != before:
                self.edited.emit(bid, tuple(round(v, 4) for v in self.rects[bid]))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Arrow keys nudge the chosen button (Shift: ten times further)."""
        steps = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1),
                 Qt.Key.Key_Down: (0, 1)}  # fmt: skip
        if self.current is None or event.key() not in steps:
            super().keyPressEvent(event)
            return
        sx, sy = steps[event.key()]
        k = GRID * (10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)
        x, y, w, h = self.rects[self.current]
        new = (min(max(0.0, x + sx * k), 1 - w), min(max(0.0, y + sy * k), 1 - h), w, h)
        self.rects[self.current] = tuple(round(v, 4) for v in new)
        self.edited.emit(self.current, self.rects[self.current])
        self.update()

    # ------------------------------------------------------------------ paint

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), color("video"))
        f = self._frame()
        if self.image is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(f, self.image)
        # TV safe areas: action (90 %) and title (80 %).
        for share in (0.9, 0.8):
            guide = QRectF(0, 0, f.width() * share, f.height() * share)
            guide.moveCenter(f.center())
            pen = QPen(QColor(255, 255, 255, 90), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(guide)
        for lid in self.layer_ids:
            r = self._px(self.rects[lid])
            chosen = lid == self.current
            p.setPen(QPen(color("amber") if chosen else color("bilgi"), 2 if chosen else 1,
                          Qt.PenStyle.DashLine))  # fmt: skip
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)
            if chosen:
                p.setBrush(color("amber"))
                p.drawRect(QRectF(r.right() - HANDLE / 2, r.bottom() - HANDLE / 2, HANDLE, HANDLE))
        clash = {i for pair in overlapping(self.button_rects()) for i in pair}
        for b in self.buttons:
            r = self._px(self.rects[b.id])
            chosen = b.id == self.current
            edge = color("hata") if b.id in clash else color("amber") if chosen \
                else QColor(255, 255, 255, 150)  # fmt: skip
            p.setPen(QPen(edge, 2 if chosen else 1))
            p.setBrush(QBrush(QColor(240, 180, 73, 40)) if chosen else Qt.BrushStyle.NoBrush)
            p.drawRect(r)
            if chosen:
                p.setBrush(edge)
                p.drawRect(QRectF(r.right() - HANDLE / 2, r.bottom() - HANDLE / 2, HANDLE, HANDLE))
        if self.show_nav:
            self._arrows(p)
        p.end()

    def _arrows(self, p: QPainter) -> None:
        centre = {b.id: self._px(self.rects[b.id]).center() for b in self.buttons}
        p.setPen(QPen(color("bilgi"), 1.5))
        p.setBrush(color("bilgi"))
        for b in self.buttons:
            for target in b.nav.values():
                if target not in centre:
                    continue
                a, z = centre[b.id], centre[target]
                v = z - a
                length = max(1.0, (v.x() ** 2 + v.y() ** 2) ** 0.5)
                ux, uy = v.x() / length, v.y() / length
                tip = QPointF(z.x() - ux * 14, z.y() - uy * 14)  # stop short of the centre
                start = QPointF(a.x() + ux * 14, a.y() + uy * 14)
                p.drawLine(start, tip)
                head = QPainterPath()
                head.moveTo(tip)
                head.lineTo(tip.x() - ux * 8 - uy * 4, tip.y() - uy * 8 + ux * 4)
                head.lineTo(tip.x() - ux * 8 + uy * 4, tip.y() - uy * 8 - ux * 4)
                head.closeSubpath()
                p.drawPath(head)
