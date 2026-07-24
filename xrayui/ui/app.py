from __future__ import annotations

from PySide6.QtWidgets import QApplication

from .icon import app_icon
from .main_window import MainWindow
from .theme import STYLESHEET


def run(argv: list[str], elevated: bool = True) -> int:
    app = QApplication(argv)
    app.setApplicationName("Xray Portable")
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(app_icon())
    window = MainWindow(elevated=elevated)
    window.show()
    return app.exec()
