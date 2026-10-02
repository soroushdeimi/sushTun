"""Keep Qt's clipboard and the macOS user's clipboard the same.

The elevated sushTun cannot see the user's pasteboard (core/desktop.py), so on
its own every paste into a field found nothing and every copy out of the app
stayed inside it. Whenever the app comes to the front it takes over whatever
the user copied elsewhere, and whatever is copied inside it goes back out.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication

from ..core import desktop


class SessionClipboard(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        # Last text seen on either side, so a copy this bridge made itself
        # is not sent straight back the way it came.
        self._last: str | None = None
        app.applicationStateChanged.connect(self._on_state)
        app.clipboard().dataChanged.connect(self._on_changed)

    def _on_state(self, state) -> None:
        if state == Qt.ApplicationActive:
            self.pull()

    def pull(self) -> None:
        text = desktop.session_clipboard_text()
        if text is None or text == self._last:
            return
        self._last = text
        self._app.clipboard().setText(text)

    def _on_changed(self) -> None:
        text = self._app.clipboard().text()
        if not text or text == self._last:
            return
        self._last = text
        desktop.set_session_clipboard_text(text)
