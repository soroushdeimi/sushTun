"""Password-free elevation on macOS: a root launch daemon starts the app.

The app still runs as root in the user's GUI session (``launchctl asuser``),
so the clipboard bridge, tray and Dock keep working. Only the password step
changes: instead of ``osascript ... with administrator privileges`` every
launch, a LaunchDaemon (``/Library/LaunchDaemons/…helper.plist``) is
socket-activated by launchd and starts the *installed* app on request.

The daemon runs the installed app binary itself (``--helper``), so there is
no separate helper executable to keep in sync across updates. The request
carries no command and no path: the helper derives the uid from the peer
credentials (``getpeereid``), accepts only a whitelist of session arguments,
and executes exactly what ``elevate._elevated_cmd`` +
``elevate._session_launch_prefix`` do today.

Everything is opt-in. An untouched install behaves exactly as before; the
client (``elevate.py``) falls back to the osascript password prompt whenever
the helper is absent, refuses, or is a stale version.

macOS only. Stdlib + ctypes, no new dependencies.
"""
from __future__ import annotations

import ctypes
import json
import os
import shlex
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

from .. import __version__, paths

# Fixed label and paths: one helper per machine, known to launchd and to the
# client. The socket lives in /var/run (a symlink to /private/var/run).
LABEL = "com.soroushdeimi.sushtun.helper"
PLIST_NAME = f"{LABEL}.plist"
PLIST_PATH = Path("/Library/LaunchDaemons") / PLIST_NAME
SOCK_PATH = Path("/var/run/sushtun-helper.sock")
# launchd.plist: "Property lists don't support octal, so convert to decimal."
SOCK_MODE = 0o660  # 408

# The app binary the daemon starts: the installed .app's executable.
APP_EXE = Path("/Applications/sushTun.app/Contents/MacOS/sushtun")

# Protocol bounds.
MAX_REQUEST = 8192
READ_TIMEOUT = 5.0
# Bounded count per minute: a real launch makes at most a couple of requests.
RATE_LIMIT = 10
RATE_WINDOW = 60.0

# The helper protocol version. A mismatch between the running app and the
# installed plist means the plist must be reinstalled, not silently used.
HELPER_VERSION = 1

# launchctl(1) and the session wrapper, same as elevate.py uses.
_LAUNCHCTL = "/bin/launchctl"

# The session arguments the helper will accept, mirroring elevate._GUI_ENV.
# The receiver runs as root, so nothing outside this list is ever accepted.
_ALLOWED_SESSION_KEYS = frozenset({
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DBUS_SESSION_BUS_ADDRESS",
    "QT_QPA_PLATFORM", "QT_SCALE_FACTOR", "LANG",
})
_SESSION_ARG = "--session-env="
# Same name sudo uses (see elevate._MAC_UID).
_MAC_UID = "SUDO_UID"

# A session value is a locale/display style string: bounded, printable, and
# free of shell metacharacters. The helper never shells out, but a value that
# could not be a legitimate display setting is rejected anyway.
_MAX_VALUE_LEN = 512
_BAD_VALUE_CHARS = frozenset(';&|`$<>(){}[]!#~*\n\r"\'\\')


class Refusal(Exception):
    """The helper refused the request; the client must fall back to osascript."""


def _is_mac() -> bool:
    return sys.platform == "darwin"


# -- peer credentials --------------------------------------------------------

