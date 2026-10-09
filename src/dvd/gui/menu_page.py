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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dvd.gui import tasks
from dvd.gui.i18n import t
from dvd.gui.widgets import ModeSwitch, VideoWell
from dvd.probe import SourceInfo
from dvd.project import edit
from dvd.project.create import default_menus
from dvd.project.model import MenuBackground, MenuPage, Project

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
                               "try": t("menu.view.try")}, "lit")  # fmt: skip
        self.view = "lit"
        self.lit.changed.connect(self._set_view)
        row.addWidget(self.page_list)
        row.addWidget(self.lit)
        row.addStretch()
        box.addLayout(row)
        self.well = VideoWell()
        box.addWidget(self.well, 1)
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
        if 0 <= i < len(self.previews):
            rendered = self.previews[i][1]
            self.well.set_image(compose(rendered, 0 if self.view == "lit" else None), aspect)

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
