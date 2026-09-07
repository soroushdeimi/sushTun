"""wireguard-go process manager for the WireGuard lane.

Modeled on tun2socks.py: start / is_running / stop around a subprocess.Popen
with a dedicated log file. Configuration goes over the cross-implementation
userspace API (UAPI) — a named pipe on Windows, a unix socket on POSIX —
rather than a config file, so keys never touch disk unencrypted.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

from .. import paths
from . import proc

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

DEVICE = "sushTun"
# macOS requires "utunN"-shaped names; tun2socks already claims utun233 for
# the proxy lane's bridge device, so the WireGuard lane uses a distinct number.
MAC_DEVICE = "utun234"


def device_name() -> str:
    return MAC_DEVICE if IS_MAC else DEVICE


_PIPE_ROOT = "\\\\.\\pipe\\"


def _uapi_pipe_name(device: str) -> str:
    """The pipe's name relative to the named-pipe filesystem root."""
    return rf"ProtectedPrefix\Administrators\WireGuard\{device}"


def _uapi_pipe_path(device: str) -> str:
    return _PIPE_ROOT + _uapi_pipe_name(device)


def _uapi_socket_path(device: str) -> str:
    return f"/var/run/wireguard/{device}.sock"


class WireGuardTunnel:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._log = None
        self.device = device_name()

    def start(self) -> None:
        self.stop()
        self.device = device_name()
        log_path = paths.base_dir() / "wireguard-go.log"
        self._log = open(log_path, "w", encoding="utf-8", errors="replace")
        env = {**os.environ}
        if IS_WIN:
            env["WG_PROCESS_FOREGROUND"] = "1"
            args = [str(paths.wireguard_go_bin()), self.device]
        else:
            args = [str(paths.wireguard_go_bin()), "-f", self.device]
        self._proc = subprocess.Popen(
            args,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            cwd=str(paths.base_dir()),
            env=env,
            creationflags=proc.CREATE_NO_WINDOW,
            startupinfo=proc._startupinfo(),
        )

    def is_running(self) -> bool:
        # A fresh process (recover_if_stale after an app restart) holds no
        # Popen handle at all, so liveness must also be checkable from the
        # adapter/UAPI endpoint alone, not just the child handle.
        if self._proc is not None and self._proc.poll() is None:
            return True
        return uapi_exists(self.device)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._log is not None:
            try:
                self._log.close()
            finally:
                self._log = None


def _pipe_exists(name: str) -> bool:
    """Answer whether a named pipe is live, without connecting to it.

    A named pipe cannot be probed with stat(). Path.exists() raises
    WinError 231 (ERROR_PIPE_BUSY) precisely when the pipe *is* live, and
    os.path.exists() answers False even then -- both because stat() tries to
    *open* the pipe, which would additionally steal an instance from
    wireguard-go's UAPI listener. Enumerating the pipe filesystem answers
    the question without opening anything.
    """
    try:
        return name in os.listdir(_PIPE_ROOT)
    except OSError:
        return False


def _uapi_exists_win(device: str) -> bool:
    return _pipe_exists(_uapi_pipe_name(device))


def _uapi_exists_posix(device: str) -> bool:
    return os.path.exists(_uapi_socket_path(device))


def uapi_exists(device: str) -> bool:
    return _uapi_exists_win(device)


def wait_for_uapi(device: str, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if uapi_exists(device):
            return True
        time.sleep(0.3)
    return False


def _uapi_set_win(device: str, payload: str) -> str:
    # Read up to the UAPI blank-line terminator rather than to EOF, matching
    # _uapi_set_posix below. A bare read() would block until the server closes
    # the connection, so it would hang forever against an implementation that
    # keeps the pipe open after replying.
    with open(_uapi_pipe_path(device), "r+b", buffering=0) as pipe:
        pipe.write(payload.encode("ascii"))
        chunks: list[bytes] = []
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"".join(chunks).endswith(b"\n\n"):
                break
        return b"".join(chunks).decode("ascii", errors="replace")


def _uapi_set_posix(device: str, payload: str) -> str:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(_uapi_socket_path(device))
        sock.sendall(payload.encode("ascii"))
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n\n"):
                break
        return b"".join(chunks).decode("ascii", errors="replace")
    finally:
        sock.close()


def uapi_set(device: str, payload: str) -> str:
    return _uapi_set_win(device, payload)


# On Linux/macOS, swap the Windows implementations for the POSIX backend,
# matching network.py's convention. The Windows code above is left untouched
# and never runs off-Windows.
if sys.platform != "win32":
    uapi_exists = _uapi_exists_posix
    uapi_set = _uapi_set_posix
