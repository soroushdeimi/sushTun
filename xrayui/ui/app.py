from __future__ import annotations

from PySide6.QtWidgets import QApplication

from .icon import app_icon
from .main_window import MainWindow
from .theme import STYLESHEET


def starts_hidden(autostart: bool, settings: dict) -> bool:
    """Whether the window should stay in the tray instead of showing at launch."""
    return autostart or bool(settings.get("startup", {}).get("start_minimized"))


def run(argv: list[str], elevated: bool = True, autostart: bool = False) -> int:
    app = QApplication(argv)
    app.setApplicationName("sushTun")
    # GNOME on Wayland pairs a window with its launcher (and so its dock and
    # Alt-Tab icon) by this id; matches the .deb's sushtun.desktop.
    app.setDesktopFileName("sushtun")
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(app_icon())
    window = MainWindow(elevated=elevated, autostart=autostart)
    # A login-triggered launch stays out of the way in the tray if either the
    # --autostart flag itself or the "start minimized" setting asks for it.
    if not starts_hidden(autostart, window.settings):
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
