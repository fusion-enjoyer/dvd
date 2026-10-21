"""Menu template editor: change a template's layout and colours with a live preview, save it
as your own, export it to a file or import one."""

from __future__ import annotations

from dataclasses import fields, replace
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dvd.gui.i18n import t
from dvd.menu.layout import Button, Page, main_rects
from dvd.menu.render import render_page
from dvd.menu.templates import (
    TEMPLATES,
    Template,
    TemplateError,
    choices,
    export_template,
    import_template,
    list_templates,
    load_template,
    save_template,
)
from dvd.project.model import MenuAction

FRAME = (720, 576, Fraction(16, 9))
SAMPLE_LABELS = ("Filmi oynat", "Bölümler", "Dil ayarları")
COLOURS = ("text", "title", "muted", "highlight", "select")
FILE_FILTER = "Menü şablonu (*.yaml)"


def template_text(name: str) -> str:
    return t(f"menu.template.{name}") if name in TEMPLATES else name


def sample_page(tpl: Template) -> Page:
    rects = main_rects(len(SAMPLE_LABELS), tpl)
    pairs = zip(SAMPLE_LABELS, rects, strict=True)
    buttons = [Button(f"b{i}", label, MenuAction(do="play"), rect)
               for i, (label, rect) in enumerate(pairs)]  # fmt: skip
    return Page("main", "main", "Örnek Film", buttons, subtitle="Disk 1 / 2")


def preview_image(tpl: Template, width: int = 512) -> QImage:
    """A sample main page on a dark-to-light picture, the first button lit."""
    backdrop = QImage(1024, 576, QImage.Format.Format_RGB32)
    p = QPainter(backdrop)
    grad = QLinearGradient(0, 0, 1024, 576)
    grad.setColorAt(0, QColor(30, 40, 60))
    grad.setColorAt(0.6, QColor(120, 110, 90))
    grad.setColorAt(1, QColor(210, 190, 150))
    p.fillRect(backdrop.rect(), grad)
    p.end()
    rendered = render_page(sample_page(tpl), FRAME, backdrop, template=tpl)
    from dvd.gui.menu_page import compose

    image = compose(rendered, 0)
    return image.scaled(1024, 576).scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)


