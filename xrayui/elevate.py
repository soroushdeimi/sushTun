"""UAC elevation. Network changes (netsh/route/DNS) require admin."""
from __future__ import annotations

import ctypes
import sys


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Relaunch elevated. Returns True if a new elevated process was started."""
    argv = sys.argv[1:]
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = _join(argv)
    else:
        exe = sys.executable
        params = _join(["-m", "xrayui", *argv])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return int(rc) > 32


def _join(args: list[str]) -> str:
    return " ".join(f'"{a}"' if " " in a else a for a in args)
