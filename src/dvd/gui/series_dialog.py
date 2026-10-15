"""Season folder → a set of disc projects: the plan, the series name, TMDB names and pictures."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from dvd import settings
from dvd.gui import tasks
from dvd.gui.i18n import t
from dvd.meta.tmdb import Client, TmdbError
from dvd.project import save
from dvd.project.model import PROJECT_SUFFIX
from dvd.project.season import Season, disc_projects, lookup, plan_season, series_name
from dvd.series import QUALITY, DiscSet


class SeriesDialog(QDialog):
    created = Signal(list)  # the project files written, disc 1 first

    def __init__(self, season: Season, parent=None,
                 client: Callable[[str], Client] = Client) -> None:  # fmt: skip
        super().__init__(parent)
        self.setWindowTitle(t("series.title"))
        self.resize(720, 560)
        self.season, self.make_client = season, client
        self.plan: DiscSet | None = None
        box = QVBoxLayout(self)
        first, last = season.episodes[0].code, season.episodes[-1].code
        found = QLabel(t("series.found", count=len(season.episodes), first=first, last=last))
        found.setObjectName("pageTitle")
        box.addWidget(found)
        form = QFormLayout()
        self.default_name = series_name(season, None)
        self.name = QLineEdit(self.default_name)
        self.name.setMaxLength(64)
        form.addRow(t("series.name"), self.name)
        self.media = QComboBox()
        for key in ("dvd9", "dvd5"):
            self.media.addItem(t(f"disc.media.{key}"), key)
        self.quality = QComboBox()
        for key in QUALITY:
            self.quality.addItem(t(f"series.quality.{key}"), key)
        self.quality.setCurrentIndex(self.quality.findData("iyi"))
        form.addRow(t("disc.media"), self.media)
        form.addRow(t("series.quality"), self.quality)
        self.tmdb = QCheckBox(t("series.tmdb"))
        self.tmdb.setChecked(bool(settings.tmdb_key()))
        self.key = QLineEdit(settings.tmdb_key())
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(t("tmdb.key_hint"))
        self.key.textChanged.connect(lambda text: self.tmdb.setChecked(bool(text.strip())))
        form.addRow(t("tmdb.key"), self.key)
        form.addRow("", self.tmdb)
        box.addLayout(form)
        self.discs = QListWidget()
        box.addWidget(self.discs, 1)
        self.note = QLabel("")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        bottom = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("muted")
        bottom.addWidget(self.status, 1)
        self.create_button = QPushButton(t("series.create"))
        self.create_button.setObjectName("primary")
        self.create_button.clicked.connect(self.create)
        bottom.addWidget(self.create_button)
        box.addLayout(bottom)
        credit = QLabel(t("tmdb.credit"))  # required by the TMDB API terms
        credit.setObjectName("hint")
        credit.setWordWrap(True)
        box.addWidget(credit)
        self.media.currentIndexChanged.connect(self.replan)
        self.quality.currentIndexChanged.connect(self.replan)
        self.name.textChanged.connect(self._note)
        self.replan()

    def replan(self) -> None:
        self.plan = plan_season(self.season, self.media.currentData(), self.quality.currentData())
        target = QUALITY[self.quality.currentData()]
        self.discs.clear()
        for n, (disc, kbps) in enumerate(zip(self.plan.discs, self.plan.video_kbps,
                                             strict=True), start=1):  # fmt: skip
            codes = f"{disc[0].code} – {disc[-1].code}" if len(disc) > 1 else disc[0].code
            line = t("series.disc", n=n, count=self.plan.count, codes=codes, episodes=len(disc),
                     minutes=round(sum(e.duration for e in disc) / 60),
                     mbps=f"{kbps / 1000:.1f}".replace(".", ","))  # fmt: skip
            if kbps < target:
                line += f" · {t('series.below')}"
            self.discs.addItem(line)
        self._note()

    def _files(self, name: str) -> list[Path]:
        count = self.plan.count if self.plan else 1
        labels = [f"{name} - Disk {n}" for n in range(1, count + 1)] if count > 1 else [name]
        return [self.season.folder / f"{label}{PROJECT_SUFFIX}" for label in labels]

    def _note(self) -> None:
        existing = [f for f in self._files(self.name.text().strip()) if f.exists()]
        self.note.setText(t("series.exists", count=len(existing)) if existing else "")

    def create(self) -> None:
        typed = self.name.text().strip()
        name = "" if typed in ("", self.default_name) else typed  # TMDB may name it
        key = self.key.text().strip()
        if key and key != settings.tmdb_key():
            settings.save({"tmdb_key": key})
        client = self.make_client(key) if self.tmdb.isChecked() and key else None
        season, plan = self.season, self.plan
        self.create_button.setEnabled(False)
        self.status.setText(t("series.creating"))

        def work() -> tuple[list[Path], str]:
            meta, warning = None, ""
            if client is not None:
                try:
                    meta = lookup(season, client)
                except TmdbError as exc:
                    warning = t("series.tmdb_failed", error=exc)
                else:
                    warning = "" if meta else t("series.tmdb_unknown")
            written = []
            for path, project in disc_projects(season, plan, name, meta):
                save(project, path)
                written.append(path)
            return written, warning

        tasks.run(work, self._created, self._failed)

    def _created(self, result: tuple[list[Path], str]) -> None:
        written, warning = result
        self.created.emit(written)
        if not warning:
            self.accept()
            return
        # Keep the dialog up so the TMDB problem is read; the discs are written already.
        self.status.setText(warning)
        self.create_button.setText(t("series.close"))
        self.create_button.clicked.disconnect()
        self.create_button.clicked.connect(self.accept)
        self.create_button.setEnabled(True)

    def _failed(self, message: str) -> None:
        self.create_button.setEnabled(True)
        self.status.setText(message)