class TemplateEditor(QDialog):
    saved = Signal(str)  # the saved (or imported) template's name

    def __init__(self, current: str = "minimal", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("tpl.window"))
        self.resize(940, 640)
        box = QHBoxLayout(self)
        left = QVBoxLayout()
        base_row = QHBoxLayout()
        base_row.addWidget(QLabel(t("tpl.start_from")))
        self.base = QComboBox()
        for name in list_templates():
            self.base.addItem(template_text(name), name)
        self.base.setCurrentIndex(max(0, self.base.findData(current)))
        self.base.currentIndexChanged.connect(self._load_base)
        base_row.addWidget(self.base, 1)
        left.addLayout(base_row)
        self.form_holder = QWidget()
        self.form = QFormLayout(self.form_holder)
        scroll = QScrollArea()
        scroll.setWidget(self.form_holder)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        left.addWidget(scroll, 1)
        box.addLayout(left, 1)
        right = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(512, 288)
        self.preview.setObjectName("videoWell")
        right.addWidget(self.preview)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(t("tpl.name")))
        self.name = QLineEdit()
        self.name.setMaxLength(40)
        name_row.addWidget(self.name, 1)
        right.addLayout(name_row)
        buttons = QHBoxLayout()
        self.save_button = QPushButton(t("tpl.save"))
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        export = QPushButton(t("tpl.export"))
        export.clicked.connect(self._export)
        imp = QPushButton(t("tpl.import"))
        imp.clicked.connect(self._import)
        for b in (self.save_button, export, imp):
            buttons.addWidget(b)
        right.addLayout(buttons)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        right.addStretch()
        box.addLayout(right)
        self.tpl: Template = TEMPLATES["minimal"]
        self.widgets: dict[str, QWidget] = {}
        self._load_base()

    # ------------------------------------------------------------------ form

    def _load_base(self) -> None:
        name = self.base.currentData()
        try:
            self.tpl = load_template(name)
        except TemplateError as exc:
            self.status.setText(str(exc))
            return
        self.base_name = name if name in TEMPLATES else self._base_of(name)
        self.name.setText("" if name in TEMPLATES else name)
        self._build_form()
        self._update()

    @staticmethod
    def _base_of(name: str) -> str:
        import yaml

        from dvd.menu.templates import template_folder

        data = yaml.safe_load((template_folder() / f"{name}.yaml").read_text("utf-8")) or {}
        return data.get("base", "minimal")

    def _build_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.widgets = {}
        for f in fields(Template):
            key, value = f.name, getattr(self.tpl, f.name)
            if key == "name":
                continue
            if key in COLOURS or key == "tint":
                w = QPushButton()
                w.clicked.connect(lambda _=False, k=key: self._pick_colour(k))
                if key == "tint":
                    holder, row = QWidget(), QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    on = QCheckBox(t("tpl.tint_on"))
                    on.setChecked(value is not None)
                    on.toggled.connect(self._tint_toggled)
                    row.addWidget(on)
                    row.addWidget(w, 1)
                    holder.setLayout(row)
                    self.widgets["tint_on"] = on
                    self.form.addRow(t(f"tpl.{key}"), holder)
                else:
                    self.form.addRow(t(f"tpl.{key}"), w)
            elif choices(key):
                w = QComboBox()
                for c in choices(key):
                    w.addItem(t(f"tpl.{key}.{c}"), c)
                w.setCurrentIndex(w.findData(value))
                w.currentIndexChanged.connect(lambda _i, k=key, c=w: self._set(k, c.currentData()))
                self.form.addRow(t(f"tpl.{key}"), w)
            elif isinstance(value, bool):
                w = QCheckBox()
                w.setChecked(value)
                w.toggled.connect(lambda on, k=key: self._set(k, on))
                self.form.addRow(t(f"tpl.{key}"), w)
            elif isinstance(value, float):
                w = QDoubleSpinBox()
                w.setRange(0.0, 1.0)
                w.setDecimals(3)
                w.setSingleStep(0.005)
                w.setValue(value)
                w.valueChanged.connect(lambda v, k=key: self._set(k, round(v, 3)))
                self.form.addRow(t(f"tpl.{key}"), w)
            else:  # fonts
                w = QFontComboBox()
                w.setCurrentText(value)
                w.currentFontChanged.connect(lambda font, k=key: self._set(k, font.family()))
                self.form.addRow(t(f"tpl.{key}"), w)
            self.widgets[key] = w
        self._paint_swatches()

    def _paint_swatches(self) -> None:
        for key in (*COLOURS, "tint"):
            value = getattr(self.tpl, key)
            w = self.widgets[key]
            rgb = value or (40, 40, 40)
            w.setText("#{:02x}{:02x}{:02x}".format(*rgb) if value else t("tpl.none"))
            w.setStyleSheet(f"background: rgb{tuple(rgb)}; color: "
                            f"{'#111' if sum(rgb) > 380 else '#eee'};")  # fmt: skip
            w.setEnabled(key != "tint" or value is not None)

    def _pick_colour(self, key: str) -> None:
        current = getattr(self.tpl, key) or (20, 50, 110)
        chosen = QColorDialog.getColor(QColor(*current), self, t(f"tpl.{key}"))
        if chosen.isValid():
            self._set(key, (chosen.red(), chosen.green(), chosen.blue()))

    def _tint_toggled(self, on: bool) -> None:
        self._set("tint", (20, 50, 110) if on else None)

    def _set(self, key: str, value) -> None:
        self.tpl = replace(self.tpl, **{key: value})
        self._paint_swatches()
        self._update()

    def _update(self) -> None:
        self.preview.setPixmap(QPixmap.fromImage(preview_image(self.tpl)))

    # ------------------------------------------------------------------ files

    def save(self) -> str | None:
        name = self.name.text().strip()
        if not name:
            self.status.setText(t("tpl.need_name"))
            return None
        try:
            save_template(name, self.tpl, self.base_name)
        except TemplateError as exc:
            self.status.setText(str(exc))
            return None
        self.status.setText(t("tpl.saved", name=name))
        self._relist(name)
        self.saved.emit(name)
        return name

    def _relist(self, select: str) -> None:
        self.base.blockSignals(True)
        self.base.clear()
        for n in list_templates():
            self.base.addItem(template_text(n), n)
        self.base.setCurrentIndex(max(0, self.base.findData(select)))
        self.base.blockSignals(False)

    def _export(self) -> None:
        name = self.base.currentData()
        path, _ = QFileDialog.getSaveFileName(self, t("tpl.export"), f"{name}.yaml", FILE_FILTER)
        if path:
            try:
                export_template(name, Path(path))
                self.status.setText(t("tpl.exported", path=Path(path).name))
            except (TemplateError, OSError) as exc:
                self.status.setText(str(exc))

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("tpl.import"), "", FILE_FILTER)
        if not path:
            return
        try:
            name = import_template(Path(path))
        except (TemplateError, OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        self._relist(name)
        self._load_base()
        self.status.setText(t("tpl.imported", name=name))
        self.saved.emit(name)
