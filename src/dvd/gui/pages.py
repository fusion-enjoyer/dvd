"""Track selection and disc build pages."""

from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dvd.gui.i18n import t
from dvd.probe import SourceInfo
from dvd.project import edit
from dvd.project.model import AC3_BITRATES, Project

LANGS = ["tr", "en", "de", "fr", "es", "it", "ru", "ja", "ko", "zh", "ar", "nl", "sv", "pl"]


def _label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def _track_text(language: str | None, what: str, title: str | None) -> str:
    text = f"{language or '?'}  ·  {what}"
    return f'{text}  "{title}"' if title else text


def _lang_combo(current: str) -> QComboBox:
    combo = QComboBox()
    for code in dict.fromkeys([current, *LANGS]):
        combo.addItem(t(f"lang.{code}") if t(f"lang.{code}") != f"lang.{code}" else code, code)
    combo.setCurrentIndex(0)
    combo.setMinimumWidth(110)
    return combo


class TracksPage(QWidget):
    """Audio and subtitle choices. `show` is "both" (simple mode), "audio" or "subs"."""

    changed = Signal()
    failed = Signal(str)

    def __init__(self, show: str) -> None:
        super().__init__()
        self.show_kind = show
        self.mode = "basit"
        self.project: Project | None = None
        self.info: SourceInfo | None = None
        self.project_dir = Path()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.body = QWidget()
        scroll.setWidget(self.body)
        self.box = QVBoxLayout(self.body)
        self.box.setContentsMargins(24, 20, 24, 20)
        self.box.setSpacing(14)

    def show_project(self, project: Project, info: SourceInfo, project_dir: Path, mode: str):
        self.project, self.info, self.project_dir, self.mode = project, info, project_dir, mode
        self._rebuild()

    # ---------------------------------------------------------------- building rows

    def _clear(self) -> None:
        while self.box.count():
            item = self.box.takeAt(0)
            if w := item.widget():
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _rebuild(self) -> None:
        self._clear()
        if self.project is None:
            return
        if self.show_kind in ("both", "audio"):
            self._audio_section()
        if self.show_kind in ("both", "subs"):
            self._subtitle_section()
        self.box.addStretch()

    def _card(self, title: str, hint: str) -> QGridLayout:
        self.box.addWidget(_label(title, "pageTitle"))
        if hint:
            self.box.addWidget(_label(hint, "muted", wrap=True))
        card = QWidget()
        card.setObjectName("card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        card.setMaximumWidth(860)
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.box.addWidget(card)
        return grid

    def _audio_section(self) -> None:
        title, info = self.project.titles[0], self.info
        grid = self._card(t("tracks.audio"), t("tracks.audio_hint"))
        chosen = {a.track: a for a in title.audio}
        group = QButtonGroup(grid.parentWidget())
        for row, src in enumerate(info.audio):
            a = chosen.get(src.index)
            check = QCheckBox(_track_text(src.language, f"{src.profile or src.codec} "
                                          f"{src.channels}ch", src.title))  # fmt: skip
            check.setChecked(a is not None)
            check.toggled.connect(lambda on, i=src.index: self._edit(
                lambda: edit.set_audio_included(title, info, i, on)))  # fmt: skip
            grid.addWidget(check, row, 0)
            if a is None:
                continue
            default = QRadioButton(t("tracks.default"))
            default.setChecked(a.default)
            group.addButton(default)
            default.toggled.connect(lambda on, i=src.index: on and self._edit(
                lambda: edit.set_default_audio(title, i)))  # fmt: skip
            grid.addWidget(default, row, 1)
            lang = _lang_combo(a.lang)
            lang.currentIndexChanged.connect(lambda _n, c=lang, a=a: self._edit(
                lambda: setattr(a, "lang", c.currentData())))  # fmt: skip
            grid.addWidget(lang, row, 2)
            if self.mode == "pro":
                channels = QComboBox()
                channels.addItems(["5.1", "2.0"])
                channels.setCurrentText(a.channels)
                channels.currentTextChanged.connect(lambda v, a=a: self._edit(
                    lambda: setattr(a, "channels", v)))  # fmt: skip
                bitrate = QComboBox()
                for b in AC3_BITRATES:
                    bitrate.addItem(f"{b}k", b)
                bitrate.setCurrentIndex(bitrate.findData(a.bitrate))
                bitrate.currentIndexChanged.connect(lambda _n, c=bitrate, a=a: self._edit(
                    lambda: setattr(a, "bitrate", c.currentData())))  # fmt: skip
                grid.addWidget(channels, row, 3)
                grid.addWidget(bitrate, row, 4)
            else:
                grid.addWidget(_label(f"AC-3 {a.channels}", "hint"), row, 3)
        grid.setColumnStretch(0, 1)

    def _subtitle_section(self) -> None:
        title, info = self.project.titles[0], self.info
        grid = self._card(t("tracks.subs"), t("tracks.subs_hint"))
        group = QButtonGroup(grid.parentWidget())
        off = QRadioButton(t("tracks.subs_off"))
        off.setChecked(not any(s.default for s in title.subtitles))
        off.toggled.connect(lambda on: on and self._edit(
            lambda: edit.set_default_subtitle(title, None)))  # fmt: skip
        group.addButton(off)
        grid.addWidget(off, 0, 1)
        row = 1
        by_track = {s.track: s for s in title.subtitles if s.track is not None}
        for src in info.subtitles:
            s = by_track.get(src.index)
            check = QCheckBox(_track_text(src.language, src.codec, src.title))
            check.setChecked(s is not None)
            if src.kind != "text":
                check.setEnabled(False)
                check.setToolTip(t("tracks.bitmap_later"))
                grid.addWidget(check, row, 0)
                grid.addWidget(_label(t("tracks.bitmap_later"), "hint"), row, 1, 1, 2)
                row += 1
                continue
            check.toggled.connect(lambda on, i=src.index, lang=src.language: self._edit(
                lambda: edit.set_subtitle_included(title, i, lang, on)))  # fmt: skip
            grid.addWidget(check, row, 0)
            if s is not None:
                self._sub_controls(grid, row, s, s.track, group)
            row += 1
        for s in [s for s in title.subtitles if s.file is not None]:
            grid.addWidget(_label(Path(s.file).name), row, 0)
            self._sub_controls(grid, row, s, s.file, group)
            remove = QPushButton(t("tracks.remove"))
            remove.clicked.connect(lambda _=False, f=s.file: self._edit(
                lambda: edit.remove_subtitle_file(title, f)))  # fmt: skip
            grid.addWidget(remove, row, 3)
            row += 1
        add = QPushButton(t("tracks.add_srt"))
        add.clicked.connect(self._add_srt)
        grid.addWidget(add, row, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(0, 1)

    def _sub_controls(self, grid: QGridLayout, row: int, s, key, group: QButtonGroup) -> None:
        title = self.project.titles[0]
        default = QRadioButton(t("tracks.default"))
        default.setChecked(s.default)
        group.addButton(default)
        default.toggled.connect(lambda on: on and self._edit(
            lambda: edit.set_default_subtitle(title, key)))  # fmt: skip
        grid.addWidget(default, row, 1)
        lang = _lang_combo(s.lang)
        lang.currentIndexChanged.connect(lambda _n: self._edit(
            lambda: setattr(s, "lang", lang.currentData())))  # fmt: skip
        grid.addWidget(lang, row, 2)

    def _add_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("tracks.add_srt"), str(self.project_dir),
                                              "SRT (*.srt)")  # fmt: skip
        if path:
            self._edit(lambda: edit.add_subtitle_file(self.project.titles[0], Path(path),
                                                      self.project_dir))  # fmt: skip

    def _edit(self, change) -> None:
        try:
            change()
        except ValueError as exc:
            self.failed.emit(str(exc))
        self.changed.emit()
        self._rebuild()


STAGES = [
    (r"title \d+ audio", "build.stage.audio"),
    (r"title \d+ video", "build.stage.video"),
    (r"title \d+ check", "build.stage.check"),
    (r"title \d+ mux", "build.stage.mux"),
    (r"title \d+ subtitles", "build.stage.subs"),
    (r"authoring", "build.stage.author"),
    (r"iso", "build.stage.iso"),
    (r"done", "build.stage.done"),
]


WARNINGS = [
    (r"automatic black-bar crop", "warning.crop", None),
    (r"average video bitrate ([\d.]+) Mbps is low; consider DVD-9", "warning.low_dvd5", 1),
    (r"average video bitrate ([\d.]+) Mbps is low; use fewer", "warning.low_dvd9", 1),
]


def translate_warning(text: str) -> str:
    """Engine warnings are English for the CLI; show the known ones in Turkish."""
    for pattern, key, group in WARNINGS:
        m = re.search(pattern, text)
        if m:
            return t(key, value=m.group(group)) if group else t(key)
    return text


def stage_text(stage: str) -> str:
    for pattern, key in STAGES:
        if re.match(pattern, stage):
            return t(key)
    return stage


class BuildPage(QWidget):
    start_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 20)
        box.setSpacing(14)
        box.addWidget(_label(t("build.title"), "pageTitle"))
        self.summary = _label("", "muted", wrap=True)
        box.addWidget(self.summary)
        self.start = QPushButton(t("build.start"))
        self.start.setObjectName("primary")
        self.start.clicked.connect(self.start_requested)
        box.addWidget(self.start, alignment=Qt.AlignmentFlag.AlignLeft)
        self.stage = _label("", None)
        self.stage.setStyleSheet("font-weight: 600;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setMaximumWidth(860)
        self.done_list = _label("", "muted", wrap=True)
        self.result = _label("", None, wrap=True)
        self.warnings = _label("", "warn", wrap=True)
        self.open_folder = QPushButton(t("build.open_folder"))
        self.open_folder.clicked.connect(self._open_folder)
        for w in (self.stage, self.bar, self.done_list, self.result, self.warnings):
            box.addWidget(w)
        box.addWidget(self.open_folder, alignment=Qt.AlignmentFlag.AlignLeft)
        box.addStretch()
        self.folder: Path | None = None
        self.reset()

    def reset(self) -> None:
        self.stage.setText("")
        self.bar.hide()
        self.done_list.setText("")
        self.result.setText("")
        self.warnings.setText("")
        self.open_folder.hide()
        self.finished_stages: list[str] = []

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def running(self) -> None:
        self.reset()
        self.start.setEnabled(False)
        self.bar.show()

    def progress(self, stage: str, fraction: float) -> None:
        text = stage_text(stage)
        if self.stage.text() and self.stage.text() != text:
            self.finished_stages.append(self.stage.text())
            self.done_list.setText("\n".join(f"✓  {s}" for s in self.finished_stages))
        self.stage.setText(text)
        self.bar.setValue(round(fraction * 1000))

    def finished(self, folder: Path, lines: list[str], warnings: list[str]) -> None:
        self.start.setEnabled(True)
        self.bar.hide()
        self.stage.setText(t("build.stage.done"))
        self.folder = folder
        self.result.setObjectName("ok")
        self.result.setText("\n".join(lines))
        self.result.style().polish(self.result)
        self.warnings.setText("\n".join(translate_warning(w) for w in warnings))
        self.open_folder.show()

    def failed(self, message: str) -> None:
        self.start.setEnabled(True)
        self.bar.hide()
        self.result.setObjectName("error")
        self.result.setText(f"{t('build.failed')}\n{message}")
        self.result.style().polish(self.result)

    def _open_folder(self) -> None:
        if self.folder and hasattr(os, "startfile"):
            os.startfile(self.folder)  # noqa: S606 (opens Explorer on the user's own output)
