from __future__ import annotations

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import STYLESHEET


def run(argv: list[str], elevated: bool = True) -> int:
    app = QApplication(argv)
    app.setApplicationName("Xray Portable")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow(elevated=elevated)
    window.show()
    return app.exec()
