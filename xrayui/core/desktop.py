"""Hand a link to the desktop session that started this process.

On Linux sushTun runs elevated (pkexec), and a root process cannot reach the
user's session bus: dbus authenticates by uid and closes the connection. Both
routes Qt's own opener takes -- the desktop portal over that bus, then
xdg-open, which on GNOME goes through gio and the same bus -- therefore fail,
returning False with nothing on screen. On a .deb install that is the only
action the update dialog offers, so "check for updates" ended in a button that
did nothing at all.

macOS elevates through a password prompt instead, with the same result: the
browser would start as root. elevate.py passes the user's uid along as
SUDO_UID, and the URL is opened as them.

Everything here is a no-op on Windows and when not elevated; the caller then
falls back to Qt, which works fine as the user.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

# pkexec and sudo each record who asked for the elevation. Without one of them
# there is no session to hand the URL to.
_UID_VARS = ("PKEXEC_UID", "SUDO_UID")
# Carried through to the opener so it reaches the same display.
_SESSION_ENV = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE",
                "XDG_CURRENT_DESKTOP", "LANG")
# macOS: `open` hands the URL to LaunchServices, which starts the browser in
# the user's own session. Run as root, it opened a root copy of the browser.
_OPENERS = (["xdg-open"], ["gio", "open"])
_MAC_OPENERS = (["open"],)
_TIMEOUT = 20.0


def session_user() -> tuple[int, int, str] | None:
    """(uid, gid, name) of the user who elevated this process, or None."""
    if sys.platform == "win32":
        return None
    try:
        import pwd
    except ImportError:  # pragma: no cover - POSIX only
        return None
    for var in _UID_VARS:
        raw = (os.environ.get(var) or "").strip()
        if not raw.isdigit() or int(raw) == 0:
            continue
        try:
            entry = pwd.getpwuid(int(raw))
        except KeyError:
            continue
        return entry.pw_uid, entry.pw_gid, entry.pw_name
    return None


def _as_user(uid: int, gid: int, name: str, argv: list[str]) -> list[str] | None:
    """`argv` wrapped so it runs as that user, or None if nothing can do it."""
    if shutil.which("runuser"):
        return ["runuser", "-u", name, "--", *argv]
    if shutil.which("setpriv"):
        return ["setpriv", "--reuid", str(uid), "--regid", str(gid),
                "--init-groups", "--", *argv]
    if shutil.which("sudo"):
        # -n: never prompt. Root needs no password, and a prompt no one can
        # answer would hang the UI thread until the timeout.
        return ["sudo", "-n", "-u", f"#{uid}", "--", *argv]
    return None


def _session_env(uid: int, home: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _SESSION_ENV}
    env["HOME"] = home
    env["PATH"] = os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin"
    # elevate.py carries these in from the session; the /run/user paths are the
    # fallback for a session that did not set them.
    env["XDG_RUNTIME_DIR"] = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    env["DBUS_SESSION_BUS_ADDRESS"] = (os.environ.get("DBUS_SESSION_BUS_ADDRESS")
                                       or f"unix:path=/run/user/{uid}/bus")
    return env


def open_url(url: str) -> bool:
    """True when the URL reached the user's browser.

    False means "not this case, or it did not work": the caller falls back to
    QDesktopServices and, if that fails too, must show the URL rather than
    pretend something happened.
    """
    # The URL becomes another program's argv, so only the two schemes this app
    # ever opens are allowed through.
    if not url.startswith(("http://", "https://")):
        return False
    if sys.platform == "win32" or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return False
    who = session_user()
    if who is None:
        return False
    uid, gid, name = who
    try:
        import pwd
        home = pwd.getpwuid(uid).pw_dir
    except (ImportError, KeyError):  # pragma: no cover - checked above
        return False
    env = _session_env(uid, home)
    for opener in _MAC_OPENERS if sys.platform == "darwin" else _OPENERS:
        if not shutil.which(opener[0]):
            continue
        argv = _as_user(uid, gid, name, [*opener, url])
        if argv is None:
            return False
        try:
            done = subprocess.run(argv, env=env, timeout=_TIMEOUT,
                                  capture_output=True)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return True
    return False


# -- the clipboard -------------------------------------------------------------
# macOS: the pasteboard belongs to the logged-in user, and the elevated copy of
# sushTun (root, behind the osascript password prompt) reads it as empty. Every
# paste into the app found nothing while other apps pasted fine, and a link
# copied out of the app never reached anything else. Reading and writing it as
# the user who elevated us goes through their pasteboard instead.
_CLIP_TIMEOUT = 5.0


def _clipboard_tool(tool: str, data: bytes | None = None) -> subprocess.CompletedProcess | None:
    if sys.platform != "darwin" or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None
    who = session_user()
    if who is None or not shutil.which(tool):
        return None
    uid, gid, name = who
    argv = _as_user(uid, gid, name, [tool])
    if argv is None:
        return None
    # Becoming the user is not enough. osascript starts the elevated app
    # outside the user's login session, and from there pbpaste reads nothing
    # even as the user; only a command placed back in that session with
    # launchctl asuser reaches their pasteboard. Measured on a macOS runner
    # from a LaunchDaemon: plain and sudo -u read "", asuser read the text.
    argv = ["launchctl", "asuser", str(uid), *argv]
    # pbpaste/pbcopy pick their text encoding from the locale; without a UTF-8
    # one anything outside ASCII (a Persian server name) came back as "?".
    env = {"LANG": "en_US.UTF-8", "PATH": os.environ.get("PATH") or "/usr/bin:/bin"}
    try:
        return subprocess.run(argv, env=env, input=data, capture_output=True,
                              timeout=_CLIP_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None


def session_clipboard_text() -> str | None:
    """The user's clipboard text, or None when this process can read the
    clipboard itself (not elevated, not macOS) or the read did not work."""
    done = _clipboard_tool("pbpaste")
    if done is None or done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", "replace")


def set_session_clipboard_text(text: str) -> bool:
    """Put `text` on the user's clipboard. False when it is not needed or failed."""
    done = _clipboard_tool("pbcopy", text.encode("utf-8"))
    return done is not None and done.returncode == 0
