"""Persisted connection state under state/."""
from __future__ import annotations

from .. import paths
from .network import DnsState, Interface

_FILES = (
    "active_if.txt", "active_ip.txt", "gateway.txt", "relay_ip.txt",
    "tunidx.txt", "connected.flag", "dns-mode.txt", "dns-servers.txt",
)


class State:
    def __init__(self) -> None:
        self.dir = paths.state_dir()

    def _p(self, name: str):
        return self.dir / name

    def _read(self, name: str) -> str:
        p = self._p(name)
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""

    def _write(self, name: str, value: object) -> None:
        self._p(name).write_text(str(value), encoding="utf-8")

    def save(self, iface: Interface, server_ip: str, tun_index: int, dns: DnsState) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
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

    def clear(self) -> None:
        for name in _FILES:
            self._p(name).unlink(missing_ok=True)
