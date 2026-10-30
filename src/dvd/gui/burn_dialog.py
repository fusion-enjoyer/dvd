"""Writing the built image to a disc from the output page, and checking the disc after."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from dvd.gui import tasks
from dvd.gui.i18n import t
from dvd.output import burn


class BurnDialog(QDialog):
    def __init__(self, iso: Path, video_ts: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.iso, self.video_ts = iso, video_ts
        self.setWindowTitle(t("burn.title"))
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 16)
        form.addRow(t("burn.image"), QLabel(iso.name))
        self.drive = QComboBox()
        self.found = burn.drives()
        dual = iso.with_suffix(".dvd").is_file()
        for d in self.found:
            note = "" if d.dual_layer or not dual else t("burn.no_dl")
            self.drive.addItem(f"{d.path}  {d.name}{note}", d.path)
        if not self.found:
            self.drive.addItem(t("burn.no_drive"), None)
            self.drive.setEnabled(False)
        form.addRow(t("burn.drive"), self.drive)
        self.speed = QComboBox()
        for s in burn.SPEEDS:
            self.speed.addItem(t("burn.speed_auto") if s == "auto" else f"{s}x", s)
        self.speed.setCurrentIndex(self.speed.findData("4"))  # slower burns read back better
        form.addRow(t("burn.speed"), self.speed)
        self.verify = QCheckBox(t("burn.verify"))
        self.verify.setChecked(True)
        form.addRow(self.verify)
        self.tool = burn.imgburn()
        note = QLabel(t("burn.with_imgburn") if self.tool else t("burn.with_windows"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        form.addRow(note)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        form.addRow(self.status)
        row = QHBoxLayout()
        row.addStretch()
        self.check = QPushButton(t("burn.check"))
        self.check.clicked.connect(self._check)
        self.write = QPushButton(t("burn.write"))
        self.write.setObjectName("primary")
        self.write.clicked.connect(self._write)
        close = QPushButton(t("series.close"))
        close.clicked.connect(self.reject)
        for b in (self.check, self.write, close):
            row.addWidget(b)
        form.addRow(row)
        for b in (self.check, self.write):
            b.setEnabled(bool(self.found))

    def _busy(self, text: str) -> None:
        self.status.setText(text)
        self.write.setEnabled(False)
        self.check.setEnabled(False)

    def _idle(self, text: str) -> None:
        self.status.setText(text)
        self.write.setEnabled(bool(self.found))
        self.check.setEnabled(bool(self.found))

    def _write(self) -> None:
        drive, speed, verify = self.drive.currentData(), self.speed.currentData(), \
            self.verify.isChecked()  # fmt: skip
        self._busy(t("burn.writing"))
        tasks.run(lambda: burn.burn(self.iso, drive, speed, verify),
                  lambda used: self._idle(t("burn.done_imgburn") if used == "imgburn"
                                          else t("burn.done_windows")),
                  lambda msg: self._idle(t("burn.failed", error=msg)))  # fmt: skip

    def _check(self) -> None:
        drive = Path(self.drive.currentData())
        self._busy(t("burn.checking"))
        tasks.run(lambda: burn.verify_disc(drive, self.video_ts),
                  lambda problems: self._idle(t("burn.matches") if not problems else
                                              t("burn.differs", n=len(problems),
                                                first=problems[0])),
                  lambda msg: self._idle(t("burn.failed", error=msg)))  # fmt: skip
