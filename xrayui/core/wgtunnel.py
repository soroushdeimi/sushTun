"""WireGuard lane: a native WireGuard tunnel that runs alongside the Xray
lane instead of replacing it.

Deliberately much smaller than Connection — no DNS hijack, no boot-restore
task, no hotspot sharing. Only a wireguard-go process, one adapter, and the
handful of routes that make a split-tunnel WireGuard profile (AllowedIPs
narrower than 0.0.0.0/0) coexist with whatever the proxy lane is doing.
"""
from __future__ import annotations

import atexit
import ipaddress
import sys
import time
from collections.abc import Callable

from . import network, proc, wgconf
from . import wireguard as wg_mod
from .connection import _resolve
from .profiles import Profile
from .state import State, WgState

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


class WgError(Exception):
    pass


class WgTunnel:
    def __init__(self, on_step: Callable[[str], None] | None = None) -> None:
        self._log = on_step or (lambda _m: None)
        self.state = WgState()
        self.wg = wg_mod.WireGuardTunnel()
        self._owned = False
        atexit.register(self._atexit)

    def is_connected(self) -> bool:
        return self.state.is_connected()

    def connect(self, profile: Profile) -> None:
        if (profile.protocol or "").lower() != "wireguard":
            raise WgError("this lane only runs WireGuard profiles")
        if not profile.address or not profile.id or not profile.pbk:
            raise WgError("profile is missing address, private key, or peer public key")
        if wgconf.has_reserved(profile):
            raise WgError(
                "This profile uses a Reserved value (Xray/WARP obfuscation), which "
                "wireguard-go does not support. Run it in the Proxy (Xray) lane instead."
            )
        if self.state.is_connected():
            raise WgError("WireGuard lane already connected")
        if wgconf.is_full_tunnel(profile) and State().is_connected():
            raise WgError(
                "This profile has no split AllowedIPs (full tunnel), which would fight "
                "the Proxy lane's default route. Disconnect the Proxy lane first."
            )

        self._log("Detecting active interface...")
        iface = network.detect_interface()
        if iface is None:
            raise WgError("no active internet interface found")
        self._log(f"Interface {iface.alias} ({iface.ipv4}) via {iface.gateway}")

        endpoint_ip = _resolve(profile.address)
        self._warn_lan_collision(iface, profile)

        pinned_ip: str | None = None
        added_prefixes: list[str] = []
        tun_index: int | None = None
        try:
            if not profile.wg_endpoint_via_proxy:
                self._log(f"Pinning WireGuard endpoint {endpoint_ip} via {iface.gateway}...")
                network.add_host_route(endpoint_ip, iface.gateway)
                pinned_ip = endpoint_ip

            self._log("Starting wireguard-go...")
            self.wg.start()
            if not wg_mod.wait_for_uapi(self.wg.device):
                raise WgError("wireguard-go did not create its UAPI endpoint")

            self._log("Configuring WireGuard peer...")
            payload = wgconf.uapi_payload(profile, endpoint_ip=endpoint_ip)
            response = wg_mod.uapi_set(self.wg.device, payload)
            if "errno=0" not in response:
                detail = response.strip() or "no response"
                raise WgError(f"wireguard-go rejected configuration: {detail}")

            self._log("Waiting for TUN adapter...")
            tun_index = self._wait_for_adapter()
            if tun_index is None:
                raise WgError(f"TUN interface {self.wg.device} did not appear")

            self._log("Assigning address and bringing adapter up...")
            self._assign_address(profile, tun_index)

            self._log("Adding routes...")
            for prefix in wgconf.allowed_ips(profile):
                network.add_prefix_route(prefix, tun_index)
                added_prefixes.append(prefix)

            self.state.save(self.wg.device, profile.uid, tun_index, endpoint_ip, added_prefixes)
            self._owned = True
            self._log("WireGuard tunnel connected.")
        except Exception:
            self._teardown(pinned_ip, added_prefixes, tun_index)
            raise

    def _wait_for_adapter(self) -> int | None:
        if IS_MAC:
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                if proc.run(["ifconfig", self.wg.device]).returncode == 0:
                    return 0
                time.sleep(0.5)
            return None
        return network.wait_for_tun(self.wg.device)

    def _warn_lan_collision(self, iface, profile: Profile) -> None:
        try:
            local = ipaddress.ip_address(iface.ipv4)
        except ValueError:
            return
        for prefix in wgconf.allowed_ips(profile):
            try:
                net = ipaddress.ip_network(prefix, strict=False)
            except ValueError:
                continue
            if local in net:
                self._log(
                    f"Warning: AllowedIPs {prefix} overlaps this machine's own network "
                    f"({iface.ipv4}) — local devices (router, printers) may become unreachable."
                )

    def _assign_address(self, profile: Profile, tun_index: int) -> None:
        addrs = wgconf.local_addresses(profile)
        mtu = int(profile.wg_mtu) if profile.wg_mtu else 1420
        if IS_WIN:
            _assign_address_win(self.wg.device, addrs, mtu)
        elif IS_MAC:
            _assign_address_mac(self.wg.device, addrs, mtu)
        else:
            _assign_address_linux(self.wg.device, addrs, mtu)

    def disconnect(self) -> None:
        if not self.state.is_connected() and not self.wg.is_running():
            return
        self._log("Disconnecting WireGuard tunnel...")
        self._teardown(self.state.endpoint_ip, self.state.routes(), self.state.tun_index)
        self._log("WireGuard tunnel disconnected.")

    def _teardown(self, endpoint_ip: str | None, prefixes: list[str], tun_index: int | None) -> None:
        for prefix in prefixes:
            try:
                network.remove_prefix_route(prefix, tun_index or 0)
            except Exception:
                pass
        if endpoint_ip:
            try:
                network.remove_host_route(endpoint_ip)
            except Exception:
                pass
        self.wg.stop()
        self.state.clear()
        self._owned = False

    def recover_if_stale(self) -> bool:
        """Undo leftover routes when a previous run never disconnected.

        Routes only, no DNS — low risk compared to the proxy lane, so this
        is not wired into the boot-restore scheduled task.
        """
        if not self.state.is_connected():
            return False
        if self.wg.is_running():
            return False
        self._log("Previous WireGuard session left routes behind. Cleaning up...")
        self.disconnect()
        return True

    def _atexit(self) -> None:
        if self._owned and self.state.is_connected():
            try:
                self.disconnect()
            except Exception:
                pass


def _assign_address_win(device: str, addrs: list[str], mtu: int) -> None:
    for addr in addrs:
        ip, _, plen = addr.partition("/")
        script = (
            f"New-NetIPAddress -InterfaceAlias '{device}' -IPAddress '{ip}' "
            f"-PrefixLength {plen or '32'} -ErrorAction SilentlyContinue | Out-Null"
        )
        proc.powershell(script)
    proc.run(["netsh", "interface", "ipv4", "set", "subinterface", device,
              f"mtu={mtu}", "store=active"])


def _assign_address_linux(device: str, addrs: list[str], mtu: int) -> None:
    for addr in addrs:
        proc.run(["ip", "address", "add", addr, "dev", device])
    proc.run(["ip", "link", "set", "dev", device, "mtu", str(mtu), "up"])


def _assign_address_mac(device: str, addrs: list[str], mtu: int) -> None:
    for addr in addrs:
        ip, _, _ = addr.partition("/")
        if ":" in ip:
            proc.run(["ifconfig", device, "inet6", addr])
        else:
            proc.run(["ifconfig", device, "inet", ip, ip, "netmask", "255.255.255.255"])
    proc.run(["ifconfig", device, "mtu", str(mtu), "up"])
