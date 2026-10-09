"""Chapters page (pro mode): how chapters are set, the list with a frame for each, edits."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dvd.gui import tasks
from dvd.gui.i18n import t
from dvd.probe import SourceInfo
from dvd.project import edit
from dvd.project.model import MAX_CHAPTERS, ChapterEvery, Project, parse_timecode

THUMB = (128, 72)


def _label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def thumbnails(source: Path, info: SourceInfo, times: list[float]) -> dict[float, QImage]:
    """Small frames at chapter starts, in display aspect, tone mapped like the disc."""
    from dvd.menu.pictures import frame_images

    return frame_images(source, info, times, THUMB)


class ChaptersPage(QWidget):
    changed = Signal()

    def __init__(self, position: Callable[[], float]) -> None:
        """`position`: the preview's current source time, where "add" puts a chapter."""
        super().__init__()
        self.position = position
        self.project: Project | None = None
        self.info: SourceInfo | None = None
        self.source = Path()
        self.speedup = 1.0
        self.thumbs: dict[float, QImage] = {}
        self.suggesting = False
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self.box = QVBoxLayout(body)
        self.box.setContentsMargins(24, 20, 24, 20)
        self.box.setSpacing(14)
        self.box.addWidget(_label(t("chapters.title"), "pageTitle"))
        self.box.addWidget(_label(t("chapters.hint"), "muted", wrap=True))
        row = QHBoxLayout()
        self.mode = QComboBox()
        for key in ("from-source", "every", "manual", "none"):
            self.mode.addItem(t(f"chapters.mode.{key}"), key)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.every = QDoubleSpinBox()
        self.every.setRange(1, 30)
        self.every.setSingleStep(1)
        self.every.setDecimals(0)
        self.every.setValue(5)
        self.every.setSuffix(t("chapters.minutes"))
        self.every.editingFinished.connect(self._every_changed)
        self.suggest = QPushButton(t("chapters.suggest"))
        self.suggest.setToolTip(t("chapters.suggest_hint"))
        self.suggest.clicked.connect(self._suggest)
        self.add = QPushButton(t("chapters.add"))
        self.add.clicked.connect(self._add)
        for w in (self.mode, self.every, self.suggest, self.add):
            row.addWidget(w)
        row.addStretch()
        self.box.addLayout(row)
        self.status = _label("", "muted", wrap=True)
        self.status.hide()
        self.box.addWidget(self.status)
        self.card = QWidget()
        self.card.setObjectName("card")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.card.setMaximumWidth(860)
        self.grid = QGridLayout(self.card)
        self.grid.setContentsMargins(16, 12, 16, 12)
        self.grid.setHorizontalSpacing(16)
        self.box.addWidget(self.card)
        self.box.addStretch()

    # ------------------------------------------------------------------ show

    def show_project(self, project: Project, info: SourceInfo, source: Path,
                     speedup: float) -> None:  # fmt: skip
        self.project, self.info, self.source, self.speedup = project, info, source, speedup
        title = project.titles[0]
        chapters = title.chapters
        key = ("every" if isinstance(chapters, ChapterEvery) else
               "manual" if isinstance(chapters, list) else chapters)  # fmt: skip
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(self.mode.findData(key))
        self.mode.model().item(0).setEnabled(bool(info.chapters))
        self.mode.setItemText(0, t("chapters.mode.from-source", n=len(info.chapters)))
        self.mode.blockSignals(False)
        if isinstance(chapters, ChapterEvery):
            self.every.setValue(chapters.every)
        self.every.setVisible(key in ("every", "manual"))  # manual: the suggestion interval
        self.add.setVisible(key == "manual")
        self.suggest.setEnabled(not self.suggesting)
        self._fill(edit.chapter_times(title, info, speedup), editable=key == "manual")

    def _fill(self, times: list[float], editable: bool) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            w.hide()
            w.setParent(None)
            w.deleteLater()
        for row, at in enumerate(times):
            number = _label(f"{row + 1:02}", "mono")
            thumb = QLabel()
            thumb.setFixedSize(*THUMB)
            thumb.setObjectName("videoWell")
            if at in self.thumbs:
                thumb.setPixmap(QPixmap.fromImage(self.thumbs[at]))
            when = QLineEdit(edit.format_time(at))
            when.setObjectName("mono")
            when.setReadOnly(not editable or row == 0)
            when.setMaximumWidth(140)
            when.editingFinished.connect(lambda w=when, i=row: self._moved(i, w.text()))
            cells = [number, thumb, when]
            if editable and row > 0:
                remove = QPushButton(t("tracks.remove"))
                remove.clicked.connect(lambda _=False, i=row: self._remove(i))
                cells.append(remove)
            for col, w in enumerate(cells):
                self.grid.addWidget(w, row, col)
                w.show()
        self.grid.setColumnStretch(4, 1)
        missing = [at for at in times if at not in self.thumbs]
        if missing and self.info is not None and self.info.main_video is not None:
            tasks.run(lambda: thumbnails(self.source, self.info, missing), self._thumbs_ready,
                      lambda _msg: None)  # fmt: skip

    def _thumbs_ready(self, images: dict[float, QImage]) -> None:
        self.thumbs.update(images)
        if self.project is not None:
            self.show_project(self.project, self.info, self.source, self.speedup)

    # ----------------------------------------------------------------- edits

    def _times(self) -> list[float]:
        return edit.chapter_times(self.project.titles[0], self.info, self.speedup)

    def _status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _set(self, change: Callable[[], None]) -> None:
        try:
            change()
        except ValueError as exc:
            self._status(str(exc))
            return
        self._status("")
        self.changed.emit()

    def _mode_changed(self) -> None:
        title, key = self.project.titles[0], self.mode.currentData()
        current = self._times()
        if key == "every":
            self._set(lambda: setattr(title, "chapters", ChapterEvery(every=self.every.value())))
        elif key == "manual":  # start from what the title has now
            self._set(lambda: edit.set_manual_chapters(title, current))
        else:
            self._set(lambda: setattr(title, "chapters", key))

    def _every_changed(self) -> None:
        title = self.project.titles[0]
        if isinstance(title.chapters, ChapterEvery) and title.chapters.every != self.every.value():
            self._set(lambda: setattr(title, "chapters", ChapterEvery(every=self.every.value())))

    def _moved(self, index: int, text: str) -> None:
        times = self._times()
        try:
            at = parse_timecode(text)
        except ValueError as exc:
            self._status(str(exc))
            return
        if abs(at - times[index]) < 0.001:
            return
        times[index] = at
        self._set(lambda: edit.set_manual_chapters(self.project.titles[0], times))

    def _remove(self, index: int) -> None:
        times = self._times()
        del times[index]
        self._set(lambda: edit.set_manual_chapters(self.project.titles[0], times))

    def _add(self) -> None:
        times = self._times()
        if len(times) >= MAX_CHAPTERS:
            self._status(t("chapters.full", n=MAX_CHAPTERS))
            return
        at = self.position()
        if at in times or at <= 0:
            at = times[-1] + 60
        self._set(lambda: edit.set_manual_chapters(self.project.titles[0], [*times, at]))

    def _suggest(self) -> None:
        from dvd.video.scenes import suggest_chapters

        info, every = self.info, self.every.value() * self.speedup
        self.suggesting = True
        self.suggest.setEnabled(False)
        self._status(t("chapters.suggesting", pct=0))

        def done(times: list[float]) -> None:
            self.suggesting = False
            title = self.project.titles[0]
            self._set(lambda: edit.set_manual_chapters(title, times))
            self._status(t("chapters.suggested", n=len(times)))

        def failed(message: str) -> None:
            self.suggesting = False
            self.suggest.setEnabled(True)
            self._status(message)

        tasks.run(
            lambda report: suggest_chapters(self.source, info.main_video, info.duration or 0,
                                            every, progress=lambda f: report("", f)),
            done, failed,
            lambda _stage, f: self._status(t("chapters.suggesting", pct=round(f * 100))),
        )  # fmt: skip
