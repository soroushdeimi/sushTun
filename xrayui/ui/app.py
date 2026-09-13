from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .. import i18n
from ..core import settings as app_settings
from . import theme
from .icon import app_icon
from .main_window import MainWindow

# Not bundled -- Noto Sans Arabic/Naskh ship on Linux, and Windows/macOS
# system fonts already cover Persian. Vazirmatn is tried first for anyone
# who does have it installed, since it reads better for Persian UI text.
_FA_FONTS = '"Vazirmatn", "Noto Sans Arabic", "Segoe UI", "Tahoma", "Geeza Pro"'


def starts_hidden(autostart: bool, settings: dict) -> bool:
    """Whether the window should stay in the tray instead of showing at launch."""
    return autostart or bool(settings.get("startup", {}).get("start_minimized"))


def run(argv: list[str], elevated: bool = True, autostart: bool = False) -> int:
    # Set before any window is built, so every widget constructed below
    # picks up the right language and direction from the start.
    i18n.set_language(app_settings.load().get("language", "en"))

    app = QApplication(argv)
    app.setApplicationName("sushTun")
    # GNOME on Wayland pairs a window with its launcher (and so its dock and
    # Alt-Tab icon) by this id; matches the .deb's sushtun.desktop.
    app.setDesktopFileName("sushtun")
    if i18n.current() == "fa":
        app.setLayoutDirection(Qt.RightToLeft)
        app.setStyleSheet(theme.build_stylesheet(f"{_FA_FONTS}, {theme._FONT}"))
    else:
        app.setStyleSheet(theme.STYLESHEET)
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
