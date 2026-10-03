"""Persisted connection state under state/."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .. import paths
from .network import DnsState, Interface

_FILES = (
    "active_if.txt", "active_ip.txt", "gateway.txt", "relay_ip.txt",
    "tunidx.txt", "connected.flag", "dns-mode.txt", "dns-servers.txt",
    "gateway.flag", "tethering.txt", "profile.txt", "chain.txt",
)


# Pending backups outlive clear(). Limit failed recovery calls, not OS retries.
MAX_DNS_ATTEMPTS = 20


@dataclass
class PendingDns:
    dns: DnsState
    attempts: int = 0


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

    def save(self, iface: Interface, server_ip: str, tun_index: int, dns: DnsState,
             profile_uid: str = "", chain_uid: str = "") -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        # Which profile this tunnel was built from. The active profile is only
        # what the UI has selected; without this the window could not tell a
        # click on another server from the server actually carrying traffic.
        if profile_uid:
            self._write("profile.txt", profile_uid)
        else:
            self._p("profile.txt").unlink(missing_ok=True)
        if chain_uid:
            self._write("chain.txt", chain_uid)
        else:
            self._p("chain.txt").unlink(missing_ok=True)
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
    def profile_uid(self) -> str | None:
        return self._read("profile.txt") or None

    @property
    def chain_uid(self) -> str | None:
        return self._read("chain.txt") or None

    @property
    def tun_index(self) -> int | None:
        v = self._read("tunidx.txt")
        return int(v) if v.isdigit() else None

    def dns_state(self) -> DnsState:
        mode = self._read("dns-mode.txt") or "DHCP"
        sp = self._p("dns-servers.txt")
        lines = sp.read_text(encoding="utf-8").splitlines() if sp.exists() else []
        if mode != "FILE":
            lines = [ln.strip() for ln in lines if ln.strip()]
        # FILE holds /etc/resolv.conf verbatim, one line per entry. Splitting
        # it on whitespace restored "nameserver\n1.1.1.1", a resolv.conf glibc
        # cannot parse: no DNS at all after disconnect.
        return DnsState(mode=mode, servers=lines)

    def update_gateway(self, gateway: str) -> None:
        self._write("gateway.txt", gateway)

    def set_gateway(self, on: bool) -> None:
        if on:
            self._write("gateway.flag", "1")
        else:
            self._p("gateway.flag").unlink(missing_ok=True)

    def gateway_on(self) -> bool:
        return self._p("gateway.flag").exists()

    def set_tethering(self, how: str) -> None:
        """What sushTun did to the Windows hotspot: "started" it, "moved" the
        user's own one onto the tunnel, or "" for nothing. Kept on disk so a
        restarted app or the crash recovery can still undo exactly that."""
        if how:
            self._write("tethering.txt", how)
        else:
            self._p("tethering.txt").unlink(missing_ok=True)

    def tethering(self) -> str:
        return self._read("tethering.txt")

    # Not in _FILES: it describes Windows' hotspot, which outlives a connection.
    def hotspot_pushed(self) -> str:
        return self._read("hotspot_pushed.txt")

    def set_hotspot_pushed(self, digest: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._write("hotspot_pushed.txt", digest)

    def pending(self) -> dict[str, PendingDns]:
        try:
            data = json.loads(self._p("dns-pending.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        result = {}
        for alias, entry in data.items():
            try:
                dns = entry["dns"]
                attempts = entry["attempts"]
                if (not alias or not isinstance(dns["mode"], str)
                        or not isinstance(dns["servers"], list)
                        or not all(isinstance(s, str) for s in dns["servers"])
                        or not isinstance(attempts, int) or attempts < 0):
                    continue
                result[alias] = PendingDns(DnsState(**dns), attempts)
            except (KeyError, TypeError):
                continue
        return result

    def _write_pending(self, entries: dict[str, PendingDns]) -> None:
        target = self._p("dns-pending.json")
        if not entries:
            target.unlink(missing_ok=True)
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps({a: asdict(p) for a, p in entries.items()}),
                             encoding="utf-8")
        temporary.replace(target)

    def save_pending(self, alias: str, dns: DnsState, attempts: int | None = None) -> None:
        entries = self.pending()
        old = entries.get(alias)
        entries[alias] = PendingDns(dns, (old.attempts if old else 0)
                                    if attempts is None else attempts)
        self._write_pending(entries)

    def clear_pending(self, alias: str) -> None:
        entries = self.pending()
        entries.pop(alias, None)
        self._write_pending(entries)

    def clear(self) -> None:
        for name in _FILES:
            self._p(name).unlink(missing_ok=True)
