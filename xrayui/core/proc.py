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


def child_env(extra: dict | None = None) -> dict[str, str]:
    """The environment for a child process, plus `extra`.

    A frozen build points LD_LIBRARY_PATH at its bundled libraries so the app
    loads them, and every child inherits that. System tools then load the
    bundle's copies instead of their own: seen live, resolvectl died on the
    bundled libcrypto ("version OPENSSL_3.4.0 not found"), so DNS was never
    moved into the tunnel. PyInstaller keeps the original value in *_ORIG,
    and leaves that unset when there was none.
    """
    env = dict(os.environ)
    if getattr(sys, "frozen", False) and not IS_WIN:
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            original = env.pop(f"{var}_ORIG", None)
            if original is None:
                env.pop(var, None)
            else:
                env[var] = original
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def run(args, *, env=None, timeout=None, check=False) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=child_env(env),
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
