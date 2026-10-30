"""Program settings shared by every project (`dvd/settings.py`): the interface language
(applies the next time the program starts) and the theme (applies at once)."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QWidget

from dvd import settings
from dvd.gui.i18n import LANGUAGES, current_language, t
from dvd.gui.theme import THEMES, current_theme, set_theme


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
        self.theme = QComboBox()
        for name in THEMES:
            self.theme.addItem(t(f"settings.theme.{name}"), name)
        self.theme.setCurrentIndex(max(0, self.theme.findData(current_theme())))
        form.addRow(t("settings.theme"), self.theme)
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
        theme = self.theme.currentData()
        settings.save({"language": self.language.currentData(), "theme": theme})
        if theme != current_theme():
            set_theme(theme)
            window = self.parent()
            if window is not None and hasattr(window, "set_mode"):
                window.set_mode(window.mode)  # the stylesheet again, with the new tokens
                window.update()
        self.accept()
