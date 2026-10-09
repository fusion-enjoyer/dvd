"""Find the film on TMDB and take a backdrop and a logo for the menus."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from dvd import settings
from dvd.gui import tasks
from dvd.gui.i18n import t
from dvd.meta.tmdb import Client, Film, guess_title
from dvd.project.model import MenuBackground, Project

THUMB = QSize(200, 113)


class TmdbDialog(QDialog):
    applied = Signal()

    def __init__(self, project: Project, source: Path, parent=None,
                 client: Callable[[str], Client] = Client) -> None:  # fmt: skip
        super().__init__(parent)
        self.setWindowTitle(t("tmdb.title"))
        self.resize(900, 680)
        self.project, self.make_client = project, client
        self.film: Film | None = None
        box = QVBoxLayout(self)
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel(t("tmdb.key")))
        self.key = QLineEdit(settings.tmdb_key())
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(t("tmdb.key_hint"))
        key_row.addWidget(self.key, 1)
        box.addLayout(key_row)
        search_row = QHBoxLayout()
        name, year = guess_title(source)
        self.query = QLineEdit(name)
        self.year = QLineEdit(str(year) if year else "")
        self.year.setPlaceholderText(t("tmdb.year"))
        self.year.setMaximumWidth(80)
        find = QPushButton(t("tmdb.search"))
        find.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.year)
        search_row.addWidget(find)
        box.addLayout(search_row)
        self.results = QListWidget()
        self.results.setMaximumHeight(130)
        self.results.currentRowChanged.connect(self._picked)
        box.addWidget(self.results)
        self.overview = QLabel("")
        self.overview.setWordWrap(True)
        self.overview.setObjectName("muted")
        box.addWidget(self.overview)
        box.addWidget(QLabel(t("tmdb.backdrops")))
        self.backdrops = self._strip()
        box.addWidget(self.backdrops)
        box.addWidget(QLabel(t("tmdb.logos")))
        self.logos = self._strip()
        box.addWidget(self.logos)
        bottom = QHBoxLayout()
        self.rename = QCheckBox(t("tmdb.rename"))
        self.rename.setChecked(True)
        bottom.addWidget(self.rename)
        bottom.addStretch()
        self.apply_button = QPushButton(t("tmdb.apply"))
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply)
        bottom.addWidget(self.apply_button)
        box.addLayout(bottom)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        box.addWidget(self.status)
        credit = QLabel(t("tmdb.credit"))  # required by the TMDB API terms
        credit.setObjectName("hint")
        box.addWidget(credit)
        self.matches = []

    def _strip(self) -> QListWidget:
        strip = QListWidget()
        strip.setViewMode(QListWidget.ViewMode.IconMode)
        strip.setIconSize(THUMB)
        strip.setFlow(QListWidget.Flow.LeftToRight)
        strip.setWrapping(False)
        strip.setFixedHeight(THUMB.height() + 30)
        return strip

    def _client(self) -> Client:
        key = self.key.text().strip()
        if key and key != settings.tmdb_key():
            settings.save({"tmdb_key": key})
        return self.make_client(key)

    # ------------------------------------------------------------------ steps

    def search(self) -> None:
        try:
            client = self._client()
        except Exception as exc:  # no key yet
            self.status.setText(str(exc))
            return
        year = int(self.year.text()) if self.year.text().strip().isdigit() else None
        self.status.setText(t("tmdb.searching"))
        tasks.run(lambda: client.search(self.query.text().strip(), year), self._found,
                  self.status.setText)  # fmt: skip

    def _found(self, matches) -> None:
        self.matches = matches
        self.results.clear()
        for m in matches:
            year = f" ({m.year})" if m.year else ""
            extra = f"  ·  {m.original_title}" if m.original_title != m.title else ""
            self.results.addItem(f"{m.title}{year}{extra}")
        self.status.setText(t("tmdb.found", n=len(matches)) if matches else t("tmdb.none"))
        if matches:
            self.results.setCurrentRow(0)

    def _picked(self, row: int) -> None:
        if not 0 <= row < len(self.matches):
            return
        client, film_id = self._client(), self.matches[row].id
        self.status.setText(t("tmdb.loading"))

        def load():
            film = client.film(film_id)
            thumbs = {p: client.image(film.id, p, "w300")
                      for p in film.backdrops[:8] + film.logos[:6]}  # fmt: skip
            return film, thumbs

        tasks.run(load, self._loaded, self.status.setText)

    def _loaded(self, result) -> None:
        film, thumbs = result
        self.film = film
        year = f" ({film.year})" if film.year else ""
        self.overview.setText(f"{film.title}{year}\n{film.overview}")
        for strip, paths in ((self.backdrops, film.backdrops[:8]), (self.logos, film.logos[:6])):
            strip.clear()
            for path in paths:
                item = QListWidgetItem(QIcon(QPixmap(str(thumbs[path]))), "")
                item.setData(Qt.ItemDataRole.UserRole, path)
                strip.addItem(item)
            if strip.count():
                strip.setCurrentRow(0)
        self.apply_button.setEnabled(True)
        self.status.setText("")

    def apply(self) -> None:
        film, client = self.film, self._client()
        backdrop = self.backdrops.currentItem()
        logo = self.logos.currentItem()
        chosen = (backdrop.data(Qt.ItemDataRole.UserRole) if backdrop else None,
                  logo.data(Qt.ItemDataRole.UserRole) if logo else None)  # fmt: skip
        self.status.setText(t("tmdb.downloading"))

        def fetch():
            bg = client.image(film.id, chosen[0], "w1280") if chosen[0] else None
            lg = client.image(film.id, chosen[1], "w500") if chosen[1] else None
            return bg, lg

        def done(files) -> None:
            bg, lg = files
            menus = self.project.menus
            if bg is not None:
                menus.background = MenuBackground(image=bg.as_posix())
            menus.logo = lg.as_posix() if lg is not None else None
            menus.tmdb_id = film.id
            if self.rename.isChecked() and film.title:
                self.project.disc.name = film.title[:64]
            self.applied.emit()
            self.accept()

        tasks.run(fetch, done, self.status.setText)
