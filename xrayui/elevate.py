"""Elevation. Network changes (routes/DNS/TUN) require admin/root."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

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
# Nothing outside this list is ever accepted back: the receiver runs as root,
# and LD_PRELOAD and friends must not ride along.
_GUI_ENV = (
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DBUS_SESSION_BUS_ADDRESS",
    "QT_QPA_PLATFORM", "QT_SCALE_FACTOR", "LANG",
)
_SESSION_ARG = "--session-env="

# pkexec exit codes: 126 = the auth dialog was dismissed, 127 = not authorized
# (or no polkit agent is running).
_PKEXEC_REFUSED = (126, 127)


def _session_args() -> list[str]:
    env = {k: os.environ[k] for k in _GUI_ENV if os.environ.get(k)}
    if "DISPLAY" in env and "XAUTHORITY" not in env:
        # X11 falls back to ~/.Xauthority, which as root would mean /root's.
        cookie = os.path.expanduser("~/.Xauthority")
        if os.path.exists(cookie):
            env["XAUTHORITY"] = cookie
    if not getattr(sys, "frozen", False):
        # Root's interpreter would not see --user site-packages (PySide6).
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p and os.path.isdir(p))
    return [f"{_SESSION_ARG}{k}={v}" for k, v in env.items()]


def apply_session_env(argv: list[str]) -> list[str]:
    """Strip --session-env=KEY=VALUE arguments from argv and apply them."""
    rest = []
    for arg in argv:
        if not arg.startswith(_SESSION_ARG):
            rest.append(arg)
            continue
        key, _, value = arg[len(_SESSION_ARG):].partition("=")
        if key == "PYTHONPATH" and not getattr(sys, "frozen", False):
            sys.path[1:1] = [p for p in value.split(os.pathsep) if p and p not in sys.path]
        elif key in _GUI_ENV:
            os.environ[key] = value
    return rest


def _elevated_cmd() -> list[str]:
    if getattr(sys, "frozen", False):
        # Resolved, so a polkit policy keyed on the installed path matches
        # even when launched through the /usr/bin symlink.
        return [str(Path(sys.executable).resolve()), *sys.argv[1:]]
    # pkexec starts in root's home and osascript's `do shell script` in /,
    # where `-m xrayui` cannot find the package; the script's absolute path
    # puts the project on sys.path wherever it runs.
    main = Path(__file__).resolve().parent.parent / "app_main.py"
    return [sys.executable, str(main), *sys.argv[1:]]


def _relaunch_linux() -> bool:
    # The session rides as arguments rather than through `env VAR=...`, so
    # pkexec runs this program itself: the .deb's polkit policy then matches
    # and the prompt names sushTun instead of "/usr/bin/env".
    cmd = [*_elevated_cmd(), *_session_args()]
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
    # Quoted for the shell `do shell script` runs, then escaped for the
    # AppleScript string literal around it: unquoted, a space anywhere in the
    # path split the command and the elevated app never started.
    inner = " ".join(shlex.quote(a) for a in _elevated_cmd())
    literal = inner.replace("\\", "\\\\").replace('"', '\\"')
    script = f'do shell script "{literal}" with administrator privileges'
    # Wait, so a cancelled prompt (AppleScript error -128) falls back to an
    # unelevated window that says why connecting will fail, as on Linux. Any
    # other failure is the elevated app's own exit, not a reason to reopen.
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return "-128" not in result.stderr


def _join(args: list[str]) -> str:
    return " ".join(f'"{a}"' if " " in a else a for a in args)
