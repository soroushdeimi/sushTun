"""tun2socks bridge for macOS, where Xray has no native TUN inbound.

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


class Tun2socks:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._log = None

    def start(self, socks_host: str, socks_port: int, interface: str) -> None:
        self.stop()
        log_path = paths.base_dir() / "tun2socks.log"
        self._log = open(log_path, "w", encoding="utf-8", errors="replace")
        self._proc = subprocess.Popen(
            [
                str(paths.tun2socks_bin()),
                "-device", DEVICE,
                "-proxy", f"socks5://{socks_host}:{socks_port}",
                "-interface", interface,
                "-mtu", str(MTU),
                "-loglevel", "info",
            ],
            stdout=self._log,
            stderr=subprocess.STDOUT,
            cwd=str(paths.base_dir()),
        )

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
        if self._log is not None:
            try:
                self._log.close()
            finally:
                self._log = None


def bring_up_device(timeout: float = 15.0) -> bool:
    """Assign the point-to-point address once tun2socks creates the device."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.run(["ifconfig", DEVICE]).returncode == 0:
            proc.run(["ifconfig", DEVICE, ADDRESS, ADDRESS, "mtu", str(MTU), "up"])
            return True
        time.sleep(0.5)
    return False
