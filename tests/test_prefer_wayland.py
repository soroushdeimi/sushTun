import importlib.util
from pathlib import Path

import pytest

from xrayui import elevate


@pytest.mark.parametrize("platform_value", [None, ""])
@pytest.mark.parametrize("session_type", ["wayland", "Wayland"])
def test_prefers_wayland(monkeypatch, platform_value, session_type):
    monkeypatch.setattr(elevate.sys, "platform", "linux")
    environ = {"XDG_SESSION_TYPE": session_type, "WAYLAND_DISPLAY": "wayland-0"}
    if platform_value is not None:
        environ["QT_QPA_PLATFORM"] = platform_value
    elevate.prefer_wayland(environ)
    assert environ["QT_QPA_PLATFORM"] == "wayland;xcb"


def test_preserves_user_platform(monkeypatch):
    monkeypatch.setattr(elevate.sys, "platform", "linux")
    environ = {
        "XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0",
        "QT_QPA_PLATFORM": "offscreen",
    }
    elevate.prefer_wayland(environ)
    assert environ["QT_QPA_PLATFORM"] == "offscreen"


@pytest.mark.parametrize("platform, session, display", [
    ("linux", "x11", "wayland-0"),
    ("linux", "wayland", None),
    ("linux", "wayland", ""),
    ("darwin", "wayland", "wayland-0"),
    ("win32", "wayland", "wayland-0"),
])
def test_leaves_other_environments_unchanged(monkeypatch, platform, session, display):
    monkeypatch.setattr(elevate.sys, "platform", platform)
    environ = {"XDG_SESSION_TYPE": session}
    if display is not None:
        environ["WAYLAND_DISPLAY"] = display
    before = environ.copy()
    elevate.prefer_wayland(environ)
    assert environ == before


def test_defaults_to_process_environment(monkeypatch):
    monkeypatch.setattr(elevate.sys, "platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    elevate.prefer_wayland()
    assert elevate.os.environ["QT_QPA_PLATFORM"] == "wayland;xcb"


def test_deb_depends_on_xcb_cursor():
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("build_deb", root / "scripts" / "build_deb.py")
    deb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deb)
    fields = dict(line.split(": ", 1) for line in deb._control("0.10.0", "amd64", 1).splitlines()
                  if ": " in line)
    assert "libxcb-cursor0" in fields["Depends"].split(", ")
    assert "libxcb-cursor0" not in fields["Recommends"].split(", ")
