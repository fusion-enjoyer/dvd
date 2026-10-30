"""Disc map page (pro mode): the disc's flow as a graph, from the moment it goes in through
the intros and menu pages to the titles and what follows them. Clicking a menu page opens it
in the menu editor."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QMenu, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from dvd.gui.i18n import t
from dvd.gui.theme import color
from dvd.menu import mapedit
from dvd.menu.discmap import DiscMap, columns, disc_map

NODE_W, NODE_H = 190, 50
COL_GAP, ROW_GAP, MARGIN = 170, 26, 24
KIND_COLOUR = {"start": "metin_3", "intro": "bilgi", "page": "amber", "title": "basari",
               "hidden": "hata", "end": "metin_3"}  # fmt: skip


class MapCanvas(QWidget):
    page_clicked = Signal(str)  # menu page id
    page_menu = Signal(str, QPointF)  # menu page id, where on the screen (right click)

    def __init__(self) -> None:
        super().__init__()
        self.map: DiscMap | None = None
        self.boxes: dict[str, QRectF] = {}
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_map(self, m: DiscMap | None) -> None:
        self.map, self.boxes = m, {}
        if m is not None:
            for c, nodes in enumerate(columns(m)):
                for r, node in enumerate(nodes):
                    x = MARGIN + c * (NODE_W + COL_GAP)
                    y = MARGIN + 30 + r * (NODE_H + ROW_GAP)
                    self.boxes[node.id] = QRectF(x, y, NODE_W, NODE_H)
        right = max((b.right() for b in self.boxes.values()), default=0) + MARGIN
        bottom = max((b.bottom() for b in self.boxes.values()), default=0) + MARGIN + 60
        self.setMinimumSize(int(right), int(bottom))
        self.update()

    def page_at(self, pos: QPointF) -> str | None:
        for node_id, box in self.boxes.items():
            if box.contains(pos) and node_id.startswith("page:"):
                return node_id.removeprefix("page:")
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        page = self.page_at(event.position())
        if page is not None and event.button() == Qt.MouseButton.LeftButton:
            self.page_clicked.emit(page)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        page = self.page_at(QPointF(event.pos()))
        if page is not None:
            self.page_menu.emit(page, QPointF(event.globalPos()))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), color("zemin"))
        if self.map is None:
            p.end()
            return
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        heads = ["Disk", "Girişler", "Menüler", "Başlıklar"]
        kinds = [{n.kind for n in col} for col in columns(self.map)]
        names = {"start": "Disk", "intro": "Girişler", "page": "Menüler"}
        p.setPen(color("metin_3"))
        for c, ks in enumerate(kinds):
            head = next((names[k] for k in ("start", "intro", "page") if k in ks), heads[-1])
            p.drawText(QPointF(MARGIN + c * (NODE_W + COL_GAP), MARGIN + 12), head.upper())
        seen: dict[tuple[str, str], int] = {}
        for e in self.map.edges:
            pair = (e.src, e.dst)
            self._edge(p, e, small, seen.get(pair, 0))
            seen[pair] = seen.get(pair, 0) + 1
        for node in self.map.nodes:
            self._node(p, node, small)
        p.end()

    def _edge(self, p: QPainter, e, small: QFont, nth: int = 0) -> None:
        """An arrow between two boxes; `nth` > 0 for a further edge between the same pair
        (its label moves down a line)."""
        a, b = self.boxes.get(e.src), self.boxes.get(e.dst)
        if a is None or b is None:
            return
        forward = b.left() > a.right()
        same_column = abs(a.left() - b.left()) < 1
        style = {"dashed": Qt.PenStyle.DashLine, "dotted": Qt.PenStyle.DotLine}.get(
            e.style, Qt.PenStyle.SolidLine)  # fmt: skip
        pen = QPen(color("metin_2") if e.style == "solid" else color("metin_3"), 1.4, style)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        if forward:
            start, end = QPointF(a.right(), a.center().y()), QPointF(b.left(), b.center().y())
            bend = (end.x() - start.x()) / 2
            path.moveTo(start)
            path.cubicTo(start + QPointF(bend, 0), end - QPointF(bend, 0), end)
            mid = path.pointAtPercent(0.3)
        elif same_column and 0 < b.top() - a.bottom() <= ROW_GAP + 1:  # the next one down
            start, end = QPointF(a.center().x(), a.bottom()), QPointF(b.center().x(), b.top())
            path.moveTo(start)
            path.lineTo(end)
            mid = QPointF(start.x() + 86, (start.y() + end.y()) / 2 + 5)  # label beside it
        elif same_column and b.top() > a.top():  # further down: round the right side
            start, end = QPointF(a.right(), a.center().y() + 8), QPointF(b.right(), b.center().y())
            reach = 22 + (b.top() - a.top()) * 0.10
            path.moveTo(start)
            path.cubicTo(start + QPointF(reach, 0), end + QPointF(reach, 0), end)
            mid = QPointF(start.x() + reach * 0.75 + 50, (start.y() + end.y()) / 2)
        elif same_column:  # back up the column: round the left side
            start, end = QPointF(a.left(), a.center().y()), QPointF(b.left(), b.center().y())
            reach = 26 + (a.top() - b.top()) * 0.12
            path.moveTo(start)
            path.cubicTo(start - QPointF(reach, 0), end - QPointF(reach, 0), end)
            mid = QPointF(start.x() - reach * 0.75 - 60, (start.y() + end.y()) / 2)
        else:  # back to an earlier column: a loop under the boxes
            start, end = QPointF(a.center().x(), a.bottom()), QPointF(b.center().x(), b.bottom())
            depth = 30 + abs(start.x() - end.x()) * 0.08
            path.moveTo(start)
            path.cubicTo(start + QPointF(0, depth), end + QPointF(0, depth), end)
            mid = (start + end) / 2 + QPointF(0, depth * 0.75)
        p.drawPath(path)
        tip = path.pointAtPercent(1.0)
        before = path.pointAtPercent(0.97)
        v = tip - before
        length = max(1e-6, (v.x() ** 2 + v.y() ** 2) ** 0.5)
        ux, uy = v.x() / length, v.y() / length
        head = QPainterPath()
        head.moveTo(tip)
        head.lineTo(tip.x() - ux * 8 - uy * 4, tip.y() - uy * 8 + ux * 4)
        head.lineTo(tip.x() - ux * 8 + uy * 4, tip.y() - uy * 8 - ux * 4)
        head.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pen.color())
        p.drawPath(head)
        if e.text:
            p.setFont(small)
            p.setPen(color("metin_2"))
            box = QRectF(mid.x() - 80, mid.y() - 16 + nth * 13, 160, 14)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, e.text)

    def _node(self, p: QPainter, node, small: QFont) -> None:
        box = self.boxes[node.id]
        accent = color(KIND_COLOUR.get(node.kind, "metin_2"))
        p.setPen(QPen(accent, 1.4))
        p.setBrush(color("panel"))
        p.drawRoundedRect(box, 6, 6)
        p.fillRect(QRectF(box.left(), box.top() + 6, 3, box.height() - 12), accent)
        p.setPen(color("metin"))
        p.setFont(self.font())
        p.drawText(box.adjusted(12, 6, -8, -box.height() / 2), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(node.label, Qt.TextElideMode.ElideRight,
                                              int(box.width() - 20)))  # fmt: skip
        if node.note:
            p.setFont(small)
            p.setPen(color("metin_3"))
            p.drawText(box.adjusted(12, box.height() / 2, -8, -4), Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(node.note, Qt.TextElideMode.ElideRight,
                                                  int(box.width() - 20)))  # fmt: skip


class DiscMapPage(QWidget):
    page_clicked = Signal(str)
    changed = Signal()  # the project was changed from the map

    def __init__(self) -> None:
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 20)
        title = QLabel(t("map.title"))
        title.setObjectName("pageTitle")
        box.addWidget(title)
        hint = QLabel(t("map.hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.canvas = MapCanvas()
        self.canvas.page_clicked.connect(self.page_clicked)
        self.canvas.page_menu.connect(self._page_menu)
        self.project, self.infos = None, []
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        box.addWidget(scroll, 1)
        self.error = QLabel("")
        self.error.setObjectName("muted")
        box.addWidget(self.error)

    def show_project(self, project, infos: list) -> None:
        self.project, self.infos = project, infos
        try:
            self.canvas.set_map(disc_map(project, infos))
            self.error.setText("")
        except (ValueError, KeyError) as exc:
            self.canvas.set_map(None)
            self.error.setText(str(exc))

    def edit_menu(self, page_id: str) -> QMenu:
        """What can be changed from the map on this page (also used by the tests)."""
        menu = QMenu(self)
        menu.addAction(t("map.open"), lambda: self.page_clicked.emit(page_id))
        p = self.project
        page = next((x for x in p.menus.pages if x.id == page_id), None) if p and p.menus else None
        if page is None or page.kind not in mapedit.EDITABLE:
            note = menu.addAction(t("map.fixed"))
            note.setEnabled(False)
            return menu
        names = dict(mapedit.targets(p))
        have = mapedit.links(p, self.infos, page_id)
        add = menu.addMenu(t("map.add_link"))
        for node, name in mapedit.targets(p):
            if node != f"page:{page_id}":
                add.addAction(name, lambda n=node: self._edit(mapedit.add_link, page_id, n))
        remove = menu.addMenu(t("map.remove_link"))
        remove.setEnabled(bool(have))
        for node in have:
            remove.addAction(names[node], lambda n=node: self._edit(mapedit.remove_link,
                                                                   page_id, n))  # fmt: skip
        menu.addSeparator()
        menu.addAction(t("map.add_page"), lambda: self._edit(mapedit.add_page, page_id))
        if page.kind == "custom":
            menu.addAction(t("map.remove_page"), lambda: self._edit(mapedit.remove_page, page_id))
        return menu

    def _page_menu(self, page_id: str, where: QPointF) -> None:
        self.edit_menu(page_id).exec(where.toPoint())

    def _edit(self, change, *args) -> None:
        try:
            change(self.project, self.infos, *args)
        except mapedit.MapEditError as exc:
            self.error.setText(str(exc))
            return
        self.changed.emit()
