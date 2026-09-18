from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .. import i18n, paths
from ..core import settings as app_settings
from . import theme
from .icon import app_icon
from .main_window import MainWindow

# Bundled so Persian looks the same everywhere. Without Vazirmatn the fallback
# (Noto Sans Arabic) reports a 28px line for a 13px font, which inflates every
# button and row; Vazirmatn reports 20px.
_FA_FONTS = '"Vazirmatn", "Noto Sans Arabic", "Segoe UI", "Tahoma", "Geeza Pro"'
_BUNDLED_FONTS = ("Vazirmatn-Regular.ttf", "Vazirmatn-Medium.ttf", "Vazirmatn-Bold.ttf")


def load_bundled_fonts() -> list[str]:
    """Register the bundled Persian faces; returns the families Qt now has."""
    from PySide6.QtGui import QFontDatabase

    families: list[str] = []
    for name in _BUNDLED_FONTS:
        path = paths.font_file(name)
        if not path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id != -1:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return families


def starts_hidden(autostart: bool, settings: dict) -> bool:
    """Whether the window should stay in the tray instead of showing at launch."""
    return autostart or bool(settings.get("startup", {}).get("start_minimized"))


def run(argv: list[str], elevated: bool = True, autostart: bool = False) -> int:
    # Set before any window is built, so every widget constructed below
    # picks up the right language and direction from the start.
    i18n.set_language(app_settings.load().get("language", "en"))

    app = QApplication(argv)
    load_bundled_fonts()
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
