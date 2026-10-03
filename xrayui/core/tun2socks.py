"""tun2socks bridge: the macOS fallback when Xray cannot open its own utun.

Bridges Xray's local SOCKS inbound to a real TUN device: a fixed
high-numbered utun device with a point-to-point address, brought up manually
after tun2socks creates it.
"""
from __future__ import annotations

import subprocess
import time

from .. import paths
from . import proc

DEVICE = "utun233"
ADDRESS = "198.18.0.1"
MTU = 1500


def _own_pattern() -> str:
    """pgrep/pkill -f pattern for the tun2socks this app launched, and no other."""
    # Starts with the binary's name: a pattern beginning "--" would be read by
    # pgrep/pkill as one of their own options.
    return f"tun2socks --device {DEVICE} "


def kill_stale() -> None:
    """Stop a tun2socks a crashed session left behind.

    It keeps DEVICE open, so the next start would fail to create it, and the
    connect then died on "TUN device did not appear".
    """
    proc.run(["pkill", "-f", _own_pattern()])


class Tun2socks:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._log = None

    def start(self, socks_host: str, socks_port: int) -> None:
        self.stop()
        self._log = open(log_path(), "w", encoding="utf-8", errors="replace")
        # Double-dash flags: tun2socks parses them with pflag, where
        # "-device" is the shorthand -d with the value "evice", and "-mtu" is
        # an unknown shorthand that makes it exit at once with a usage error.
        # No --interface: it pins tun2socks' sockets to the NIC (IP_BOUND_IF),
        # yet its only peer is Xray's SOCKS inbound on loopback, which a
        # NIC-pinned socket cannot reach. Loopback never routes into the utun,
        # so there is no loop for the flag to prevent.
        try:
            self._proc = subprocess.Popen(
                [
                    str(paths.tun2socks_bin()),
                    "--device", DEVICE,
                    "--proxy", f"socks5://{socks_host}:{socks_port}",
                    "--mtu", str(MTU),
                    "--loglevel", "warn",  # "info" wrote a line per connection
                ],
                stdout=self._log,
                stderr=subprocess.STDOUT,
                cwd=str(paths.base_dir()),
                env=proc.child_env(),
            )
        except Exception:
            self.stop()
            raise

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        kill_stale()
        if self._log is not None:
            try:
                self._log.close()
            finally:
                self._log = None


def log_path():
    return paths.base_dir() / "tun2socks.log"


def last_log_line() -> str:
    try:
        with open(log_path(), "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return "no log output"
    lines = [ln.strip() for ln in lines if ln.strip()]
    return lines[-1] if lines else "no log output"


def bring_up_device(timeout: float = 15.0, alive=None) -> bool:
    """Assign the point-to-point address once tun2socks creates the device.

    Gives up early once `alive` says tun2socks has exited, rather than waiting
    out the timeout for a device that will never appear.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.run(["ifconfig", DEVICE]).returncode == 0:
            up = proc.run(["ifconfig", DEVICE, ADDRESS, ADDRESS, "mtu", str(MTU), "up"])
            return up.returncode == 0
        if alive is not None and not alive():
            return False
        time.sleep(0.5)
    return False
