"""Connect / disconnect orchestrator. Owns cleanup and guarantees restore."""
from __future__ import annotations

import atexit
import socket
import sys
import time
from collections.abc import Callable

from .. import paths
from . import hotspot, network, render, routing
from . import settings as app_settings
from . import tun2socks as t2s
from . import xray as xray_mod
from .profiles import Profile
from .state import State

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 10808


class ConnectError(Exception):
    pass


def _resolve(host: str) -> str:
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        return socket.gethostbyname(host)


def _wait_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect((host, port))
            return True
        except OSError:
            time.sleep(0.5)
        finally:
            s.close()
    return False


class Connection:
    def __init__(self, on_step: Callable[[str], None] | None = None) -> None:
        self._log = on_step or (lambda _m: None)
        self.state = State()
        self.xray = xray_mod.XrayProcess()
        self.tun2socks = t2s.Tun2socks()
        self._owned = False  # did this process establish the active connection?
        self._gateway_on = False
        atexit.register(self._atexit)

    def is_connected(self) -> bool:
        return self.state.is_connected()

    def connect(self, profile: Profile) -> None:
        if not profile.address or not profile.id:
            raise ConnectError("profile is missing address or id")
        if self.state.is_connected():
            raise ConnectError("already connected")

        if sys.platform == "linux":
            self._log("Experimental platform (Linux) — network backend is unverified.")
        self._log("Detecting active interface...")
        iface = network.detect_interface()
        if iface is None:
            raise ConnectError("no active internet interface found")
        self._log(f"Interface {iface.alias} ({iface.ipv4}) via {iface.gateway}")

        server_ip = _resolve(profile.address)
        self._log("Backing up DNS...")
        dns = network.backup_dns(iface.alias)

        if IS_MAC:
            self._connect_macos(profile, iface, server_ip, dns)
        else:
            self._connect_generic(profile, iface, server_ip, dns)

    def _connect_generic(self, profile: Profile, iface, server_ip: str, dns) -> None:
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
        self._setup_gateway()
        self._log("Connected.")

    def _setup_gateway(self) -> None:
        """Optionally share the tunnel with hotspot clients. Never fails the connect."""
        cfg = app_settings.load().get("gateway", {})
        if not cfg.get("enabled") or not IS_WIN:
            return
        try:
            if cfg.get("start_hotspot", True) and hotspot.tethering_state() != "On":
                self._log("Starting Windows hotspot...")
                hotspot.start_tethering()
            hotspot.enable(public_name=network.TUN_NAME)
            self._gateway_on = True
            self._log("Gateway mode on — hotspot clients now use the tunnel.")
        except Exception as exc:
            self._log(f"Gateway mode unavailable: {exc}")

    def stop_gateway(self) -> None:
        """Turn sharing off without dropping the tunnel."""
        if self._gateway_on:
            hotspot.disable()
            self._gateway_on = False

    def _connect_macos(self, profile: Profile, iface, server_ip: str, dns) -> None:
        # Xray has no native TUN inbound on macOS: run it with a SOCKS inbound
        # only, then bridge that to a real TUN device via tun2socks.
        self._log("Building runtime config (macOS: SOCKS + tun2socks bridge)...")
        rules = routing.build_rules(app_settings.load()["routing"])
        cfg = render.build(profile, iface.alias, routing_rules=rules, stats=True,
                            include_tun=False)

        self._log("Starting Xray...")
        network.remove_routes(server_ip)
        self.xray.start(cfg)
        if not _wait_port(SOCKS_HOST, SOCKS_PORT):
            self.xray.stop()
            paths.runtime_config().unlink(missing_ok=True)
            raise ConnectError("Xray SOCKS inbound did not come up")

        self._log("Starting tun2socks bridge...")
        self.tun2socks.start(SOCKS_HOST, SOCKS_PORT, iface.alias)
        if not t2s.bring_up_device():
            self.tun2socks.stop()
            self.xray.stop()
            paths.runtime_config().unlink(missing_ok=True)
            raise ConnectError("tun2socks TUN device did not appear")

        self._log("Routing DNS and traffic through the tunnel...")
        network.set_dns_loopback(iface.alias)
        network.add_routes(server_ip, iface.gateway, None)
        self.state.save(iface, server_ip, 0, dns)
        self._owned = True
        self._log("Connected.")

    def disconnect(self) -> None:
        if not self.state.is_connected() and not xray_mod.is_xray_running():
            return
        self._restore()

    def cleanup(self) -> None:
        # Explicit "restore network": also clear sharing a previous crash left behind.
        if IS_WIN and app_settings.load().get("gateway", {}).get("enabled"):
            self._gateway_on = True
        self._restore()

    def _restore(self) -> None:
        self._log("Disconnecting...")
        alias = self.state.alias
        server_ip = self.state.server_ip
        dns = self.state.dns_state()
        if self._gateway_on:
            # Undo first: leaving ICS pointed at a dead tunnel breaks the hotspot.
            try:
                hotspot.disable()
            except Exception:
                pass
            self._gateway_on = False
        if IS_MAC:
            self.tun2socks.stop()
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
