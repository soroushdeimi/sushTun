"""Resolve the application icon, falling back to a standard icon if absent."""
from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

from .. import paths


def app_icon() -> QIcon:
    png = paths.icon_png()
    if png.exists():
        return QIcon(str(png))
    app = QApplication.instance()
    if app is not None:
        return app.style().standardIcon(QStyle.SP_ComputerIcon)
    return QIcon()
