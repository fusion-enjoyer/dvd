"""Pro mode editor for a title's picture: crop and the pre-processing settings.

Edits go straight into the title's `video` (crop, overrides); `changed` tells the window to
save, re-plan and redraw the preview. A setting left on "from profile" has no override.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from dvd.gui.i18n import t
from dvd.probe import VideoTrack
from dvd.profiles import SETTINGS, resolve
from dvd.project.model import Crop, Profiles, Title

EDITABLE = ("kernel", "deband", "dither", "side_fill", "encoder")
SIDES = ("top", "bottom", "left", "right")


def value_text(key: str, value) -> str:
    if key == "dither":
        return t(f"pro.dither.{value}")
    if key == "kernel":
        return {"spline36": "Spline36", "lanczos": "Lanczos", "bicubic": "Bicubic"}[value]
    if key == "side_fill":
        return t(f"pro.side_fill.{value}")
    if key == "encoder":
        return {"hcenc": "HCEnc", "ffmpeg": "FFmpeg"}[value]
    return str(value)


def _label(text: str, name: str) -> QLabel:
    w = QLabel(text)
    w.setObjectName(name)
    w.setWordWrap(True)
    return w


class VideoEditor(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.title: Title | None = None
        self.detected: Crop | None = None
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 8, 0, 8)
        box.setSpacing(6)
        box.addWidget(_label(t("pro.crop"), "muted"))
        self.crop_mode = QComboBox()
        for mode in ("auto", "none", "manual"):
            self.crop_mode.addItem(t(f"pro.crop_mode.{mode}"), mode)
        self.crop_mode.currentIndexChanged.connect(self._crop_mode_changed)
        box.addWidget(self.crop_mode)
        self.crop_hint = _label("", "hint")
        box.addWidget(self.crop_hint)
        self.sides = QWidget()
        grid = QGridLayout(self.sides)
        grid.setContentsMargins(0, 0, 0, 0)
        self.spins: dict[str, QSpinBox] = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(500)  # one preview redraw per burst of clicks
        self.timer.timeout.connect(self._crop_values_changed)
        for i, side in enumerate(SIDES):
            spin = QSpinBox()
            spin.setSingleStep(2)  # 4:2:0 chroma: crop in pairs of pixels
            spin.setSuffix(" px")
            spin.valueChanged.connect(lambda _v: self.timer.start())
            self.spins[side] = spin
            grid.addWidget(_label(t(f"pro.side.{side}"), "muted"), i // 2 * 2, i % 2)
            grid.addWidget(spin, i // 2 * 2 + 1, i % 2)
        box.addWidget(self.sides)
        box.addSpacing(6)
        box.addWidget(_label(t("pro.preprocess_section"), "sectionLabel"))
        self.combos: dict[str, QComboBox] = {}
        for key in EDITABLE:
            box.addWidget(_label(t(f"pro.{key}"), "muted"))
            combo = QComboBox()
            combo.addItem("", None)  # "from profile", text set in show()
            allowed = SETTINGS[key][1]
            for value in allowed:
                combo.addItem(value_text(key, value), value)
            combo.currentIndexChanged.connect(lambda _i, k=key: self._setting_changed(k))
            self.combos[key] = combo
            box.addWidget(combo)

    # ------------------------------------------------------------------ show

    def show_title(self, title: Title, v: VideoTrack | None, profiles: Profiles,
                   detected: Crop | None) -> None:  # fmt: skip
        self.title, self.detected = title, detected
        widgets = [self.crop_mode, *self.spins.values(), *self.combos.values()]
        for w in widgets:
            w.blockSignals(True)
        crop = title.video.crop
        mode = "manual" if isinstance(crop, Crop) else crop
        self.crop_mode.setCurrentIndex(self.crop_mode.findData(mode))
        values = crop if isinstance(crop, Crop) else (detected or Crop())
        for side, spin in self.spins.items():
            limit = (v.height if side in ("top", "bottom") else v.width) // 2 if v else 1000
            spin.setRange(0, limit)
            spin.setValue(getattr(values, side))
        self.sides.setVisible(mode == "manual")
        self.crop_hint.setText(self._crop_hint(mode, detected))
        self.crop_hint.setVisible(bool(self.crop_hint.text()))
        overrides = title.video.overrides
        try:
            from_profile = resolve(profiles)
        except ValueError:
            from_profile = None
        for key, combo in self.combos.items():
            base = value_text(key, from_profile[key]) if from_profile else "?"
            combo.setItemText(0, t("pro.from_profile_value", value=base))
            combo.setCurrentIndex(max(0, combo.findData(overrides[key])) if key in overrides else 0)
        for w in widgets:
            w.blockSignals(False)

    @staticmethod
    def _crop_hint(mode: str, detected: Crop | None) -> str:
        if mode != "auto":
            return ""
        if detected is None:
            return t("pro.crop_auto")
        if detected == Crop():
            return t("pro.crop_none")
        return t("pro.crop_found", top=detected.top, bottom=detected.bottom,
                 left=detected.left, right=detected.right)  # fmt: skip

    # ----------------------------------------------------------------- edits

    def _crop_mode_changed(self) -> None:
        if self.title is None:
            return
        mode = self.crop_mode.currentData()
        if mode == "manual":
            self.title.video.crop = Crop(**{s: self.spins[s].value() for s in SIDES})
        else:
            self.title.video.crop = mode
        self.sides.setVisible(mode == "manual")
        self.changed.emit()

    def _crop_values_changed(self) -> None:
        if self.title is None or self.crop_mode.currentData() != "manual":
            return
        values = {s: self.spins[s].value() // 2 * 2 for s in SIDES}
        if Crop(**values) != self.title.video.crop:
            self.title.video.crop = Crop(**values)
            self.changed.emit()

    def _setting_changed(self, key: str) -> None:
        if self.title is None:
            return
        value = self.combos[key].currentData()
        overrides = dict(self.title.video.overrides)
        if value is None:
            overrides.pop(key, None)
        else:
            overrides[key] = value
        self.title.video.overrides = overrides
        self.changed.emit()
