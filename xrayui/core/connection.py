"""Connect / disconnect orchestrator. Owns cleanup and guarantees restore."""
from __future__ import annotations

import atexit
import socket
import sys
from collections.abc import Callable

from .. import paths
from . import network, render, routing
from . import settings as app_settings
from . import xray as xray_mod
from .profiles import Profile
from .state import State


class ConnectError(Exception):
    pass


def _resolve(host: str) -> str:
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        return socket.gethostbyname(host)


class Connection:
    def __init__(self, on_step: Callable[[str], None] | None = None) -> None:
        self._log = on_step or (lambda _m: None)
        self.state = State()
        self.xray = xray_mod.XrayProcess()
        self._owned = False  # did this process establish the active connection?
        atexit.register(self._atexit)

    def is_connected(self) -> bool:
        return self.state.is_connected()

    def connect(self, profile: Profile) -> None:
        if not profile.address or not profile.id:
            raise ConnectError("profile is missing address or id")
        if self.state.is_connected():
            raise ConnectError("already connected")

        if sys.platform != "win32":
            self._log("Experimental platform (Linux/macOS) — network backend is unverified.")
        self._log("Detecting active interface...")
        iface = network.detect_interface()
        if iface is None:
            raise ConnectError("no active internet interface found")
        self._log(f"Interface {iface.alias} ({iface.ipv4}) via {iface.gateway}")

        server_ip = _resolve(profile.address)
        self._log("Backing up DNS...")
        dns = network.backup_dns(iface.alias)

        self._log("Building runtime config...")
        rules = routing.build_rules(app_settings.load()["routing"])
        cfg = render.build(profile, iface.alias, routing_rules=rules, stats=True)

        self._log("Starting Xray...")
        network.remove_routes(server_ip)
        self.xray.start(cfg)

        self._log("Waiting for TUN adapter...")
        tun = network.wait_for_tun()
        if tun is None:
            self.xray.stop()
            paths.runtime_config().unlink(missing_ok=True)
            raise ConnectError("TUN interface xray0 did not appear")

        self._log("Routing DNS and traffic through the tunnel...")
        network.set_dns_loopback(iface.alias)
        network.add_routes(server_ip, iface.gateway, tun)
        self.state.save(iface, server_ip, tun, dns)
        self._owned = True
        self._log("Connected.")

    def disconnect(self) -> None:
        if not self.state.is_connected() and not xray_mod.is_xray_running():
            return
        self._restore()

    def cleanup(self) -> None:
        self._restore()

    def _restore(self) -> None:
        self._log("Disconnecting...")
        alias = self.state.alias
        server_ip = self.state.server_ip
        dns = self.state.dns_state()
        self.xray.stop()
        network.remove_routes(server_ip)
        if alias:
            network.restore_dns(alias, dns)
        self.state.clear()
        self._owned = False
        paths.runtime_config().unlink(missing_ok=True)
        self._log("Network restored.")

    def _atexit(self) -> None:
        # Only auto-restore a connection this process created.
        if self._owned and self.state.is_connected():
            try:
                self._restore()
            except Exception:
                pass
