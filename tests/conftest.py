"""Suite-wide guards."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_network_teardown_at_exit(monkeypatch):
    # Connection() registers an atexit hook that undoes a connection this
    # process made. A test that fakes a successful connect leaves that flag
    # set, and at interpreter exit -- long after its monkeypatches are gone --
    # the hook ran the real teardown on the developer's machine: `ip route del`
    # for the fake server and `resolvectl revert xray0` on a live tunnel.
    from xrayui.core import connection

    monkeypatch.setattr(connection.atexit, "register", lambda *a, **k: None)


def _flush_qt_widgets() -> None:
    """Destroy every leftover top-level widget now.

    Changing the application's stylesheet re-polishes every widget that still
    exists. A widget an earlier test left to the garbage collector can be half
    destroyed at that moment, and polishing it crashed the interpreter with a
    segfault: rarely, and only in some environments (CI once, locally twice).
    """
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    gc.collect()
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


@pytest.fixture(scope="session")
def flush_widgets():
    """Call before any app-wide setStyleSheet (see _flush_qt_widgets)."""
    return _flush_qt_widgets

