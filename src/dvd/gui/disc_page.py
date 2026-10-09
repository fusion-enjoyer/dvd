"""Disc page (pro mode): name, media and TV standard, intro clips, what happens at the end."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dvd.gui.i18n import t
from dvd.project.model import Intro, Project

VIDEO_FILES = "Video (*.mkv *.mp4 *.m4v *.mov *.avi *.mpg *.ts *.m2ts *.webm)"


def _label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


class DiscPage(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.project_dir = Path()
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 20)
        box.setSpacing(12)
        box.addWidget(_label(t("disc.title"), "pageTitle"))
        holder = QWidget()
        holder.setMaximumWidth(560)  # short fields read better than full-width ones
        form = QFormLayout(holder)
        form.setContentsMargins(0, 0, 0, 0)
        self.name = QLineEdit()
        self.name.setMaxLength(64)
        self.name.editingFinished.connect(self._name_changed)
        form.addRow(t("disc.name"), self.name)
        self.media = QComboBox()
        for key in ("dvd5", "dvd9"):
            self.media.addItem(t(f"disc.media.{key}"), key)
        self.media.currentIndexChanged.connect(lambda _i: self._field(
            self.project.disc, "media", self.media))  # fmt: skip
        form.addRow(t("disc.media"), self.media)
        self.standard = QComboBox()
        for key in ("pal", "ntsc"):
            self.standard.addItem(key.upper(), key)
        self.standard.currentIndexChanged.connect(lambda _i: self._field(
            self.project.disc, "standard", self.standard))  # fmt: skip
        form.addRow(t("disc.standard"), self.standard)
        self.at_end = QComboBox()
        for key in ("menu", "stop", "repeat"):
            self.at_end.addItem(t(f"disc.at_end.{key}"), key)
        self.at_end.currentIndexChanged.connect(lambda _i: self._field(
            self.project, "at_end", self.at_end))  # fmt: skip
        form.addRow(t("disc.at_end"), self.at_end)
        box.addWidget(holder)
        box.addSpacing(8)
        box.addWidget(_label(t("disc.intros"), "sectionLabel"))
        box.addWidget(_label(t("disc.intros_hint"), "muted", wrap=True))
        self.card = QWidget()
        self.card.setObjectName("card")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.card.setMaximumWidth(860)
        self.grid = QGridLayout(self.card)
        self.grid.setContentsMargins(16, 12, 16, 12)
        box.addWidget(self.card)
        add = QPushButton(t("disc.add_intro"))
        add.clicked.connect(self._add_intro)
        box.addWidget(add, alignment=Qt.AlignmentFlag.AlignLeft)
        box.addStretch()

    def show_project(self, project: Project, project_dir: Path) -> None:
        self.project, self.project_dir = project, project_dir
        widgets = (self.name, self.media, self.standard, self.at_end)
        for w in widgets:
            w.blockSignals(True)
        self.name.setText(project.disc.name)
        self.media.setCurrentIndex(self.media.findData(project.disc.media))
        self.standard.setCurrentIndex(self.standard.findData(project.disc.standard))
        self.at_end.setCurrentIndex(self.at_end.findData(project.at_end))
        for w in widgets:
            w.blockSignals(False)
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            w.hide()
            w.setParent(None)
            w.deleteLater()
        if not project.first_play:
            empty = _label(t("disc.no_intros"), "hint")
            self.grid.addWidget(empty, 0, 0)
            empty.show()
        for row, intro in enumerate(project.first_play):
            name = _label(f"{row + 1}.  {Path(intro.file).name}")
            remove = QPushButton(t("tracks.remove"))
            remove.clicked.connect(lambda _=False, i=row: self._remove(i))
            for col, w in enumerate((name, remove)):
                self.grid.addWidget(w, row, col)
                w.show()
        self.grid.setColumnStretch(0, 1)

    def _set(self, change) -> None:
        if self.project is None:
            return
        change()
        self.changed.emit()

    def _field(self, target, name: str, combo: QComboBox) -> None:
        self._set(lambda: setattr(target, name, combo.currentData()))

    def _name_changed(self) -> None:
        text = self.name.text().strip()
        if text and self.project is not None and text != self.project.disc.name:
            self._set(lambda: setattr(self.project.disc, "name", text))

    def _add_intro(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("disc.add_intro"), str(self.project_dir),
                                              VIDEO_FILES)  # fmt: skip
        if path:
            self.add_intro(Path(path))

    def add_intro(self, path: Path) -> None:
        try:
            rel = Path(os.path.relpath(path.resolve(), self.project_dir.resolve()))
            stored = rel.as_posix() if not str(rel).startswith("..") else path.as_posix()
        except ValueError:  # another drive
            stored = path.resolve().as_posix()
        self._set(lambda: self.project.first_play.append(Intro(file=stored)))

    def _remove(self, index: int) -> None:
        self._set(lambda: self.project.first_play.pop(index))
