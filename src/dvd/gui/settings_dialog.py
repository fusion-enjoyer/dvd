"""Program settings shared by every project (`dvd/settings.py`): for now the interface
language, which applies the next time the program starts."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QWidget

from dvd import settings
from dvd.gui.i18n import LANGUAGES, current_language, t


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings.title"))
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 16)
        self.language = QComboBox()
        for code in LANGUAGES:
            self.language.addItem(t(f"settings.language.{code}"), code)
        saved = settings.load().get("language") or current_language()
        self.language.setCurrentIndex(max(0, self.language.findData(saved)))
        form.addRow(t("settings.language"), self.language)
        note = QLabel(t("settings.restart"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)  # fmt: skip
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self) -> None:
        settings.save({"language": self.language.currentData()})
        self.accept()
