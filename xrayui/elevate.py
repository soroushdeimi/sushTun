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


def _relaunch_linux() -> bool:
    runner = shutil.which("pkexec") or shutil.which("sudo")
    if not runner:
        return False
    subprocess.Popen([runner, *_cmd()])
    return True


def _relaunch_macos() -> bool:
    inner = " ".join(_cmd())
    script = f'do shell script "{inner}" with administrator privileges'
    subprocess.Popen(["osascript", "-e", script])
    return True


def _join(args: list[str]) -> str:
    return " ".join(f'"{a}"' if " " in a else a for a in args)
