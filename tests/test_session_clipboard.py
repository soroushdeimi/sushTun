"""macOS: the elevated app reads and writes the user's clipboard through them.

Root cannot see the logged-in user's pasteboard, so every paste into sushTun
found nothing while other apps pasted fine, and a copied share link never left
the app. Nothing here can reach a real pasteboard on Linux: these pin who runs
pbpaste/pbcopy, and how the Qt side stays in step without echoing.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest

from xrayui.core import desktop


@pytest.fixture
def mac_root(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(desktop.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("SUDO_UID", "501")
    monkeypatch.delenv("PKEXEC_UID", raising=False)
    entry = types.SimpleNamespace(pw_uid=501, pw_gid=20, pw_name="ada", pw_dir="/Users/ada")
    monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwuid=lambda _u: entry))
    monkeypatch.setattr(desktop.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in ("pbpaste", "pbcopy", "sudo")
                        else None)


@pytest.fixture
def ran(monkeypatch):
    calls = []

    def fake(argv, **kw):
        calls.append((argv, kw))
        out = b"vless://copied-in-safari\n" if argv[-1] == "pbpaste" else b""
        return subprocess.CompletedProcess(argv, 0, out, b"")

    monkeypatch.setattr(desktop.subprocess, "run", fake)
    return calls


def test_paste_reads_the_users_clipboard_as_the_user(mac_root, ran):
    assert desktop.session_clipboard_text() == "vless://copied-in-safari\n"
    argv, kw = ran[0]
    assert argv == ["sudo", "-n", "-u", "#501", "--", "pbpaste"]
    assert kw["env"]["LANG"] == "en_US.UTF-8"  # non-ASCII survives


def test_copy_writes_to_the_users_clipboard_as_the_user(mac_root, ran):
    assert desktop.set_session_clipboard_text("سرور آلمان") is True
    argv, kw = ran[0]
    assert argv == ["sudo", "-n", "-u", "#501", "--", "pbcopy"]
    assert kw["input"] == "سرور آلمان".encode()


def test_nothing_is_done_where_qt_can_reach_the_clipboard(monkeypatch, ran):
    # Not elevated, or not macOS: Qt's own clipboard is the user's.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(desktop.os, "geteuid", lambda: 501, raising=False)
    assert desktop.session_clipboard_text() is None
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop.os, "geteuid", lambda: 0, raising=False)
    assert desktop.set_session_clipboard_text("x") is False
    assert ran == []


def test_a_failed_read_is_not_mistaken_for_an_empty_clipboard(mac_root, monkeypatch):
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"", b"denied"))
    assert desktop.session_clipboard_text() is None


# -- the Qt side ---------------------------------------------------------------
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui.ui import clipboard_bridge  # noqa: E402


@pytest.fixture
def bridge(monkeypatch):
    app = QApplication.instance() or QApplication([])
    app.clipboard().setText("")
    pushed = []
    monkeypatch.setattr(clipboard_bridge.desktop, "session_clipboard_text",
                        lambda: "vless://copied-in-safari")
    monkeypatch.setattr(clipboard_bridge.desktop, "set_session_clipboard_text",
                        lambda text: pushed.append(text) or True)
    b = clipboard_bridge.SessionClipboard(app)
    yield app, b, pushed
    # deleteLater needs an event loop the tests never run; a bridge left
    # connected would answer the next test's clipboard changes too.
    app.applicationStateChanged.disconnect(b._on_state)
    app.clipboard().dataChanged.disconnect(b._on_changed)


def test_coming_to_the_front_brings_in_what_the_user_copied(bridge):
    app, b, pushed = bridge
    b.pull()
    assert app.clipboard().text() == "vless://copied-in-safari"
    assert pushed == []  # not echoed straight back out


def test_a_copy_inside_the_app_goes_out_to_the_user(bridge):
    app, _b, pushed = bridge
    app.clipboard().setText("vless://share-link-from-the-table")
    app.processEvents()
    assert pushed == ["vless://share-link-from-the-table"]
