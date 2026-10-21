"""Menu page: menus on or off, which pages, the background, and a preview of each page as
it will be on the disc (the same render code the build uses)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dvd.gui import tasks
from dvd.gui.disc_page import VIDEO_FILES
from dvd.gui.i18n import t
from dvd.gui.menu_canvas import LAYER, MenuCanvas
from dvd.gui.widgets import ModeSwitch, VideoWell
from dvd.menu.layout import DIRECTIONS, auto_nav, overlapping
from dvd.probe import SourceInfo
from dvd.project import edit
from dvd.project.create import default_menus
from dvd.project.model import (
    MAX_HIDDEN,
    MAX_MENU_LAYERS,
    ButtonEdit,
    HiddenClip,
    MenuBackground,
    MenuLayer,
    MenuPage,
    Project,
)

OPTIONAL = ("chapters", "languages")  # pages the user can leave out; main is always there


def render_preview(project: Project, infos: list[SourceInfo], sources: list[Path],
                   project_dir: Path, frame: tuple, display: tuple[int, int]) -> list:  # fmt: skip
    """(page, rendered page) for every disc menu page, drawn as the build draws them."""
    from dvd.menu.layout import expand
    from dvd.menu.pictures import background_image, button_pictures, layer_images, logo_image
    from dvd.menu.render import render_page
    from dvd.menu.templates import template

    pages = expand(project, infos)
    backdrop = background_image(project.menus.background, sources[0], infos[0], project_dir,
                                display)  # fmt: skip
    thumbs = button_pictures(pages, sources, infos, display)
    tpl = template(project.menus.template)
    logo = logo_image(project.menus.logo, project_dir)
    pictures = layer_images(pages, project_dir)
    return [(page, render_page(page, frame, backdrop, thumbs, tpl, logo, pictures))
            for page in pages]  # fmt: skip


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
        self.infos: list = []
        self.sources: list = []
        self.sim = None
        self.dirty = False
        self.request = 0
        self.wanted_page: str | None = None
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
        self._fill_templates()
        self.template.currentIndexChanged.connect(self._template_changed)
        opts.addWidget(self.template)
        edit_tpl = QPushButton(t("menu.template.edit"))
        edit_tpl.clicked.connect(self._edit_template)
        opts.addWidget(edit_tpl)
        opts.addSpacing(16)
        opts.addWidget(QLabel(t("menu.background")))
        self.bg_kind = QComboBox()
        for key in ("frame", "motion", "image", "color"):
            self.bg_kind.addItem(t(f"menu.bg.{key}"), key)
        self.bg_kind.currentIndexChanged.connect(self._bg_kind_changed)
        opts.addWidget(self.bg_kind)
        self.bg_action = QPushButton()
        self.bg_action.clicked.connect(self._bg_action)
        opts.addWidget(self.bg_action)
        self.motion_secs = QSpinBox()
        self.motion_secs.setRange(5, 60)
        self.motion_secs.setValue(20)
        self.motion_secs.setSuffix(t("menu.bg.motion_unit"))
        self.motion_secs.setToolTip(t("menu.bg.motion_hint"))
        self.motion_secs.editingFinished.connect(self._motion_changed)
        opts.addWidget(self.motion_secs)
        self.tmdb = QPushButton(t("tmdb.open"))
        self.tmdb.setToolTip(t("tmdb.open_hint"))
        self.tmdb.clicked.connect(self._open_tmdb)
        opts.addWidget(self.tmdb)
        opts.addStretch()
        box.addWidget(self.options)
        self.playback = QWidget()
        play_row = QHBoxLayout(self.playback)
        play_row.setContentsMargins(0, 0, 0, 0)
        self.resume = QCheckBox(t("menu.resume"))
        self.resume.setToolTip(t("menu.resume_hint"))
        self.resume.toggled.connect(lambda on: self._set_menus(resume=on))
        self.shuffle = QCheckBox(t("menu.shuffle"))
        self.shuffle.toggled.connect(lambda on: self._set_menus(shuffle=on))
        self.timeout = QSpinBox()
        self.timeout.setRange(0, 250)
        self.timeout.setSingleStep(5)
        self.timeout.setSpecialValueText(t("menu.timeout_off"))
        self.timeout.setSuffix(t("menu.timeout_unit"))
        self.timeout.setToolTip(t("menu.timeout_hint"))
        self.timeout.editingFinished.connect(self._timeout_changed)
        for w in (self.resume, self.shuffle):
            play_row.addWidget(w)
        play_row.addSpacing(16)
        play_row.addWidget(QLabel(t("menu.timeout")))
        play_row.addWidget(self.timeout)
        play_row.addStretch()
        box.addWidget(self.playback)
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
        self.label_title = QLabel(t("menu.edit.label"))
        side.addWidget(self.label_title)
        self.label_edit = QLineEdit()
        self.label_edit.setMaxLength(60)
        self.label_edit.editingFinished.connect(self._label_changed)
        side.addWidget(self.label_edit)
        self.reset = QPushButton(t("menu.edit.reset"))
        self.reset.clicked.connect(self._reset_button)
        side.addWidget(self.reset)
        self.colour = QPushButton(t("menu.layer.colour"))
        self.colour.clicked.connect(self._layer_colour)
        side.addWidget(self.colour)
        adds = QHBoxLayout()
        for kind in ("text", "image", "shape"):
            add = QPushButton(t(f"menu.layer.add_{kind}"))
            add.clicked.connect(lambda _=False, k=kind: self._add_layer(k))
            adds.addWidget(add)
        side.addLayout(adds)
        self.add_hidden = QPushButton(t("menu.hidden.add"))
        self.add_hidden.setToolTip(t("menu.hidden.hint"))
        self.add_hidden.clicked.connect(self._add_hidden)
        side.addWidget(self.add_hidden)
        self.nav_check = QCheckBox(t("menu.edit.arrows"))
        self.nav_check.toggled.connect(self._show_arrows)
        side.addWidget(self.nav_check)
        side.addWidget(QLabel(t("menu.edit.nav")))
        nav_form = QFormLayout()
        self.nav_combos: dict[str, QComboBox] = {}
        for direction in DIRECTIONS:
            combo = QComboBox()
            combo.currentIndexChanged.connect(lambda _i, d=direction: self._nav_changed(d))
            self.nav_combos[direction] = combo
            nav_form.addRow(t(f"menu.edit.{direction}"), combo)
        side.addLayout(nav_form)
        self.edit_note = QLabel(t("menu.edit.hint"))
        self.edit_note.setObjectName("muted")
        self.edit_note.setWordWrap(True)
        side.addWidget(self.edit_note)
        side.addStretch()
        holder = QWidget()
        holder.setLayout(side)
        scroll = QScrollArea()  # the panel outgrows short windows
        scroll.setWidget(holder)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(250)
        ed.addWidget(scroll)
        self.editor.hide()
        box.addWidget(self.editor, 1)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        box.addWidget(self.status)

    # ------------------------------------------------------------------ show

    def show_project(self, project: Project, infos: list[SourceInfo], sources: list[Path],
                     project_dir: Path, frame: tuple | None) -> None:  # fmt: skip
        self.project, self.infos, self.sources = project, infos, sources
        self.info, self.source = infos[0], sources[0]
        self.project_dir, self.frame = project_dir, frame
        self.dirty = True
        menus = project.menus
        widgets = [self.enabled, self.bg_kind, self.template, *self.page_checks.values(),
                   self.resume, self.shuffle, self.timeout]  # fmt: skip
        for w in widgets:
            w.blockSignals(True)
        self.enabled.setChecked(menus is not None)
        self.options.setVisible(menus is not None)
        self.playback.setVisible(menus is not None)
        self.page_list.setVisible(menus is not None)
        self.lit.setVisible(menus is not None)
        if menus is not None:
            kinds = {p.kind for p in menus.pages}
            for kind, check in self.page_checks.items():
                check.setChecked(kind in kinds)
            self._fill_templates(menus.template)
            self.resume.setChecked(menus.resume)
            self.shuffle.setChecked(menus.shuffle)
            self.shuffle.setVisible(len(project.titles) > 1)  # only a series has episodes
            self.timeout.setValue(menus.timeout or 0)
            bg = menus.background
            key = ("motion" if bg.motion else "frame" if bg.frame else
                   "image" if bg.image else "color")  # fmt: skip
            self.bg_kind.setCurrentIndex(self.bg_kind.findData(key))
            self.motion_secs.setVisible(key == "motion")
            self.motion_secs.setValue(bg.motion or 20)
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
        tc = (bg.frame or "-").split(".")[0]
        text = {"frame": t("menu.bg.use_frame", tc=tc), "motion": t("menu.bg.use_frame", tc=tc),
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
        args = (self.project, self.infos, self.sources, self.project_dir, frame, display)

        def done(previews) -> None:
            if request != self.request:
                return
            self.previews = previews
            current = self.page_list.currentIndex()
            ids = [page.id for page, _r in previews]
            if self.wanted_page in ids:  # asked for from the disc map before the pages were up
                current = ids.index(self.wanted_page)
            self.wanted_page = None
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

    def select_page(self, page_id: str) -> None:
        """Show this page (e.g. clicked on the disc map); waits for the previews if needed."""
        ids = [page.id for page, _r in self.previews]
        if page_id in ids and not self.dirty:
            self.page_list.setCurrentIndex(ids.index(page_id))
        else:
            self.wanted_page = page_id

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
        menus = self.project.menus
        self.sim = Simulator([p for p, _r in self.previews], menus.first,
                             subtitles_on=bool(subs) and subs[0].default,
                             titles=len(self.project.titles), timeout=menus.timeout)  # fmt: skip

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
            self.canvas.set_page(page.buttons, compose(rendered, None), aspect, page.layers)
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

    def _layer(self, item: str | None) -> tuple[MenuPage, int] | None:
        """The project page and index of a canvas layer box ("layer-2")."""
        spec = self._spec()
        if spec is None or not item or not item.startswith(LAYER):
            return None
        n = int(item[len(LAYER) :])
        return (spec, n) if n < len(spec.layers) else None

    def _button_selected(self, bid: str | None) -> None:
        button = next((b for b in self.canvas.buttons if b.id == bid), None)
        found = self._layer(bid)
        layer = found[0].layers[found[1]] if found else None
        self.label_edit.setEnabled(
            button is not None or (layer is not None and layer.kind == "text")
        )
        self.label_edit.setText(button.label if button else layer.text or "" if layer else "")
        egg = button is not None and button.hidden
        self.reset.setText(t("menu.layer.remove") if layer else
                           t("menu.hidden.remove") if egg else t("menu.edit.reset"))  # fmt: skip
        self.add_hidden.setEnabled(button is not None and not egg)
        self.label_title.setText(t("menu.layer.label") if layer else t("menu.edit.label"))
        self.colour.setEnabled(layer is not None and layer.kind != "image")
        self._fill_nav(button)
        clash = overlapping(self.canvas.button_rects())
        self.edit_note.setText(t("menu.edit.overlap") if clash else t("menu.edit.hint"))

    def _fill_nav(self, button) -> None:
        """The arrow targets of the chosen button: "Otomatik" names the button the automatic
        rule would pick; a target set by hand is selected."""
        spec = self._spec()
        chosen = spec.edits.get(button.id) if spec is not None and button is not None else None
        others = [b for b in self.canvas.buttons if button is not None and b.id != button.id]
        auto = {}
        if button is not None:
            plain = [replace(b, nav={}, rect=self.canvas.rects.get(b.id, b.rect))
                     for b in self.canvas.buttons]  # fmt: skip
            auto_nav(plain)
            auto = next(b.nav for b in plain if b.id == button.id)
        labels = {b.id: b.label for b in self.canvas.buttons}
        for direction, combo in self.nav_combos.items():
            combo.blockSignals(True)
            combo.clear()
            target = auto.get(direction)
            combo.addItem(t("menu.edit.nav_auto", target=labels.get(target, t("menu.edit.stay"))),
                          None)  # fmt: skip
            for b in others:
                combo.addItem(b.label, b.id)
            manual = getattr(chosen, direction) if chosen is not None else None
            combo.setCurrentIndex(max(0, combo.findData(manual)) if manual else 0)
            combo.setEnabled(button is not None)
            combo.blockSignals(False)

    def _nav_changed(self, direction: str) -> None:
        bid = self.canvas.current
        if bid is not None:
            self._edit_button(bid, **{direction: self.nav_combos[direction].currentData()})

    def _button_moved(self, bid: str, rect: tuple) -> None:
        if bid.startswith(LAYER):
            self._edit_layer(bid, rect=rect)
        else:
            self._edit_button(bid, rect=rect)

    def _edit_layer(self, item: str, **change) -> None:
        found = self._layer(item)
        if found is None:
            return
        spec, n = found
        layers = list(spec.layers)
        layers[n] = MenuLayer(**{**layers[n].model_dump(), **change})
        spec.layers = layers
        self._changed()

    def _add_layer(self, kind: str) -> None:
        spec = self._spec()
        if spec is None or len(spec.layers) >= MAX_MENU_LAYERS:
            return
        if kind == "text":
            layer = MenuLayer(kind="text", rect=(0.30, 0.40, 0.40, 0.10), text=t("menu.layer.text"))
        elif kind == "shape":
            layer = MenuLayer(kind="shape", rect=(0.0, 0.78, 1.0, 0.14), color="#000000",
                              opacity=0.5)  # fmt: skip
        else:
            path, _ = QFileDialog.getOpenFileName(self, t("menu.layer.add_image"), "",
                                                  "PNG, JPEG (*.png *.jpg *.jpeg)")  # fmt: skip
            if not path:
                return
            layer = MenuLayer(kind="image", rect=(0.65, 0.08, 0.25, 0.18), image=path)
        spec.layers = [*spec.layers, layer]
        self.canvas.current = f"{LAYER}{len(spec.layers) - 1}"
        self._changed()

    def _layer_colour(self) -> None:
        found = self._layer(self.canvas.current)
        if found is None:
            return
        spec, n = found
        chosen = QColorDialog.getColor(QColor(spec.layers[n].color), self, t("menu.layer.colour"))
        if chosen.isValid():
            self._edit_layer(self.canvas.current, color=chosen.name())

    def _label_changed(self) -> None:
        if self._layer(self.canvas.current) is not None:
            text = self.label_edit.text().strip()
            if text:
                self._edit_layer(self.canvas.current, text=text)
            return
        bid, text = self.canvas.current, self.label_edit.text().strip()
        button = next((b for b in self.canvas.buttons if b.id == bid), None)
        if button is not None and text and text != button.label:
            self._edit_button(bid, label=text)

    def _add_hidden(self) -> None:
        spec, bid = self._spec(), self.canvas.current
        menus = self.project.menus if self.project is not None else None
        if spec is None or menus is None or not bid or bid.startswith(LAYER):
            return
        if len(menus.hidden_clips()) >= MAX_HIDDEN:
            self.status.setText(t("menu.hidden.full", n=MAX_HIDDEN))
            return
        path, _ = QFileDialog.getOpenFileName(self, t("menu.hidden.add"), str(self.project_dir),
                                              VIDEO_FILES)  # fmt: skip
        if not path:
            return
        direction = next((d for d in ("right", "down", "left", "up")
                          if d not in self._manual_nav(spec, bid)), "right")  # fmt: skip
        spec.hidden = [*spec.hidden, HiddenClip(file=path, after=bid, direction=direction)]
        self._changed()

    @staticmethod
    def _manual_nav(spec: MenuPage, bid: str) -> set[str]:
        e = spec.edits.get(bid)
        return {d for d in DIRECTIONS if e is not None and getattr(e, d)}

    def _remove_hidden(self, egg: str) -> None:
        number = int(egg.removeprefix("egg"))
        clip = self.project.menus.hidden_clips()[number - 1]
        for page in self.project.menus.pages:
            if any(h is clip for h in page.hidden):
                page.hidden = [h for h in page.hidden if h is not clip]
        self.canvas.current = None
        self._changed()

    def _reset_button(self) -> None:
        """Back to the generated button; for a layer or a hidden spot: remove it."""
        if (self.canvas.current or "").startswith("egg"):
            self._remove_hidden(self.canvas.current)
            return
        found = self._layer(self.canvas.current)
        if found is not None:
            spec, n = found
            spec.layers = [x for i, x in enumerate(spec.layers) if i != n]
            self.canvas.current = None
            self._changed()
            return
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
        elif key == Qt.Key.Key_W:  # "wait": let the first page's timeout run out
            self.sim.wait()
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

    def _set_menus(self, **change) -> None:
        for key, value in change.items():
            setattr(self.project.menus, key, value)
        self._changed()

    def _timeout_changed(self) -> None:
        value = self.timeout.value()
        if value and value < 5:
            value = 5
        if (value or None) != self.project.menus.timeout:
            self._set_menus(timeout=value or None)

    def _set_page(self, kind: str, on: bool) -> None:
        menus = self.project.menus
        pages = [p for p in menus.pages if p.kind != kind]
        if on:
            pages.append(MenuPage(id=kind, kind=kind))
        order = {"main": 0, "chapters": 1, "languages": 2}
        menus.pages = sorted(pages, key=lambda p: order.get(p.kind, 9))
        self._changed()

    def _open_tmdb(self) -> None:
        from dvd.gui.tmdb_dialog import TmdbDialog

        dialog = TmdbDialog(self.project, self.source, self)
        dialog.applied.connect(self._changed)
        dialog.exec()

    def _fill_templates(self, select: str | None = None) -> None:
        from dvd.gui.template_editor import template_text
        from dvd.menu.templates import list_templates

        self.template.blockSignals(True)
        self.template.clear()
        for name in list_templates():
            self.template.addItem(template_text(name), name)
        if select is not None:
            if self.template.findData(select) < 0:  # a template not on this PC
                self.template.addItem(select, select)
            self.template.setCurrentIndex(self.template.findData(select))
        self.template.blockSignals(False)

    def _edit_template(self) -> None:
        from dvd.gui.template_editor import TemplateEditor

        dialog = TemplateEditor(self.project.menus.template if self.project and
                                self.project.menus else "minimal", self)  # fmt: skip
        dialog.saved.connect(self._template_saved)
        dialog.exec()

    def _template_saved(self, name: str) -> None:
        self._fill_templates(name)
        if self.project is not None and self.project.menus is not None:
            self.project.menus.template = name
            self._changed()

    def _template_changed(self) -> None:
        self.project.menus.template = self.template.currentData()
        self._changed()

    def _bg_kind_changed(self) -> None:
        key, menus = self.bg_kind.currentData(), self.project.menus
        self.motion_secs.setVisible(key == "motion")
        if key == "frame":
            menus.background = MenuBackground(frame=edit.format_time(self.position()))
        elif key == "motion":
            menus.background = MenuBackground(frame=edit.format_time(self.position()),
                                              motion=self.motion_secs.value())  # fmt: skip
        elif key == "color":
            menus.background = MenuBackground(color=menus.background.color)
        else:
            self._pick_image()
            return
        self._changed()

    def _bg_action(self) -> None:
        key, menus = self.bg_kind.currentData(), self.project.menus
        if key in ("frame", "motion"):
            menus.background = MenuBackground(frame=edit.format_time(self.position()),
                                              motion=menus.background.motion)  # fmt: skip
            self._changed()
        elif key == "image":
            self._pick_image()
        else:
            colour = QColorDialog.getColor(QColor(menus.background.color), self)
            if colour.isValid():
                menus.background = MenuBackground(color=colour.name())
                self._changed()

    def _motion_changed(self) -> None:
        bg = self.project.menus.background
        if bg.motion and bg.motion != self.motion_secs.value():
            self.project.menus.background = bg.model_copy(
                update={"motion": self.motion_secs.value()}
            )
            self._changed()

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("menu.bg.pick_image"), str(self.project_dir),
                                              "Resim (*.png *.jpg *.jpeg *.bmp)")  # fmt: skip
        if path:
            self.project.menus.background = MenuBackground(image=Path(path).as_posix())
        self._changed()
