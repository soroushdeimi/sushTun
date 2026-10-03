"""Linux relaunch failures and session argument boundaries, without elevation."""
import os
from types import SimpleNamespace

import pytest

from xrayui import elevate


@pytest.fixture(autouse=True)
def linux(monkeypatch):
    monkeypatch.setattr(elevate, "IS_WIN", False)
    monkeypatch.setattr(elevate, "IS_MAC", False)
    monkeypatch.setattr(elevate.subprocess, "call", lambda *a, **k: pytest.fail("real launch"))


@pytest.mark.parametrize("tool", ["pkexec", "sudo"])
def test_unlaunchable_elevation_tool_returns_false(monkeypatch, tool):
    monkeypatch.setattr(elevate.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name == tool else None)
    monkeypatch.setattr(elevate.sys, "stdin", SimpleNamespace(isatty=lambda: True))

    def fail(*args, **kwargs):
        raise FileNotFoundError("removed after discovery")

    monkeypatch.setattr(elevate.subprocess, "call", fail)
    assert elevate._relaunch_linux() is False


@pytest.mark.parametrize("code", [0, 126, 127])
def test_session_and_user_arguments_survive_pkexec(monkeypatch, code):
    session = {"DISPLAY": ":2", "WAYLAND_DISPLAY": "wayland-1",
               "XDG_RUNTIME_DIR": "/run/user/1001",
               "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/bus with spaces,guid=abc"}
    for key, value in session.items():
        monkeypatch.setenv(key, value)
    args = ["", "a 'quoted' argument", 'تهران "VPN"', "100%", "$(touch no)"]
    monkeypatch.setattr(elevate.sys, "argv", ["sushtun", *args])
    monkeypatch.setattr(elevate.shutil, "which", lambda name: "/usr/bin/pkexec")
    calls = []
    monkeypatch.setattr(elevate.subprocess, "call", lambda argv: calls.append(argv) or code)
    assert elevate._relaunch_linux() is (code == 0)
    argv = calls[0]
    for arg in args:
        assert arg in argv
    for key, value in session.items():
        assert f"--session-env={key}={value}" in argv
        monkeypatch.delenv(key)
    rest = elevate.apply_session_env(argv)
    assert all(arg in rest for arg in args)
    assert all(os.environ[key] == value for key, value in session.items())


@pytest.mark.parametrize("stdin", [None, SimpleNamespace(isatty=lambda: False)])
def test_missing_pkexec_without_terminal_does_not_launch_sudo(monkeypatch, stdin):
    monkeypatch.setattr(elevate.shutil, "which",
                        lambda name: "/usr/bin/sudo" if name == "sudo" else None)
    monkeypatch.setattr(elevate.sys, "stdin", stdin)
    assert elevate._relaunch_linux() is False


def test_already_root_is_detected(monkeypatch):
    monkeypatch.setattr(elevate.os, "geteuid", lambda: 0)
    assert elevate.is_admin()
