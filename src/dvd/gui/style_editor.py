"""Subtitle style editor: change a style with a live preview, save it under a name."""

from __future__ import annotations

import re
from dataclasses import replace
from fractions import Fraction

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from dvd.gui.i18n import t
from dvd.gui.pages import style_text
from dvd.subs.render import SubStyle, render_cue
from dvd.subs.srt import Cue
from dvd.subs.styles import StyleError, list_styles, load_style, save_style

SAMPLE = Cue(0, 1, ("Örnek altyazı satırı", "İkinci satır: ğüşıöç ĞÜŞİÖÇ"))
FRAME = (720, 576, Fraction(16, 9))  # PAL 16:9, drawn at 1024x576
WEIGHTS = {400: "Normal", 600: "Yarı kalın", 700: "Kalın"}


def preview_image(style: SubStyle, width: int = 512) -> QImage:
    """The sample cue on a dark-to-light background, at display aspect."""
    fw, fh, aspect = FRAME
    canvas = QImage(fw, fh, QImage.Format.Format_ARGB32)
    p = QPainter(canvas)
    grad = QLinearGradient(0, 0, fw, fh)
    grad.setColorAt(0, QColor(20, 24, 30))
    grad.setColorAt(0.6, QColor(110, 120, 120))
    grad.setColorAt(1, QColor(225, 220, 205))  # light sky: the outline has to carry the text
    p.fillRect(canvas.rect(), grad)
    bitmap = render_cue(SAMPLE, fw, fh, aspect, style)
    rgba = bitmap.rgba.copy()
    sub = QImage(rgba.data, bitmap.width, bitmap.height, bitmap.width * 4,
                 QImage.Format.Format_RGBA8888)  # fmt: skip
    p.drawImage(bitmap.x, bitmap.y, sub)
    p.end()
    display_w = round(fh * aspect)
    return canvas.scaled(display_w, fh).scaledToWidth(
        width, Qt.TransformationMode.SmoothTransformation
    )


class StyleEditor(QDialog):
    saved = Signal(str)

    def __init__(self, start: str = "varsayilan", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("style.title"))
        self.style_ = load_style(start)
        box = QVBoxLayout(self)
        self.preview = QLabel()
        self.preview.setObjectName("videoWell")
        box.addWidget(self.preview)
        form = QFormLayout()
        self.base = QComboBox()
        for name in list_styles():
            self.base.addItem(style_text(name), name)
        self.base.setCurrentIndex(max(0, self.base.findData(start)))
        self.base.currentIndexChanged.connect(self._load_base)
        form.addRow(t("style.base"), self.base)
        self.font = QFontComboBox()
        self.font.currentFontChanged.connect(lambda f: self._set(family=f.family()))
        form.addRow(t("style.font"), self.font)
        self.weight = QComboBox()
        for w, text in WEIGHTS.items():
            self.weight.addItem(text, w)
        self.weight.currentIndexChanged.connect(
            lambda _i: self._set(weight=self.weight.currentData())
        )
        form.addRow(t("style.weight"), self.weight)
        self.size = self._spin(3.0, 9.0, 0.1, " %", lambda v: self._set(size=v / 100))
        form.addRow(t("style.size"), self.size)
        self.outline = self._spin(0.0, 1.2, 0.05, " %", lambda v: self._set(outline_width=v / 100))
        form.addRow(t("style.outline_width"), self.outline)
        self.bottom = self._spin(2.0, 20.0, 0.5, " %", lambda v: self._set(bottom=v / 100))
        form.addRow(t("style.bottom"), self.bottom)
        colours = QHBoxLayout()
        self.fill_button = QPushButton(t("style.fill"))
        self.fill_button.clicked.connect(lambda: self._pick("fill"))
        self.outline_button = QPushButton(t("style.outline"))
        self.outline_button.clicked.connect(lambda: self._pick("outline"))
        colours.addWidget(self.fill_button)
        colours.addWidget(self.outline_button)
        form.addRow(t("style.colours"), colours)
        box.addLayout(form)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("style.name_hint"))
        save = QPushButton(t("style.save"))
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(self.name, 1)
        row.addWidget(save)
        box.addLayout(row)
        self.message = QLabel("")
        self.message.setObjectName("muted")
        box.addWidget(self.message)
        self._show()

    def _spin(self, lo, hi, step, suffix, changed) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        spin.setSuffix(suffix)
        spin.valueChanged.connect(changed)
        return spin

    def _load_base(self) -> None:
        self.style_ = load_style(self.base.currentData())
        self._show()

    def _set(self, **change) -> None:
        self.style_ = replace(self.style_, **change)
        self._draw()

    def _pick(self, which: str) -> None:
        current = QColor(*getattr(self.style_, which))
        colour = QColorDialog.getColor(current, self, t(f"style.{which}"))
        if colour.isValid():
            self._set(**{which: (colour.red(), colour.green(), colour.blue())})

    def _show(self) -> None:
        """Put the style's values into the fields without triggering edits."""
        s = self.style_
        widgets = (self.font, self.weight, self.size, self.outline, self.bottom)
        for w in widgets:
            w.blockSignals(True)
        self.font.setCurrentFont(QFont(s.family))
        self.weight.setCurrentIndex(max(0, self.weight.findData(s.weight)))
        self.size.setValue(s.size * 100)
        self.outline.setValue(s.outline_width * 100)
        self.bottom.setValue(s.bottom * 100)
        for w in widgets:
            w.blockSignals(False)
        self._draw()

    def _draw(self) -> None:
        self.preview.setPixmap(QPixmap.fromImage(preview_image(self.style_)))
        for button, rgb in ((self.fill_button, self.style_.fill),
                            (self.outline_button, self.style_.outline)):  # fmt: skip
            text = "#{:02X}{:02X}{:02X}".format(*rgb)
            button.setText(f"{t('style.' + ('fill' if button is self.fill_button else 'outline'))}"
                           f"  {text}")  # fmt: skip

    def _save(self) -> None:
        name = self.name.text().strip()
        if name in _builtin():
            self.message.setText(t("style.builtin_name"))
            return
        if not re.fullmatch(r"[\w\- ]{1,40}", name):
            self.message.setText(t("style.bad_name"))
            return
        try:
            save_style(name, self.style_)
        except StyleError as exc:
            self.message.setText(str(exc))
            return
        self.saved.emit(name)
        self.accept()


def _builtin() -> set[str]:
    from dvd.subs.styles import TEMPLATES

    return set(TEMPLATES)