def _getpeereid(fd: int) -> int:
    """The uid of the connected peer, via getpeereid(3). -1 on failure."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                                ctypes.POINTER(ctypes.c_int),
                                ctypes.POINTER(ctypes.c_int)]
    libc.getpeereid.restype = ctypes.c_int
    uid = ctypes.c_int(-1)
    gid = ctypes.c_int(-1)
    euid = ctypes.c_int(-1)
    if libc.getpeereid(fd, ctypes.byref(uid), ctypes.byref(gid),
                       ctypes.byref(euid)) != 0:
        return -1
    return uid.value


# -- path safety -------------------------------------------------------------

def _path_is_safe(path: Path, console_uid: int | None) -> bool:
    """True when `path` is the real installed app, not a user-planted copy.

    The property enforced: no user other than the owner can swap the binary,
    and the app sits in a system location, not a dev checkout.

    macOS reality (verified on a live machine) shapes two details:
      * ``/Applications`` is ``root:admin`` and *group*-writable by design, so
        a "not group-writable" rule would refuse every real install. The rule
        is therefore "not *world*-writable" for the parents.
      * A drag-installed ``.app`` is owned by the user who dragged it in, not
        root. So the executable may be owned by root *or* the console user;
        a copy owned by some other uid is refused.
    Every parent directory must be root-owned and not world-writable, which
    rejects a dev copy (its parents, e.g. ``~/Desktop``, are user-owned) and a
    ``/tmp`` copy (``/tmp`` is world-writable).
    """
    p = Path(path).resolve()
    if not p.is_file():
        return False
    # The executable itself: not world-writable, owned by root or the console
    # user (a drag-install). A third uid means someone else's copy. os.lstat
    # (not Path.lstat) so the lookup is explicit and patchable in tests.
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if st.st_mode & stat.S_IWOTH:
        return False
    if st.st_uid != 0 and (console_uid is None or st.st_uid != console_uid):
        return False
    # Every parent directory: root-owned and not world-writable.
    parent = p.parent
    while True:
        try:
            pst = os.lstat(parent)
        except OSError:
            return False
        if pst.st_uid != 0:
            return False
        if pst.st_mode & stat.S_IWOTH:
            return False
        if parent == parent.parent:
            return True
        parent = parent.parent


# -- request validation ------------------------------------------------------

def _validate_session_args(raw: object) -> list[str]:
    """Validate the whitelist of session args; raise Refusal on any problem."""
    if not isinstance(raw, list):
        raise Refusal("session args are not a list")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise Refusal("session arg is not a string")
        if not item.startswith(_SESSION_ARG):
            raise Refusal("session arg is not a --session-env= value")
        key, _, value = item[len(_SESSION_ARG):].partition("=")
        if key in seen:
            raise Refusal("duplicate session key")
        seen.add(key)
        if key == _MAC_UID:
            # The uid is derived from the peer, never taken from the request.
            raise Refusal("uid is not a session arg")
        if key not in _ALLOWED_SESSION_KEYS:
            raise Refusal("unknown session key")
        if len(value) > _MAX_VALUE_LEN:
            raise Refusal("session value too long")
        if any(c in _BAD_VALUE_CHARS for c in value):
            raise Refusal("session value has shell metacharacters")
        out.append(item)
    return out


def _validate_request(data: object) -> list[str]:
    """Validate a decoded request; return the session args."""
    if not isinstance(data, dict):
        raise Refusal("request is not an object")
    if set(data) - {"op", "session"}:
        raise Refusal("unknown request key")
    if data.get("op") != "launch":
        raise Refusal("unknown op")
    return _validate_session_args(data.get("session", []))


# -- rate limit --------------------------------------------------------------

class RateLimiter:
    """Bounded count per sliding window."""

    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW):
        self._limit = limit
        self._window = window
        self._hits: list[float] = []

    def allow(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._hits = [t for t in self._hits if now - t < self._window]
        if len(self._hits) >= self._limit:
            return False
        self._hits.append(now)
        return True


# -- the command the helper runs --------------------------------------------

def _session_launch_prefix(uid: int) -> list[str]:
    """`[launchctl, asuser, <uid>]`, or [] when the old launch must be used."""
    if uid == 0 or not os.path.exists(_LAUNCHCTL):
        return []
    return [_LAUNCHCTL, "asuser", str(uid)]


def _launch_command(uid: int, session: list[str]) -> list[str]:
    """The elevated app: the fixed installed path, in the user's session.

    No path or argument comes from the request: the helper executes exactly
    what ``elevate._elevated_cmd`` + ``elevate._session_launch_prefix`` do
    today, with the installed app standing in for the launcher's own binary.
    """
    return [*_session_launch_prefix(uid), str(APP_EXE), *session]


# -- plist -------------------------------------------------------------------

def _plist_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plist_xml(app_exe: str = str(APP_EXE), version: int = HELPER_VERSION) -> str:
    """The LaunchDaemon plist: socket-activated, starts the installed app."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{_plist_escape(app_exe)}</string>
        <string>--helper</string>
    </array>
    <key>Sockets</key>
    <dict>
        <key>Listener</key>
        <dict>
            <key>SockPathName</key>
            <string>{_plist_escape(str(SOCK_PATH))}</string>
            <key>SockPathMode</key>
            <integer>{SOCK_MODE}</integer>
        </dict>
    </dict>
    <key>Version</key>
    <integer>{version}</integer>
