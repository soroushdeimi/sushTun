"""Persisted connection state under state/.

Two independent lanes, two independent stores: State (the Xray proxy lane)
and WgState (the native WireGuard lane) share the same flat
one-value-per-file mechanics but never share files, so neither lane's
disconnect can touch the other's bookkeeping.
"""
from __future__ import annotations

from .. import paths
from .network import DnsState, Interface

_FILES = (
    "active_if.txt", "active_ip.txt", "gateway.txt", "relay_ip.txt",
    "tunidx.txt", "connected.flag", "dns-mode.txt", "dns-servers.txt",
    "gateway.flag",
)

_WG_FILES = (
    "wg_connected.flag", "wg_tunidx.txt", "wg_endpoint_ip.txt",
    "wg_routes.txt", "wg_dev.txt", "wg_profile.txt",
)


class _FileStore:
    def __init__(self) -> None:
        self.dir = paths.state_dir()

    def _p(self, name: str):
        return self.dir / name

    def _read(self, name: str) -> str:
        p = self._p(name)
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""

    def _write(self, name: str, value: object) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._p(name).write_text(str(value), encoding="utf-8")

    def _clear(self, files: tuple[str, ...]) -> None:
        for name in files:
            self._p(name).unlink(missing_ok=True)


class State(_FileStore):
    def save(self, iface: Interface, server_ip: str, tun_index: int, dns: DnsState) -> None:
        self._write("active_if.txt", iface.alias)
        self._write("active_ip.txt", iface.ipv4)
        self._write("gateway.txt", iface.gateway)
        self._write("relay_ip.txt", server_ip)
        self._write("tunidx.txt", tun_index)
        self._write("dns-mode.txt", dns.mode)
        if dns.servers:
            self._write("dns-servers.txt", "\n".join(dns.servers))
        else:
            self._p("dns-servers.txt").unlink(missing_ok=True)
        self._write("connected.flag", "connected")

    def is_connected(self) -> bool:
        return self._p("connected.flag").exists()

    @property
    def alias(self) -> str | None:
        return self._read("active_if.txt") or None

    @property
    def ipv4(self) -> str | None:
        return self._read("active_ip.txt") or None

    @property
    def gateway(self) -> str | None:
        return self._read("gateway.txt") or None

    @property
    def server_ip(self) -> str | None:
        return self._read("relay_ip.txt") or None

    @property
    def tun_index(self) -> int | None:
        v = self._read("tunidx.txt")
        return int(v) if v.isdigit() else None

    def dns_state(self) -> DnsState:
        mode = self._read("dns-mode.txt") or "DHCP"
        sp = self._p("dns-servers.txt")
        servers = sp.read_text(encoding="utf-8").split() if sp.exists() else []
        return DnsState(mode=mode, servers=servers)

    def update_gateway(self, gateway: str) -> None:
        self._write("gateway.txt", gateway)

    def set_gateway(self, on: bool) -> None:
        if on:
            self._write("gateway.flag", "1")
        else:
            self._p("gateway.flag").unlink(missing_ok=True)

    def gateway_on(self) -> bool:
        return self._p("gateway.flag").exists()

    def clear(self) -> None:
        self._clear(_FILES)


class WgState(_FileStore):
    def save(
        self,
        device: str,
        profile_uid: str,
        tun_index: int | None,
        endpoint_ip: str | None,
        routes: list[str],
    ) -> None:
        self._write("wg_dev.txt", device)
        self._write("wg_profile.txt", profile_uid)
        self._write("wg_tunidx.txt", tun_index if tun_index is not None else "")
        self._write("wg_endpoint_ip.txt", endpoint_ip or "")
        self._write("wg_routes.txt", "\n".join(routes))
        self._write("wg_connected.flag", "connected")

    def is_connected(self) -> bool:
        return self._p("wg_connected.flag").exists()

    @property
    def device(self) -> str | None:
        return self._read("wg_dev.txt") or None

    @property
    def profile_uid(self) -> str | None:
        return self._read("wg_profile.txt") or None

    @property
    def tun_index(self) -> int | None:
        v = self._read("wg_tunidx.txt")
        return int(v) if v.isdigit() else None

    @property
    def endpoint_ip(self) -> str | None:
        return self._read("wg_endpoint_ip.txt") or None

    def routes(self) -> list[str]:
        p = self._p("wg_routes.txt")
        return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln] if p.exists() else []

    def clear(self) -> None:
        self._clear(_WG_FILES)
