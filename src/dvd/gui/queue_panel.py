"""The job queue on the output page: projects waiting to be built one after another, and
what the computer does when the last one is done (`dvd/jobs.py` holds the queue)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dvd.gui.i18n import t
from dvd.jobs import AFTER, Job


def _label(text: str, name: str | None = None) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    return w


class QueuePanel(QWidget):
    add_requested = Signal()
    start_requested = Signal()
    pause_toggled = Signal(bool)  # True: pause
    remove_requested = Signal(int)  # job index
    clear_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        box.addWidget(_label(t("queue.title"), "sectionLabel"))
        self.card = QWidget()
        self.card.setObjectName("card")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.card.setMaximumWidth(860)
        self.grid = QGridLayout(self.card)
        self.grid.setContentsMargins(16, 12, 16, 12)
        box.addWidget(self.card)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.add = QPushButton(t("queue.add"))
        self.add.clicked.connect(self.add_requested)
        self.start = QPushButton(t("queue.start"))
        self.start.clicked.connect(self.start_requested)
        self.pause = QPushButton(t("queue.pause"))
        self.pause.setCheckable(True)
        self.pause.setEnabled(False)
        self.pause.toggled.connect(self._pause)
        self.clear = QPushButton(t("queue.clear"))
        self.clear.setObjectName("link")
        self.clear.clicked.connect(self.clear_requested)
        for w in (self.add, self.start, self.pause, self.clear):
            row.addWidget(w)
        row.addStretch()
        box.addLayout(row)
        after = QHBoxLayout()
        after.addWidget(_label(t("queue.after"), "muted"))
        self.after_box = QComboBox()
        for key in AFTER:  # never remembered: shutting down must be chosen every time
            self.after_box.addItem(t(f"queue.after.{key}"), key)
        after.addWidget(self.after_box)
        after.addStretch()
        box.addLayout(after)
        self.current: str | None = None
        self.busy = False
        self.jobs: list[Job] = []
        self.show_jobs([])

    def after(self) -> str:
        return self.after_box.currentData()

    def running(self, on: bool) -> None:
        """While a build (one disc or the queue) runs: pause works, starting does not."""
        self.busy = on
        self.start.setEnabled(not on and any(j.state == "waiting" for j in self.jobs))
        self.pause.setEnabled(on)
        if not on:
            self.pause.blockSignals(True)
            self.pause.setChecked(False)
            self.pause.setText(t("queue.pause"))
            self.pause.blockSignals(False)
            self.current = None

    def _pause(self, on: bool) -> None:
        self.pause.setText(t("queue.resume" if on else "queue.pause"))
        self.pause_toggled.emit(on)

    def show_jobs(self, jobs: list[Job]) -> None:
        self.jobs = jobs
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            w.hide()
            w.setParent(None)
            w.deleteLater()
        if not jobs:
            empty = _label(t("queue.empty"), "hint")
            self.grid.addWidget(empty, 0, 0)
            empty.show()
        for row, job in enumerate(jobs):
            state = "running" if job.project == self.current else job.state
            name = _label(f"{row + 1}.  {Path(job.project).stem.removesuffix('.dvd')}")
            name.setToolTip(job.project)
            status = _label(t(f"queue.state.{state}"), {"failed": "error", "done": "ok"}
                            .get(state, "muted"))  # fmt: skip
            status.setToolTip(job.message)
            widgets = [name, status]
            if state == "waiting":
                remove = QPushButton(t("tracks.remove"))
                remove.clicked.connect(lambda _=False, i=row: self.remove_requested.emit(i))
                widgets.append(remove)
            for col, w in enumerate(widgets):
                self.grid.addWidget(w, row, col)
                w.show()
        self.grid.setColumnStretch(0, 1)
        self.start.setEnabled(not self.busy and any(j.state == "waiting" for j in jobs))
