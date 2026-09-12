"""Elevation. Network changes (routes/DNS/TUN) require admin/root."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def is_admin() -> bool:
    if IS_WIN:
        import ctypes
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def relaunch_as_admin() -> bool:
    """Relaunch elevated. Returns True if a new elevated process was started."""
    if IS_WIN:
        return _relaunch_windows()
    if IS_MAC:
        return _relaunch_macos()
    return _relaunch_linux()


def _cmd() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, "-m", "xrayui", *sys.argv[1:]]


def _relaunch_windows() -> bool:
    import ctypes
    argv = sys.argv[1:]
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, _join(argv)
    else:
        exe, params = sys.executable, _join(["-m", "xrayui", *argv])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return int(rc) > 32


# What a GUI needs to reach the user's display and session bus. pkexec scrubs
# the environment (DISPLAY and XAUTHORITY included), so without these the
# elevated window can never open and the relaunch dies with nothing on screen.
_GUI_ENV = (
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DBUS_SESSION_BUS_ADDRESS",
    "QT_QPA_PLATFORM", "QT_SCALE_FACTOR", "LANG",
)

# pkexec exit codes: 126 = the auth dialog was dismissed, 127 = not authorized
# (or no polkit agent is running).
_PKEXEC_REFUSED = (126, 127)


def _linux_env() -> list[str]:
    env = {k: os.environ[k] for k in _GUI_ENV if os.environ.get(k)}
    if "DISPLAY" in env and "XAUTHORITY" not in env:
        # X11 falls back to ~/.Xauthority, which as root would mean /root's.
        cookie = os.path.expanduser("~/.Xauthority")
        if os.path.exists(cookie):
            env["XAUTHORITY"] = cookie
    if not getattr(sys, "frozen", False):
        # pkexec starts in root's home, so `-m xrayui` (and any --user
        # site-packages holding PySide6) would not be importable. Hand the
        # elevated interpreter this one's import path.
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p and os.path.isdir(p))
    return [f"{k}={v}" for k, v in env.items()]


def _relaunch_linux() -> bool:
    env_bin = shutil.which("env") or "/usr/bin/env"
    cmd = [env_bin, *_linux_env(), *_cmd()]
    pkexec = shutil.which("pkexec")
    if pkexec:
        # Wait, so a refused prompt falls back to an unelevated window that
        # says why connecting will fail, instead of silently exiting.
        return subprocess.call([pkexec, *cmd]) not in _PKEXEC_REFUSED
    sudo = shutil.which("sudo")
    if sudo and sys.stdin is not None and sys.stdin.isatty():
        # sudo needs a terminal to ask for the password.
        return subprocess.call([sudo, *cmd]) == 0
    return False


def _relaunch_macos() -> bool:
    inner = " ".join(_cmd())
    script = f'do shell script "{inner}" with administrator privileges'
    subprocess.Popen(["osascript", "-e", script])
    return True


def _join(args: list[str]) -> str:
    return " ".join(f'"{a}"' if " " in a else a for a in args)
