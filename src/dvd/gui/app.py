"""Desktop application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from dvd.gui.i18n import t
from dvd.gui.main_window import MainWindow
from dvd.gui.theme import load_fonts


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
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