</dict>
</plist>
"""


# -- install / uninstall command construction --------------------------------

def install_commands(python: str = sys.executable,
                     app_exe: str = str(APP_EXE)) -> list[list[str]]:
    """The argv steps that install the helper, run as root.

    One osascript admin prompt writes the plist (root:wheel 0644) and
    bootstraps it. No shell: every path is a separate argv element, so a path
    with spaces or quotes cannot inject.
    """
    xml = plist_xml(app_exe=app_exe)
    # The plist is written by the elevated step, not by this (unelevated)
    # process, so it is passed as a single argv element to the shell script.
    write = (
        f"cat > {shlex.quote(str(PLIST_PATH))} <<'SUSHTUN_PLIST_EOF'\n"
        f"{xml}SUSHTUN_PLIST_EOF\n"
        f"chown root:wheel {shlex.quote(str(PLIST_PATH))}\n"
        f"chmod 0644 {shlex.quote(str(PLIST_PATH))}\n"
        f"/bin/launchctl bootstrap system {shlex.quote(str(PLIST_PATH))}\n"
    )
    return [
        ["osascript", "-e",
         f'do shell script {shlex.quote(write)} with administrator privileges'],
    ]


def uninstall_commands() -> list[list[str]]:
    """The argv steps that remove the helper, run as root."""
    script = (
        f"/bin/launchctl bootout system {shlex.quote(LABEL)} 2>/dev/null; "
        f"rm -f {shlex.quote(str(PLIST_PATH))} {shlex.quote(str(SOCK_PATH))}\n"
    )
    return [
        ["osascript", "-e",
         f'do shell script {shlex.quote(script)} with administrator privileges'],
    ]


# -- client side -------------------------------------------------------------

def _send(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(payload)


def _recv_all(sock: socket.socket) -> bytes:
    """Read the whole reply: the helper closes the connection after it."""
    chunks = []
    while True:
        b = sock.recv(4096)
        if not b:
            break
        chunks.append(b)
    return b"".join(chunks)


def _connect(timeout: float = 2.0) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(str(SOCK_PATH))
    return s


def _reply(sock: socket.socket) -> dict:
    raw = _recv_all(sock)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Refusal("helper reply is not json") from None
    if not isinstance(data, dict):
        raise Refusal("helper reply is not an object")
    return data


def ping() -> dict | None:
    """Ask the helper for its version. None when it is absent or unreachable."""
    try:
        s = _connect()
    except OSError:
        return None
    try:
        _send(s, json.dumps({"op": "ping"}).encode("utf-8"))
        data = _reply(s)
    except (OSError, Refusal):
        return None
    finally:
        s.close()
    if data.get("op") != "pong":
        return None
    return data


def launch(session: list[str]) -> str:
    """Ask the helper to start the elevated app.

    Returns "started" or "already running". Raises Refusal when the helper
    refuses, is a stale version, or is unreachable: the caller falls back to
    the osascript password prompt.
    """
    try:
        s = _connect()
    except OSError:
        raise Refusal("helper socket unreachable") from None
    try:
        payload = json.dumps({"op": "launch", "session": session}).encode("utf-8")
        _send(s, payload)
        data = _reply(s)
    except (OSError, Refusal):
        raise Refusal("helper request failed") from None
    finally:
        s.close()
    if data.get("op") == "refused":
        raise Refusal(data.get("reason", "helper refused"))
    if data.get("op") == "started":
        return "started"
    if data.get("op") == "already running":
        return "already running"
    raise Refusal("unexpected helper reply")


def installed() -> bool:
    """The plist exists on disk."""
    return PLIST_PATH.is_file()


def healthy() -> bool:
    """The helper answers a ping with the current version."""
    data = ping()
    return data is not None and data.get("version") == __version__


def status() -> dict:
    """A summary for the UI: installed, healthy, and the running version."""
    data = ping()
    return {
        "installed": installed(),
        "healthy": data is not None and data.get("version") == __version__,
        "running_version": data.get("version") if data else None,
        "app_version": __version__,
    }


def should_offer() -> bool:
    """Whether to offer the user the one-time "skip the password" choice.

    Only for an installed macOS app, and only when the helper is not already
    healthy (a stale version means a reinstall, which the UI presents as its
    own prompt).
    """
    if not _is_mac() or not paths.installed():
        return False
    return not healthy()


def install() -> bool:
    """Install the helper with one osascript admin prompt."""
    if not _is_mac():
        return False
    for argv in install_commands():
        try:
            result = subprocess.run(argv, capture_output=True, text=True)
        except OSError:
            return False
        if result.returncode != 0:
            return False
    return healthy()


def uninstall() -> bool:
    """Remove the helper: bootout, then delete the plist and socket."""
    if not _is_mac():
        return False
    for argv in uninstall_commands():
        try:
            subprocess.run(argv, capture_output=True, text=True)
        except OSError:
            return False
    return not installed()


# -- the helper side (runs as root, started by launchd) ----------------------

def _read_request(sock: socket.socket) -> bytes:
    """Read the request with a size bound and a timeout."""
    sock.settimeout(READ_TIMEOUT)
    chunks = []
    total = 0
    while True:
        b = sock.recv(4096)
        if not b:
            break
        total += len(b)
        chunks.append(b)
        if total > MAX_REQUEST:
            # Bounded before parsing: an oversize request is refused even if
            # it happens to be valid JSON.
            raise Refusal("request too large")
        # The request is a single JSON object; stop once it parses.
        try:
            json.loads(b"".join(chunks))
        except json.JSONDecodeError:
            continue
        return b"".join(chunks)
    return b"".join(chunks)


def _console_uid() -> int | None:
    """The uid of the console user, or None when it cannot be determined."""
    try:
        result = subprocess.run(
            ["stat", "-f", "%u", "/dev/console"],
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _already_running() -> bool:
    """True when an elevated copy of this app is already running."""
    from ..ui import single_instance
    return single_instance.running_instance() is not None


def _serve_one(sock: socket.socket) -> None:
    """Handle one connection. Never raises: a refusal is a reply, not a crash."""
    try:
        # The peer must be the console user, not root and not unknown.
        peer = _getpeereid(sock.fileno())
        if peer < 0:
            raise Refusal("unknown peer")
        if peer == 0:
            raise Refusal("root peer")
        console = _console_uid()
        if console is None or peer != console:
            raise Refusal("peer is not the console user")

        raw = _read_request(sock)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise Refusal("request is not json") from None

        if isinstance(data, dict) and data.get("op") == "ping":
            reply = {"op": "pong", "version": __version__,
                     "helper": HELPER_VERSION}
        else:
            if not _RATE.allow():
                raise Refusal("rate limited")
            session = _validate_request(data)
            if not _path_is_safe(APP_EXE, peer):
                raise Refusal("app path is not the installed app")
            if _already_running():
                reply = {"op": "already running"}
            else:
                cmd = _launch_command(peer, session)
                _spawn(cmd)
                reply = {"op": "started"}
    except Refusal as e:
        reply = {"op": "refused", "reason": str(e)}
    except Exception:
        # No secrets are logged; the reason is a fixed string.
        reply = {"op": "refused", "reason": "internal error"}
    try:
        sock.sendall(json.dumps(reply).encode("utf-8"))
    except OSError:
        pass


_RATE = RateLimiter()


def _spawn(cmd: list[str]) -> None:
    """Start the elevated app in the background, with a clean environment.

    The helper is a launchd job: its stdio are pipes that launchd closes, so
    the child's stdio must go to files, never pipes, or it would outlive the
    helper and block launchd.
    """
    devnull = os.open(os.devnull, os.O_RDWR)
    log = os.open(os.path.join("/tmp", "sushtun-helper.log"),
                  os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        subprocess.Popen(
            cmd,
            stdin=devnull, stdout=log, stderr=log,
            env={},  # a clean environment: nothing from the helper rides along
            start_new_session=True,
        )
    finally:
        os.close(devnull)
        os.close(log)


def serve_forever(sock: socket.socket) -> None:
    """Accept connections on the launchd-activated socket, forever."""
    while True:
        conn, _ = sock.accept()
        try:
            _serve_one(conn)
        finally:
            conn.close()


def _activated_socket() -> socket.socket:
    """The listening socket launchd created, via launch_activate_socket(3)."""
    libsystem = ctypes.CDLL("libsystem_launchd.dylib")
    libsystem.launch_activate_socket.argtypes = [ctypes.c_char_p]
    libsystem.launch_activate_socket.restype = ctypes.c_int
    fd = libsystem.launch_activate_socket(b"Listener")
    if fd < 0:
        raise OSError("launch_activate_socket failed")
    return socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM)


def run_helper() -> int:
    """The `--helper` entry point: serve the launchd-activated socket."""
    try:
        sock = _activated_socket()
    except OSError:
        # Not started by launchd (a manual run): nothing to serve.
        return 1
    try:
        serve_forever(sock)
    except KeyboardInterrupt:
        pass
    return 0
