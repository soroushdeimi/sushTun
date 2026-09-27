"""Opening a link from the elevated process, which the desktop will not talk to.

Root cannot reach the user's session bus (dbus authenticates by uid and closes
the connection), so Qt's opener fails silently and the update dialog's only
button did nothing on a .deb install. These tests pin the decision -- when to
step aside for Qt, and what exactly is run when we do not.
"""
from __future__ import annotations

import subprocess
import sys
import types

import pytest

from xrayui.core import desktop


@pytest.fixture
def elevated(monkeypatch):
    """A root process on Linux that pkexec started for uid 1000."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("PKEXEC_UID", "1000")
    monkeypatch.delenv("SUDO_UID", raising=False)
    entry = types.SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_name="ada",
                                  pw_dir="/home/ada")
    monkeypatch.setitem(sys.modules, "pwd",
                        types.SimpleNamespace(getpwuid=lambda _uid: entry))
    monkeypatch.setattr(desktop.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in
                        ("xdg-open", "runuser") else None)


@pytest.fixture
def ran(monkeypatch):
    """Capture the command instead of launching a browser."""
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(desktop.subprocess, "run", fake_run)
    return calls


# -- when this module steps aside -------------------------------------------
def test_a_non_web_url_is_refused(elevated, ran):
    # The URL becomes another program's argv; only http(s) is ever opened.
    assert desktop.open_url("file:///etc/shadow") is False
    assert desktop.open_url("javascript:alert(1)") is False
    assert ran == []


def test_an_unelevated_process_leaves_it_to_qt(monkeypatch, ran):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop.os, "geteuid", lambda: 1000, raising=False)
    assert desktop.open_url("https://example.com") is False
    assert ran == []


def test_no_recorded_session_user_leaves_it_to_qt(monkeypatch, elevated, ran):
    monkeypatch.delenv("PKEXEC_UID")
    assert desktop.open_url("https://example.com") is False
    assert ran == []


def test_root_as_the_session_user_is_not_a_session(monkeypatch, elevated):
    monkeypatch.setenv("PKEXEC_UID", "0")
    assert desktop.session_user() is None


def test_sudo_records_the_user_too(monkeypatch, elevated):
    monkeypatch.delenv("PKEXEC_UID")
    monkeypatch.setenv("SUDO_UID", "1000")
    assert desktop.session_user() == (1000, 1000, "ada")


# -- what it runs ------------------------------------------------------------
def test_the_opener_runs_as_the_user_with_their_session(monkeypatch, elevated, ran):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert desktop.open_url("https://example.com/r") is True
    argv, kw = ran[0]
    assert argv == ["runuser", "-u", "ada", "--", "xdg-open", "https://example.com/r"]
    env = kw["env"]
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["HOME"] == "/home/ada"
    assert env["DISPLAY"] == ":0"
    # Nothing of root's own environment rides along.
    assert "SUDO_UID" not in env and "PKEXEC_UID" not in env


def test_the_session_bus_carried_in_by_elevate_wins(monkeypatch, elevated, ran):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/custom/bus")
    desktop.open_url("https://example.com")
    assert ran[0][1]["env"]["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/custom/bus"


def test_a_failing_opener_reports_failure(monkeypatch, elevated, ran):
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 3))
    assert desktop.open_url("https://example.com") is False


def test_a_hung_opener_is_not_waited_on_forever(monkeypatch, elevated):
    def hang(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(desktop.subprocess, "run", hang)
    assert desktop.open_url("https://example.com") is False


def test_gio_is_tried_when_xdg_open_is_missing(monkeypatch, elevated, ran):
    monkeypatch.setattr(desktop.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in
                        ("gio", "runuser") else None)
    assert desktop.open_url("https://example.com") is True
    assert ran[0][0] == ["runuser", "-u", "ada", "--", "gio", "open",
                         "https://example.com"]


def test_setpriv_stands_in_for_runuser(monkeypatch, elevated, ran):
    monkeypatch.setattr(desktop.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in
                        ("xdg-open", "setpriv") else None)
    desktop.open_url("https://example.com")
    assert ran[0][0][:6] == ["setpriv", "--reuid", "1000", "--regid", "1000",
                             "--init-groups"]
