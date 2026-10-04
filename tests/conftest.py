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


@pytest.fixture(autouse=True)
def _no_real_update_checks(monkeypatch, request):
    # MainWindow starts a background GitHub update check during UI tests.
    # On Linux CI, late replies reached already-destroyed windows and caused
    # segfaults inside processEvents. Disable real fetches unless explicitly marked.
    from xrayui.core import updates

    if request.node.get_closest_marker("real_update_fetch") is not None:
        return

    def disabled_fetch():
        raise OSError("real update checks are disabled in tests")

    monkeypatch.setattr(updates, "_default_fetch", disabled_fetch)


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



# The Windows backend is a platform-flavoured module: importing it as
# xrayui.core._windows_test under a faked sys.platform exercises the real
# netsh/PowerShell orchestration on any CI machine.
@pytest.fixture
def win_net(monkeypatch):
    import importlib.util
    import sys

    from xrayui.core import network

    spec = importlib.util.spec_from_file_location("xrayui.core._windows_test", network.__file__)
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        spec.loader.exec_module(module)

    def unexpected(*args, **kwargs):
        pytest.fail(f"unmocked Windows command: {args}")

    monkeypatch.setattr(module.proc, "run", unexpected)
    monkeypatch.setattr(module.proc, "powershell", unexpected)
    monkeypatch.setattr(module.proc, "ps_lines", unexpected)
    return module
