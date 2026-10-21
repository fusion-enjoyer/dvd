"""Desktop application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from dvd.gui.i18n import t
from dvd.gui.main_window import MainWindow
from dvd.gui.theme import load_fonts


def _below_normal_priority() -> None:
    """Previews and builds decode and encode video on every core; at normal priority that
    makes music and other programs stutter. Below normal they only use idle time, and the
    FFmpeg/HCEnc processes started from here inherit it."""
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.windll.kernel32
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
    else:
        import os

        os.nice(5)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    _below_normal_priority()
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(t("app.title"))
    load_fonts()
    window = MainWindow()
    window.show()
    if len(argv) > 1:
        window.open_path(Path(argv[1]))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
