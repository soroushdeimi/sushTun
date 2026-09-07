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

    def restore_on_quit(*_args) -> None:
        try:
            window.conn.disconnect()
        except Exception:
            pass

    app.aboutToQuit.connect(restore_on_quit)
    # Windows shutdown sends this before killing the process; atexit often misses it.
    if hasattr(app, "commitDataRequest"):
        app.commitDataRequest.connect(restore_on_quit)
    return app.exec()
