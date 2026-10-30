"""Program settings shared by every project (`dvd/settings.py`): the interface language
(applies the next time the program starts), the theme (applies at once), the work folder,
the processor threads a build may use, and a folder of tools to use instead of the bundled
ones."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

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
        saved_all = settings.load()
        self.work = self._folder_row(form, t("settings.work"), saved_all.get("work_folder"),
                                     t("settings.work_hint"))  # fmt: skip
        self.threads = QSpinBox()
        self.threads.setRange(0, 256)
        self.threads.setSpecialValueText(t("settings.threads_all"))
        self.threads.setValue(settings.threads())
        self.threads.setToolTip(t("settings.threads_hint"))
        form.addRow(t("settings.threads"), self.threads)
        self.tools = self._folder_row(form, t("settings.tools"), saved_all.get("tools"),
                                      t("settings.tools_hint"))  # fmt: skip
        note = QLabel(t("settings.restart"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)  # fmt: skip
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _folder_row(self, form: QFormLayout, label: str, value, hint: str) -> QLineEdit:
        edit = QLineEdit(str(value or ""))
        edit.setPlaceholderText(t("settings.default"))
        edit.setToolTip(hint)
        pick = QPushButton(t("settings.choose"))
        pick.clicked.connect(lambda: self._choose(edit, label))
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(pick)
        form.addRow(label, row)
        return edit

    def _choose(self, edit: QLineEdit, label: str) -> None:
        folder = QFileDialog.getExistingDirectory(self, label, edit.text())
        if folder:
            edit.setText(folder)

    def save(self) -> None:
        theme = self.theme.currentData()
        settings.save({"language": self.language.currentData(), "theme": theme,
                       "work_folder": self.work.text().strip() or None,
                       "threads": self.threads.value(),
                       "tools": self.tools.text().strip() or None})  # fmt: skip
        if theme != current_theme():
            set_theme(theme)
            window = self.parent()
            if window is not None and hasattr(window, "set_mode"):
                window.set_mode(window.mode)  # the stylesheet again, with the new tokens
                window.update()
        self.accept()
