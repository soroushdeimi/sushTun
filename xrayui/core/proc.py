"""Subprocess helpers that never flash a console window."""
from __future__ import annotations

import os
import subprocess
import sys

IS_WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0


def _startupinfo():
    if not IS_WIN:
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


def run(args, *, env=None, timeout=None, check=False) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **{k: str(v) for k, v in env.items()}} if env else None
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=timeout,
        check=check,
        creationflags=CREATE_NO_WINDOW,
        startupinfo=_startupinfo(),
    )


def powershell(script: str, *, env=None, timeout=None) -> subprocess.CompletedProcess:
    args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    return run(args, env=env, timeout=timeout)


def ps_lines(script: str, *, env=None, timeout=None) -> list[str]:
    out = powershell(script, env=env, timeout=timeout).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]
