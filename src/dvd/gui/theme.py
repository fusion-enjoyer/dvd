"""Design tokens from docs/tasarim-sistemi.html ("Sıcak stüdyo") as Qt stylesheets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QFontDatabase

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FONT_DIR = ASSETS / "fonts"
CHEVRON = (ASSETS / "icons" / "chevron-down.svg").as_posix()
CHEVRON_UP = (ASSETS / "icons" / "chevron-up.svg").as_posix()

COLORS = {
    "zemin": "#161513",
    "panel": "#1E1C1A",
    "girdi": "#282623",
    "cizgi": "#3A3632",
    "cizgi_zayif": "#2B2926",
    "metin": "#EDE8E0",
    "metin_2": "#A29B90",
    "metin_3": "#756F66",
    "amber": "#F0B449",
    "amber_hover": "#F5C46A",
    "amber_bas": "#D99A2E",
    "on_amber": "#1A1408",
    "basari": "#5FBF7F",
    "uyari": "#F07F4A",
    "hata": "#E5534B",
    "bilgi": "#7AA8D8",
    "menu_seg": "#C9A98A",
    "video": "#000000",
}

DISPLAY_FONT = "Bricolage Grotesque"
UI_FONT = "Source Sans 3"
MONO_FONT = "JetBrains Mono"


@dataclass(frozen=True)
class Density:
    control: int  # px height of buttons and inputs
    gap: int
    font: int  # px


DENSITY = {"basit": Density(36, 16, 14), "pro": Density(26, 10, 13)}


def color(name: str) -> QColor:
    return QColor(COLORS[name])


def load_fonts() -> None:
    for name in ("SourceSans3", "BricolageGrotesque", "JetBrainsMono"):
        QFontDatabase.addApplicationFont(str(FONT_DIR / f"{name}.ttf"))


def stylesheet(mode: str) -> str:
    c, d = COLORS, DENSITY[mode]
    return f"""
* {{ font-family: "{UI_FONT}"; font-size: {d.font}px; color: {c["metin"]}; }}
QMainWindow, QDialog, QWidget#root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {c["zemin"]};
}}
QWidget#topbar, QWidget#nav, QWidget#side, QWidget#budget {{ background: {c["panel"]}; }}
QWidget#topbar {{ border-bottom: 1px solid {c["cizgi"]}; }}
QWidget#nav {{ border-right: 1px solid {c["cizgi"]}; }}
QWidget#side {{ border-left: 1px solid {c["cizgi"]}; }}
QWidget#budget {{ border-top: 1px solid {c["cizgi"]}; }}

QLabel#projectName {{ font-family: "{DISPLAY_FONT}"; font-size: 18px; font-weight: 600; }}
QLabel#pageTitle {{ font-family: "{DISPLAY_FONT}"; font-size: {22 if mode == "basit" else 17}px;
    font-weight: 600; }}
QLabel#heroTitle {{ font-family: "{DISPLAY_FONT}"; font-size: 28px; font-weight: 600; }}
QLabel#muted, QLabel#summary {{ color: {c["metin_2"]}; }}
QLabel#hint {{ color: {c["metin_3"]}; font-size: {d.font - 1}px; }}
QLabel#sectionLabel {{ color: {c["metin_3"]}; font-size: {d.font - 2}px; font-weight: 700;
    letter-spacing: 1px; }}
QLabel#mono, QLabel#value {{ font-family: "{MONO_FONT}"; font-size: {d.font - 1}px; }}
QLabel#ok {{ color: {c["basari"]}; font-weight: 600; }}
QLabel#warn {{ color: {c["uyari"]}; font-weight: 600; }}
QLabel#error {{ color: {c["hata"]}; font-weight: 600; }}

QPushButton {{
    background: {c["girdi"]}; border: 1px solid {c["cizgi"]}; border-radius: 6px;
    min-height: {d.control}px; padding: 0 {d.gap + 2}px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {c["metin_3"]}; }}
