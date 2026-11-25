"""Elevation. Network changes (routes/DNS/TUN) require admin/root."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Set when the macOS password was given but the elevated copy was refused its
# own files by privacy protection (see _relaunch_macos).
mac_privacy_blocked = False


def prefer_wayland(environ=None) -> None:
    """Prefer Wayland: elevated X11 windows can fail the user's display auth."""
    if environ is None:
        environ = os.environ
    if (sys.platform.startswith("linux")
            and not environ.get("QT_QPA_PLATFORM")
            and environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            and environ.get("WAYLAND_DISPLAY")):
        environ["QT_QPA_PLATFORM"] = "wayland;xcb"


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
# Same name sudo uses, so everything that already reads it (core.userfs,
# core.desktop) finds the user behind the macOS password prompt too.
_MAC_UID = "SUDO_UID"

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
    if IS_MAC:
        # pkexec and sudo record who elevated; the macOS prompt does not.
        # Files saved where the user chose are then written as them.
        env[_MAC_UID] = str(os.getuid())
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
        elif key == _MAC_UID and IS_MAC and value.isdigit() and int(value) != 0:
            os.environ[key] = value
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
        try:
            return subprocess.call([pkexec, *cmd]) not in _PKEXEC_REFUSED
        except OSError:
            return False
    sudo = shutil.which("sudo")
    if sudo and sys.stdin is not None and sys.stdin.isatty():
        # sudo needs a terminal to ask for the password.
        try:
            return subprocess.call([sudo, *cmd]) == 0
        except OSError:
            return False
    return False


# How long the launcher watches the elevated copy before leaving it alone.
# An elevated start that is going to fail (see _relaunch_macos) fails within
# the first second or two, while Python is still reading its own files.
_MAC_START_WATCH = 4.0

# launchctl(1): `asuser UID command` runs the command in that user's Mach
# bootstrap context (their login session's services) without changing its
# credentials -- the process stays uid 0, so routes/DNS/TUN still work.
_LAUNCHCTL = "/bin/launchctl"


def _session_launch_prefix() -> list[str]:
    """`[launchctl, asuser, <uid>]`, or [] when the old launch must be used.

    The uid is the launcher's own: this only ever runs unelevated, so it is
    the user behind the password prompt. An already-root caller has no
    session to join (and `asuser 0` would be meaningless), and without
    /bin/launchctl there is nothing to wrap with: both fall back.
    """
    try:
        uid = os.getuid()
    except OSError:
        return []
    if uid == 0 or not os.path.exists(_LAUNCHCTL):
        return []
    return [_LAUNCHCTL, "asuser", str(uid)]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # the elevated copy belongs to root
    return True


def _relaunch_macos_via_helper() -> bool:
    """Start the elevated app through the root launch daemon, no password.

    Only for an installed app: a source/dev run has no fixed installed path
    for the daemon to start, so it always uses the osascript prompt. Returns
    True when the helper started (or found) the elevated copy; False to fall
    back to the password prompt.
    """
    from . import paths
    from .core import macos_helper
    if not paths.installed():
        return False
    # Only a healthy helper (answers a ping with this app's version) is used.
    # An absent, unreachable, or stale-version helper falls back to the
    # password prompt rather than silently running stale logic; should_offer()
    # is then True so the UI can present the (re)install choice.
    if not macos_helper.healthy():
        return False
    # The helper derives the uid from the peer credentials, so the SUDO_UID
    # argument (which the osascript path needs) is dropped: the helper rejects
    # it, and it would be redundant anyway.
    session = [a for a in _session_args()
               if not a.startswith(f"{_SESSION_ARG}{_MAC_UID}=")]
    try:
        macos_helper.launch(session)
    except macos_helper.Refusal:
        return False
    return True


def _relaunch_macos() -> bool:
    # Password-free path: when the user installed the helper daemon and it is
    # healthy (right version), it starts the elevated app without a prompt.
    # Any refusal, absence, or stale version falls through to the osascript
    # password prompt below, so the user is never left without a window.
    if _relaunch_macos_via_helper():
        return True
    # Quoted for the shell `do shell script` runs, then escaped for the
    # AppleScript string literal around it: unquoted, a space anywhere in the
    # path split the command and the elevated app never started.
    # The session arguments too: `do shell script` starts from a bare
    # environment, which loses LANG and, in a source run, --user site-packages.
    # The elevated app is placed back in the user's login session with
    # `launchctl asuser`: started bare, it runs outside that session, and
    # launchd withholds the menu-bar agent, the Dock and the pasteboard from
    # it (no tray icon, Dock quirks, an unreachable clipboard). launchctl
    # execs into the command, keeping its pid, so the `echo $!` watch below
    # still tracks the real app -- and like any background start, it only
    # survives the launcher because stdio is redirected to files, never pipes.
    inner = " ".join(shlex.quote(a)
                     for a in [*_session_launch_prefix(), *_elevated_cmd(), *_session_args()])
    # The elevated app is started in the background and osascript returns as
    # soon as the password is given. Waiting for it to exit kept osascript
    # alive for the whole session, and macOS listed that helper as a second
    # "sushTun" in the Dock and Cmd+Tab. Its output goes to a file only this
    # user can read, which is how an early failure is still recognised below.
    fd, errlog = tempfile.mkstemp(prefix="sushtun-elevate-", suffix=".log")
    os.close(fd)
    try:
        shell = f"{inner} >/dev/null 2>{shlex.quote(errlog)} & echo $!"
        literal = shell.replace("\\", "\\\\").replace('"', '\\"')
        script = f'do shell script "{literal}" with administrator privileges'
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True)
        # A cancelled prompt (AppleScript error -128) falls back to an
        # unelevated window that says why connecting will fail, as on Linux.
        if "-128" in result.stderr:
            return False
        if result.returncode != 0:
            # Not given the rights, so nothing was started: better an
            # unelevated window that explains than no window at all.
            return False
        try:
            pid = int(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return True  # started, but there is nothing to watch
        deadline = time.monotonic() + _MAC_START_WATCH
        while _pid_alive(pid):
            if time.monotonic() >= deadline:
                return True
            time.sleep(0.1)
        # It died before opening a window. Any failure other than the one
        # below is the elevated app's own exit, not a reason to reopen.
        try:
            err = Path(errlog).read_text(encoding="utf-8", errors="replace")
        except OSError:
            err = ""
        if "Operation not permitted" in err:
            # The root copy could not read its own files: macOS privacy
            # protection keeps it out of Desktop, Documents and Downloads,
            # even after the password. Without this nothing appeared at all.
            # Open unelevated and say why.
            global mac_privacy_blocked
            mac_privacy_blocked = True
            return False
        return True
    finally:
        try:
            os.unlink(errlog)
        except OSError:
            pass


def _join(args: list[str]) -> str:
    return subprocess.list2cmdline(args)
