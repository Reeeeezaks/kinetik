# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point."""

from __future__ import annotations

import sys
from typing import List, Optional

from . import APP_ID, APP_NAME, __version__


def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(f"{APP_NAME} {__version__}")
        return 0
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from . import paths
    from .settings import Store
    from .ui import style
    from .ui.window import MainWindow

    paths.migrate_legacy()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)  # Wayland app id: the taskbar finds kinetik.desktop -> Icon=kinetik
    from pathlib import Path
    from PySide6.QtGui import QIcon
    bundled = Path(__file__).resolve().parent / "assets" / "kinetik.svg"
    app.setWindowIcon(QIcon.fromTheme(APP_ID, QIcon(str(bundled))))
    style.apply(app)
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda _s: style.apply(app))
    window = MainWindow(Store())
    window.show()
    return app.exec()