QPushButton:disabled {{ color: {c["metin_3"]}; }}
QPushButton#primary {{
    background: {c["amber"]}; border-color: {c["amber"]}; color: {c["on_amber"]};
}}
QPushButton#primary:hover {{ background: {c["amber_hover"]}; border-color: {c["amber_hover"]}; }}
QPushButton#primary:pressed {{ background: {c["amber_bas"]}; }}
QPushButton#primary:disabled {{
    background: {c["girdi"]}; border-color: {c["cizgi"]}; color: {c["metin_3"]};
}}
QPushButton#link {{ background: transparent; border: none; color: {c["amber"]};
    padding: 0; min-height: 0; }}
QPushButton#link:hover {{ text-decoration: underline; }}

QWidget#modeSwitch {{ background: {c["girdi"]}; border: 1px solid {c["cizgi"]};
    border-radius: 6px; }}
QWidget#modeSwitch QPushButton {{ background: transparent; border: none; border-radius: 3px;
    color: {c["metin_2"]}; min-height: {d.control - 10}px; padding: 0 10px; }}
QWidget#modeSwitch QPushButton:checked {{ background: {c["amber"]}; color: {c["on_amber"]}; }}

QWidget#nav QPushButton {{
    background: transparent; border: none; border-radius: 6px; text-align: left;
    color: {c["metin_2"]}; min-height: {d.control + 4}px; padding: 0 10px; font-weight: 400;
}}
QWidget#nav QPushButton:hover {{ background: {c["girdi"]}; color: {c["metin"]}; }}
QWidget#nav QPushButton:checked {{ background: rgba(240, 180, 73, 0.12); color: {c["metin"]}; }}

QComboBox, QLineEdit, QAbstractSpinBox {{
    background: {c["girdi"]}; border: 1px solid {c["cizgi"]}; border-radius: 3px;
    min-height: {d.control - 2}px; padding: 0 8px;
}}
QComboBox:focus, QLineEdit:focus, QAbstractSpinBox:focus {{ border-color: {c["amber"]}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ border: none; width: 20px; }}
QAbstractSpinBox::up-arrow {{ image: url({CHEVRON_UP}); width: 10px; height: 10px; }}
QAbstractSpinBox::down-arrow {{ image: url({CHEVRON}); width: 10px; height: 10px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({CHEVRON}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {c["panel"]}; border: 1px solid {c["cizgi"]};
    selection-background-color: {c["girdi"]}; }}
QCheckBox {{ spacing: 8px; }}
QListWidget {{ background: {c["girdi"]}; border: 1px solid {c["cizgi"]}; border-radius: 3px;
    outline: none; }}
QListWidget::item {{ padding: 3px; border: 1px solid transparent; }}
QListWidget::item:selected {{ background: rgba(240, 180, 73, 0.18); color: {c["metin"]};
    border: 1px solid {c["amber"]}; }}

QWidget#card {{ background: {c["panel"]}; border: 1px solid {c["cizgi_zayif"]};
    border-radius: 10px; }}
QWidget#dropZone {{ border: 2px dashed {c["cizgi"]}; border-radius: 10px; }}
QWidget#dropZone[active="true"] {{ border-color: {c["amber"]};
    background: rgba(240, 180, 73, 0.06); }}
QWidget#videoWell {{ background: {c["video"]}; border-radius: 3px; }}

QSlider::groove:horizontal {{ background: {c["girdi"]}; height: 4px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c["metin_2"]}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c["metin"]}; width: 12px; height: 12px;
    margin: -4px 0; border-radius: 6px; }}
QSlider::handle:horizontal:hover {{ background: {c["amber"]}; }}
QProgressBar {{ background: {c["girdi"]}; border: none; border-radius: 3px; height: 6px;
    text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c["amber"]}; border-radius: 3px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {c["cizgi"]}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {c["panel"]}; border: 1px solid {c["cizgi"]}; color: {c["metin"]}; }}
"""
