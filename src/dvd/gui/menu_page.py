"""Menu page: menus on or off, which pages, the background, and a preview of each page as
it will be on the disc (the same render code the build uses)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dvd.gui import tasks
from dvd.gui.i18n import t
from dvd.gui.menu_canvas import MenuCanvas
from dvd.gui.widgets import ModeSwitch, VideoWell
from dvd.menu.layout import overlapping
from dvd.probe import SourceInfo
from dvd.project import edit
from dvd.project.create import default_menus
from dvd.project.model import ButtonEdit, MenuBackground, MenuPage, Project

OPTIONAL = ("chapters", "languages")  # pages the user can leave out; main is always there


def render_preview(project: Project, info: SourceInfo, source: Path, project_dir: Path,
                   frame: tuple, display: tuple[int, int]) -> list:  # fmt: skip
    """(page, rendered page) for every disc menu page, drawn as the build draws them."""
    from dvd.menu.layout import expand
    from dvd.menu.pictures import background_image, frame_images
    from dvd.menu.render import render_page
    from dvd.menu.templates import template

    pages = expand(project, info)
    backdrop = background_image(project.menus.background, source, info, project_dir, display)
    times = sorted({b.thumb for p in pages for b in p.buttons if b.thumb is not None})
    width = round(0.22 * display[0])
    thumbs = frame_images(source, info, times, (width, round(width * 9 / 16))) if times else {}
    tpl = template(project.menus.template)
    return [(page, render_page(page, frame, backdrop, thumbs, tpl)) for page in pages]


def compose(rendered, button: int | None, layer: str = "highlight") -> QImage:
    """The page as the player shows it: the overlay only inside the button under the cursor
    (`layer` "select" for the moment it is pressed); None: no cursor."""
    image = rendered.background.convertToFormat(QImage.Format.Format_ARGB32)
    if button is None or not rendered.buttons:
        return image
    source = getattr(rendered, layer)
    overlay = np.zeros_like(source)
    x0, y0, x1, y1 = rendered.buttons[button][1]
    overlay[y0:y1, x0:x1] = source[y0:y1, x0:x1]
    h, w = overlay.shape[:2]
    painter = QPainter(image)
    painter.drawImage(0, 0, QImage(overlay.data, w, h, w * 4, QImage.Format.Format_RGBA8888))
    painter.end()
    return image


class MenuEditorPage(QWidget):
    changed = Signal()

    def __init__(self, position: Callable[[], float]) -> None:
        """`position`: source time of the picture page's preview, for "use this frame"."""
        super().__init__()
        self.position = position
        self.project: Project | None = None
        self.info: SourceInfo | None = None
        self.source = self.project_dir = Path()
        self.frame: tuple | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # arrow keys in "try" mode
        self.previews: list = []  # (page, rendered page)
        self.sim = None
        self.dirty = False
        self.request = 0
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 20)
        box.setSpacing(12)
        title = QLabel(t("menu.title"))
        title.setObjectName("pageTitle")
        box.addWidget(title)
        self.enabled = QCheckBox(t("menu.enabled"))
        self.enabled.toggled.connect(self._toggle)
        box.addWidget(self.enabled)
        self.options = QWidget()
        opts = QHBoxLayout(self.options)
        opts.setContentsMargins(0, 0, 0, 0)
        self.page_checks: dict[str, QCheckBox] = {}
        for kind in OPTIONAL:
            check = QCheckBox(t(f"menu.page.{kind}"))
            check.toggled.connect(lambda on, k=kind: self._set_page(k, on))
            self.page_checks[kind] = check
            opts.addWidget(check)
        opts.addSpacing(16)
        opts.addWidget(QLabel(t("menu.template")))
        self.template = QComboBox()
        for name in ("minimal", "sinematik", "2000ler"):
            self.template.addItem(t(f"menu.template.{name}"), name)
        self.template.currentIndexChanged.connect(self._template_changed)
        opts.addWidget(self.template)
        opts.addSpacing(16)
        opts.addWidget(QLabel(t("menu.background")))
        self.bg_kind = QComboBox()
        for key in ("frame", "image", "color"):
            self.bg_kind.addItem(t(f"menu.bg.{key}"), key)
        self.bg_kind.currentIndexChanged.connect(self._bg_kind_changed)
        opts.addWidget(self.bg_kind)
        self.bg_action = QPushButton()
        self.bg_action.clicked.connect(self._bg_action)
        opts.addWidget(self.bg_action)
        opts.addStretch()
        box.addWidget(self.options)
        row = QHBoxLayout()
        self.page_list = QComboBox()
        self.page_list.setMinimumWidth(200)
        self.page_list.currentIndexChanged.connect(self._show_preview)
        self.lit = ModeSwitch({"plain": t("menu.view.plain"), "lit": t("menu.view.lit"),
                               "try": t("menu.view.try"), "edit": t("menu.view.edit")},
                              "lit")  # fmt: skip
        self.view = "lit"
        self.lit.changed.connect(self._set_view)
        row.addWidget(self.page_list)
        row.addWidget(self.lit)
        row.addStretch()
        box.addLayout(row)
        self.well = VideoWell()
        box.addWidget(self.well, 1)
        self.editor = QWidget()
        ed = QHBoxLayout(self.editor)
        ed.setContentsMargins(0, 0, 0, 0)
        self.canvas = MenuCanvas()
        self.canvas.selected.connect(self._button_selected)
        self.canvas.edited.connect(self._button_moved)
        ed.addWidget(self.canvas, 1)
        side = QVBoxLayout()
        side.addWidget(QLabel(t("menu.edit.label")))
        self.label_edit = QLineEdit()
        self.label_edit.setMaxLength(60)
        self.label_edit.editingFinished.connect(self._label_changed)
        side.addWidget(self.label_edit)
        self.reset = QPushButton(t("menu.edit.reset"))
        self.reset.clicked.connect(self._reset_button)
        side.addWidget(self.reset)
        self.nav_check = QCheckBox(t("menu.edit.arrows"))
        self.nav_check.toggled.connect(self._show_arrows)
        side.addWidget(self.nav_check)
        self.edit_note = QLabel(t("menu.edit.hint"))
        self.edit_note.setObjectName("muted")
        self.edit_note.setWordWrap(True)
        side.addWidget(self.edit_note)
        side.addStretch()
        holder = QWidget()
        holder.setFixedWidth(230)
        holder.setLayout(side)
        ed.addWidget(holder)
        self.editor.hide()
        box.addWidget(self.editor, 1)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        box.addWidget(self.status)

    # ------------------------------------------------------------------ show

    def show_project(self, project: Project, info: SourceInfo, source: Path, project_dir: Path,
                     frame: tuple | None) -> None:  # fmt: skip
        self.project, self.info, self.source = project, info, source
        self.project_dir, self.frame = project_dir, frame
        self.dirty = True
        menus = project.menus
        widgets = [self.enabled, self.bg_kind, self.template, *self.page_checks.values()]
        for w in widgets:
            w.blockSignals(True)
        self.enabled.setChecked(menus is not None)
        self.options.setVisible(menus is not None)
        self.page_list.setVisible(menus is not None)
        self.lit.setVisible(menus is not None)
        if menus is not None:
            kinds = {p.kind for p in menus.pages}
            for kind, check in self.page_checks.items():
                check.setChecked(kind in kinds)
            self.template.setCurrentIndex(self.template.findData(menus.template))
            bg = menus.background
            key = "frame" if bg.frame else "image" if bg.image else "color"
            self.bg_kind.setCurrentIndex(self.bg_kind.findData(key))
            self._bg_button_text()
        for w in widgets:
            w.blockSignals(False)
        if self.isVisible():
            self._refresh_preview()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if self.dirty:
            self._refresh_preview()

    def _bg_button_text(self) -> None:
        bg, key = self.project.menus.background, self.bg_kind.currentData()
        text = {"frame": t("menu.bg.use_frame", tc=(bg.frame or "-").split(".")[0]),
                "image": Path(bg.image).name if bg.image else t("menu.bg.pick_image"),
                "color": bg.color}[key]  # fmt: skip
        self.bg_action.setText(text)

    def _refresh_preview(self) -> None:
        self.dirty = False
        if self.project is None or self.project.menus is None or self.frame is None:
            self.previews = []
            self.page_list.clear()
            self.well.set_image(None, 16 / 9, t("menu.off") if self.project else "")
            return
        self.request += 1
        request = self.request
        self.status.setText(t("menu.rendering"))
        frame = self.frame
        display = (round(frame[1] * frame[2]), frame[1])
        args = (self.project, self.info, self.source, self.project_dir, frame, display)

        def done(previews) -> None:
            if request != self.request:
                return
            self.previews = previews
            current = self.page_list.currentIndex()
            self.page_list.blockSignals(True)
            self.page_list.clear()
            for page, _rendered in previews:
                self.page_list.addItem(page.title)
            self.page_list.setCurrentIndex(min(max(0, current), len(previews) - 1))
            self.page_list.blockSignals(False)
            self.status.setText("")
            self._new_simulator()
            self._show_preview()

        tasks.run(lambda: render_preview(*args), done, self.status.setText)

    def _set_view(self, view: str) -> None:
        self.view = view
        self.well.setVisible(view != "edit")
        self.editor.setVisible(view == "edit")
        self.page_list.setEnabled(view != "try")
        if view == "try":
            self._new_simulator()
            self.setFocus()
        self._show_preview()

    def _new_simulator(self) -> None:
        from dvd.menu.simulator import Simulator

        if not self.previews or self.project is None or self.project.menus is None:
            self.sim = None
            return
        subs = edit.disc_subtitles(self.project.titles[0])
        self.sim = Simulator([p for p, _r in self.previews], self.project.menus.first,
                             subtitles_on=bool(subs) and subs[0].default)  # fmt: skip

    def _show_preview(self, layer: str = "highlight") -> None:
        if self.frame is None or not self.previews:
            return
        aspect = float(self.frame[2])
        if self.view == "try" and self.sim is not None:
            ids = [p.id for p, _r in self.previews]
            rendered = self.previews[ids.index(self.sim.page.id)][1]
            self.well.set_image(compose(rendered, self.sim.state.button, layer), aspect)
            self.status.setText(self._sim_status())
            return
        i = self.page_list.currentIndex()
        if not 0 <= i < len(self.previews):
            return
        page, rendered = self.previews[i]
        if self.view == "edit":
            self.canvas.set_page(page.buttons, compose(rendered, None), aspect)
            self._button_selected(self.canvas.current)
            return
        self.well.set_image(compose(rendered, 0 if self.view == "lit" else None), aspect)

    # ------------------------------------------------------------------ editor

    def _spec(self) -> MenuPage | None:
        """The project page a shown page comes from ("chapters-2" comes from "chapters")."""
        i = self.page_list.currentIndex()
        if self.project is None or self.project.menus is None or not 0 <= i < len(self.previews):
            return None
        page_id = self.previews[i][0].id
        for spec in self.project.menus.pages:
            if page_id == spec.id or page_id.startswith(spec.id + "-"):
                return spec
        return None

    def _edit_button(self, bid: str, **change) -> None:
        spec = self._spec()
        if spec is None:
            return
        edits = dict(spec.edits)
        current = edits.get(bid, ButtonEdit()).model_dump()
        current.update(change)
        edits[bid] = ButtonEdit(**current)
        spec.edits = edits
        self._changed()

    def _button_selected(self, bid: str | None) -> None:
        button = next((b for b in self.canvas.buttons if b.id == bid), None)
        self.label_edit.setEnabled(button is not None)
        self.label_edit.setText(button.label if button else "")
        clash = overlapping(self.canvas.rects)
        self.edit_note.setText(t("menu.edit.overlap") if clash else t("menu.edit.hint"))

    def _button_moved(self, bid: str, rect: tuple) -> None:
        self._edit_button(bid, rect=rect)

    def _label_changed(self) -> None:
        bid, text = self.canvas.current, self.label_edit.text().strip()
        button = next((b for b in self.canvas.buttons if b.id == bid), None)
        if button is not None and text and text != button.label:
            self._edit_button(bid, label=text)

    def _reset_button(self) -> None:
        spec, bid = self._spec(), self.canvas.current
        if spec is not None and bid in spec.edits:
            spec.edits = {k: v for k, v in spec.edits.items() if k != bid}
            self._changed()

    def _show_arrows(self, on: bool) -> None:
        self.canvas.show_nav = on
        self.canvas.update()

    def _sim_status(self) -> str:
        from dvd.lang import name_tr

        title, s = self.project.titles[0], self.sim.state
        audio = edit.disc_audio(title)
        subs = edit.disc_subtitles(title)
        parts = [t("menu.sim.audio", lang=name_tr(audio[s.audio].lang) if s.audio < len(audio)
                   else "?"),
                 t("menu.sim.subs", lang=t("menu.sim.off") if s.subtitle is None or
                   s.subtitle >= len(subs) else name_tr(subs[s.subtitle].lang))]  # fmt: skip
        if s.playing:
            parts.append(t("menu.sim.playing", chapter=s.playing[1]))
        return "  ·  ".join(parts) + "   " + t("menu.sim.keys")

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self.view != "try" or self.sim is None:
            super().keyPressEvent(event)
            return
        key = event.key()
        moves = {Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
                 Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right"}  # fmt: skip
        if key in moves:
            self.sim.move(moves[key])
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.sim.press()
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_M):
            self.sim.menu_key()
        else:
            super().keyPressEvent(event)
            return
        self._show_preview()

    # ----------------------------------------------------------------- edits

    def _changed(self) -> None:
        self.changed.emit()

    def _toggle(self, on: bool) -> None:
        self.project.menus = default_menus(self.info) if on else None
        self._changed()

    def _set_page(self, kind: str, on: bool) -> None:
        menus = self.project.menus
        pages = [p for p in menus.pages if p.kind != kind]
        if on:
            pages.append(MenuPage(id=kind, kind=kind))
        order = {"main": 0, "chapters": 1, "languages": 2}
        menus.pages = sorted(pages, key=lambda p: order.get(p.kind, 9))
        self._changed()

    def _template_changed(self) -> None:
        self.project.menus.template = self.template.currentData()
        self._changed()

    def _bg_kind_changed(self) -> None:
        key, menus = self.bg_kind.currentData(), self.project.menus
        if key == "frame":
            menus.background = MenuBackground(frame=edit.format_time(self.position()))
        elif key == "color":
            menus.background = MenuBackground(color=menus.background.color)
        else:
            self._pick_image()
            return
        self._changed()

    def _bg_action(self) -> None:
        key, menus = self.bg_kind.currentData(), self.project.menus
        if key == "frame":
            menus.background = MenuBackground(frame=edit.format_time(self.position()))
            self._changed()
        elif key == "image":
            self._pick_image()
        else:
            colour = QColorDialog.getColor(QColor(menus.background.color), self)
            if colour.isValid():
                menus.background = MenuBackground(color=colour.name())
                self._changed()

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("menu.bg.pick_image"), str(self.project_dir),
                                              "Resim (*.png *.jpg *.jpeg *.bmp)")  # fmt: skip
        if path:
            self.project.menus.background = MenuBackground(image=Path(path).as_posix())
        self._changed()
