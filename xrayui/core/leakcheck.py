"""Leak check: prove the tunnel is really carrying the traffic.

The whole point of sushTun is that the user's real IP must never reach a
service by accident. This module verifies, while connected, that the exit a
website actually sees is the tunnel's exit and not the machine's own address:

* the tunnel exit is probed with the same Cloudflare trace the app already
  uses (geo_exit), so no new third-party endpoint is introduced;
* the machine's real public IP is probed once, out the physical interface
  (a throwaway Xray pinned to the NIC, the same trick speedtest uses), cached,
  and never logged in full -- only a masked a.b.*.* form is ever exposed.

The DNS/IPv6 audit is read-only: it lists resolvers and IPv6 default routes
that still sit outside the tunnel and reports them as *potential* leaks. It
never changes system state.

Everything here is Qt-free and English; the UI translates the message strings
later. Failures degrade to UNKNOWN / empty results and never raise, so an
optional check can never break the main connection.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

from .. import paths
from . import geo_exit, proc

# -- verdict -----------------------------------------------------------------
OK = "ok"
EXIT_IS_IRAN = "exit_is_iran"
IP_MATCHES_REAL = "ip_matches_real"
UNKNOWN = "unknown"

# Fixed English messages; the UI translates these (they double as the alert
# templates, so there is one source of truth for the wording).
MSG_OK = "Traffic is leaving through the tunnel."
MSG_EXIT_IRAN = "The tunnel exit is in Iran — your real location is exposed."
MSG_IP_REAL = ("The tunnel exit matches your real IP — traffic is not going "
               "through the tunnel.")
MSG_UNKNOWN = "Could not verify the tunnel exit."

_MESSAGES = {
    OK: MSG_OK,
    EXIT_IS_IRAN: MSG_EXIT_IRAN,
    IP_MATCHES_REAL: MSG_IP_REAL,
    UNKNOWN: MSG_UNKNOWN,
}

_STATUS_LABELS = {
    OK: "protected",
    EXIT_IS_IRAN: "exit is Iran",
    IP_MATCHES_REAL: "exit is your real IP",
    UNKNOWN: "unknown",
}


@dataclass(frozen=True)
class Verdict:
    status: str  # one of OK / EXIT_IS_IRAN / IP_MATCHES_REAL / UNKNOWN
    exit_country: str | None = None
    exit_ip: str | None = None
    real_ip_masked: str | None = None
    detail: str = ""


def mask_ip(ip: str | None) -> str | None:
    """A form of `ip` safe to log or show: a.b.*.* for IPv4.

    The real public IP is sensitive, so only the first two octets survive.
    An unrecognised value is refused (None) rather than shown whole.
    """
    if not ip:
        return None
    ip = ip.strip()
    if ":" in ip:  # IPv6: keep the first two hextets (32 bits)
        hextets = ip.split(":")
        if len(hextets) >= 2:
            return f"{hextets[0]}:{hextets[1]}::"
        return "::"
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{parts[1]}.*.*"
    return None


def check(exit_info: geo_exit.ExitInfo | None, real_ip: str | None) -> Verdict:
    """Pure: turn a tunnel-exit probe and the real IP into a verdict.

    `exit_info` is a geo_exit.ExitInfo, or None if the tunnel probe failed.
    `real_ip` is the machine's real public IP, or None if unknown. A failed
    probe is always UNKNOWN -- never OK.
    """
    masked = mask_ip(real_ip)
    if exit_info is None:
        return Verdict(UNKNOWN, real_ip_masked=masked,
                       detail="the tunnel exit probe failed")
    if exit_info.country == "ir":
        return Verdict(EXIT_IS_IRAN, exit_country=exit_info.country,
                       exit_ip=exit_info.ip, real_ip_masked=masked)
    if real_ip and exit_info.ip and exit_info.ip == real_ip:
        return Verdict(IP_MATCHES_REAL, exit_country=exit_info.country,
                       exit_ip=exit_info.ip, real_ip_masked=masked)
    return Verdict(OK, exit_country=exit_info.country,
                   exit_ip=exit_info.ip, real_ip_masked=masked)


def is_active(verdict: Verdict) -> bool:
    """True if the tunnel is actually protecting (a real foreign exit)."""
    return verdict.status == OK


def status(verdict: Verdict) -> str:
    """A short, stable status label for the UI."""
    return _STATUS_LABELS.get(verdict.status, _STATUS_LABELS[UNKNOWN])


def message(verdict: Verdict) -> str:
    """A one-line English explanation (the UI translates it)."""
    return _MESSAGES.get(verdict.status, _MESSAGES[UNKNOWN])


# -- real public IP probe ----------------------------------------------------
def build_probe_config(port: int, iface_alias: str) -> dict:
    """A throwaway Xray config: one HTTP inbound + a freedom outbound pinned
    to the physical interface, so the probe leaves the machine directly and
    bypasses the tunnel. The same trick speedtest.build_test_config uses.
    """
    cfg = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {"tag": "in-probe", "listen": "127.0.0.1", "port": port,
             "protocol": "http", "settings": {}},
        ],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom", "settings": {},
             "sockopt": {"interface": "__IFACE__"}},
        ],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": [
            {"type": "field", "inboundTag": ["in-probe"], "outboundTag": "direct"},
        ]},
    }
    # Substitute after serializing, as render/speedtest do, so the placeholder
    # is replaced in one pass.
    return json.loads(json.dumps(cfg).replace("__IFACE__", iface_alias))


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _wait_port(port: int, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.05)
    return False


def _run_real_ip_probe(iface_alias: str, timeout: float = 10.0) -> str | None:
    """The machine's real public IP, probed out the physical interface so it
    bypasses the tunnel. None on any failure. The full IP is only ever held in
    memory here; callers expose the masked form.
    """
    if not iface_alias:
        return None
    port = _free_port()
    paths.state_dir().mkdir(parents=True, exist_ok=True)
    config_path = paths.state_dir() / "leakcheck-probe.json"
    log_path = paths.state_dir() / "leakcheck-probe.log"
    config_path.write_text(json.dumps(build_probe_config(port, iface_alias)),
                           encoding="utf-8")
    env = proc.child_env({"XRAY_LOCATION_ASSET": str(paths.asset_dir())})
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        popen = subprocess.Popen(
            [str(paths.xray_exe()), "run", "-c", str(config_path)],
            stdout=log, stderr=subprocess.STDOUT, cwd=str(paths.base_dir()),
            env=env, creationflags=proc.CREATE_NO_WINDOW,
            startupinfo=proc._startupinfo(),
        )
        try:
            if not _wait_port(port, time.monotonic() + timeout):
                return None
            info = geo_exit.detect(f"http://127.0.0.1:{port}", timeout)
            return info.ip if info and info.ip else None
        finally:
            popen.terminate()
            try:
                popen.wait(timeout=3)
            except subprocess.TimeoutExpired:
                popen.kill()
                try:
                    popen.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass  # unreapable; the probe result is already decided


class RealIpCache:
    """The machine's real public IP, probed once and cached in memory.

    The full IP is never written to a file or a log; only the masked form is
    exposed. A failed probe is not cached, so a later check retries.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ip: str | None = None

    def get(self, probe) -> str | None:
        with self._lock:
            if self._ip is not None:
                return self._ip
        ip = probe()
        if ip:
            with self._lock:
                if self._ip is None:
                    self._ip = ip
        return ip

    def clear(self) -> None:
        with self._lock:
            self._ip = None


def run_check(exit_opener, iface_alias: str, real_ip_cache: RealIpCache,
              timeout: float = 8.0) -> Verdict:
    """Run the leak check: probe the tunnel exit and the real IP, return a
    Verdict. `exit_opener` is whatever geo_exit.detect accepts for the tunnel
    (None for a direct request through the system route, which is the tunnel
    while connected). Never raises.
    """
    try:
        exit_info = geo_exit.detect(exit_opener, timeout)
    except Exception:
        exit_info = None
    try:
        real_ip = real_ip_cache.get(
            lambda: _run_real_ip_probe(iface_alias, timeout))
    except Exception:
        real_ip = None
    return check(exit_info, real_ip)


# -- DNS / IPv6 audit (read-only) -------------------------------------------
@dataclass(frozen=True)
class ResolverEntry:
    name: str  # link / adapter / service / resolver name
    servers: tuple[str, ...]


@dataclass(frozen=True)
class DnsAudit:
    entries: tuple[ResolverEntry, ...]
    leaks: tuple[ResolverEntry, ...]


@dataclass(frozen=True)
class Ipv6Audit:
    devices: tuple[str, ...]  # interfaces carrying an IPv6 default route
    leaks: tuple[str, ...]    # the ones that are not the tunnel


def _ip_literal(token: str) -> str | None:
    # resolvectl appends "#server-name" (SNI) and "%scope" (link-local zone).
    word = token.split("#", 1)[0].split("%", 1)[0]
    try:
        ipaddress.ip_address(word)
    except ValueError:
        return None
    return word


def parse_resolvectl_dns_audit(text: str) -> list[ResolverEntry]:
    """(link, resolvers) from `resolvectl dns`, e.g.
    "Global: 1.1.1.1" and "Link 2 (eth0): 192.168.1.1"."""
    entries: list[ResolverEntry] = []
    for line in text.splitlines():
        m = re.match(r"^\s*(Global|Link \d+ \([^)]+\)):\s*(.*)$", line)
        if not m:
            continue
        name = m.group(1).strip()
        if name.startswith("Link"):
            name = name.split("(", 1)[1].rstrip(")").strip()
        seen: list[str] = []
        for ip in map(_ip_literal, m.group(2).split()):
            if ip and ip not in seen:
                seen.append(ip)
        if seen:
            entries.append(ResolverEntry(name, tuple(seen)))
    return entries


def parse_scutil_dns_audit(text: str) -> list[ResolverEntry]:
    """(resolver, nameservers) from `scutil --dns`, the effective resolver
    order. Blocks with no usable nameserver (mdns, etc.) are skipped."""
    entries: list[ResolverEntry] = []
    name = ""
    servers: list[str] = []
    for line in text.splitlines():
        head = line.strip()
        if head.startswith("resolver #"):
            if name and servers:
                entries.append(ResolverEntry(name, tuple(servers)))
            name = head.split()[-1].lstrip("#")
            servers = []
            continue
        m = re.match(r"\s*nameserver\[\d+\]\s*:\s*(\S+)", line)
        if m and name:
            ip = _ip_literal(m.group(1))
            if ip and ip not in servers:
                servers.append(ip)
    if name and servers:
        entries.append(ResolverEntry(name, tuple(servers)))
    return entries


def parse_getdnscclient_dns_audit(text: str) -> list[ResolverEntry]:
    """(adapter, resolvers) from `Get-DnsClientServerAddress`, whose table
    shows the address collection as "{a, b}". The alias may contain spaces,
    so it is everything before the first "{"."""
    entries: list[ResolverEntry] = []
    for line in text.splitlines():
        if "{" not in line or "}" not in line:
            continue
        alias, rest = line.split("{", 1)
        alias = alias.strip()
        if not alias or alias.lower() == "interfacealias":
            continue
        servers_part = rest.split("}", 1)[0]
        seen: list[str] = []
        for w in servers_part.split(","):
            ip = _ip_literal(w.strip())
            if ip and ip not in seen:
                seen.append(ip)
        if seen:
            entries.append(ResolverEntry(alias, tuple(seen)))
    return entries


def dns_leaks(entries: list[ResolverEntry], tunnel_servers: set[str]) -> list[ResolverEntry]:
    """Entries holding a resolver that is not the tunnel's own: potential DNS
    leaks. `tunnel_servers` is the set of addresses that belong to the tunnel
    (127.0.0.1, the tunnel's own DNS); loopback is always allowed. An entry is
    a leak if it has at least one server outside that set."""
    allowed = set(tunnel_servers) | {"127.0.0.1"}
    return [e for e in entries
            if any(s not in allowed for s in e.servers)]


# -- IPv6 default-route audit ------------------------------------------------
def parse_ipv6_default_linux(text: str) -> list[str]:
    """Devices carrying an IPv6 default route, from `ip -6 route`
    ("default via fe80::1 dev eth0 ...")."""
    devs: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("default"):
            continue
        m = re.search(r"\bdev\s+(\S+)", line)
        if m and m.group(1) not in devs:
            devs.append(m.group(1))
    return devs


def parse_ipv6_default_macos(text: str) -> list[str]:
    """Interfaces carrying an IPv6 default route, from `netstat -rn -f inet6`
    (columns: Destination Gateway Flags Netif Expire)."""
    devs: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "default":
            dev = parts[3]
            if dev not in devs:
                devs.append(dev)
    return devs


def parse_ipv6_default_windows(text: str) -> list[str]:
    """Interface indices (as strings) carrying an IPv6 default route, from
    `route print -6`. The Interface column is an index, not a name, so the
    caller compares against the tunnel adapter's index."""
    devs: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        # If Metric Network Destination Gateway -- the data rows have four
        # fields; the header ("If Metric Network Destination Gateway") has
        # five and never matches the ::/0 test.
        if len(parts) >= 4 and parts[2] == "::/0" and parts[0].isdigit():
            if parts[0] not in devs:
                devs.append(parts[0])
    return devs


def ipv6_leak(devices: list[str], tunnel_devices: set[str]) -> list[str]:
    """The non-tunnel interfaces that carry an IPv6 default route, if any.
    Empty means no IPv6 leak (no default route, or only the tunnel's)."""
    tunnel = set(tunnel_devices)
    return [d for d in devices if d not in tunnel]


# -- audit orchestration (read-only) -----------------------------------------
_TUNNEL_DNS = "172.19.0.1"  # the resolver systemd-resolved is given on xray0


def _dns_audit_text() -> str:
    if sys.platform == "win32":
        script = ("Get-DnsClientServerAddress -AddressFamily IPv4 "
                  "-ErrorAction SilentlyContinue")
        try:
            return proc.powershell(script, timeout=10).stdout
        except (subprocess.TimeoutExpired, OSError):
            return ""
    if sys.platform == "darwin":
        try:
            return proc.run(["scutil", "--dns"], timeout=10).stdout
        except (subprocess.TimeoutExpired, OSError):
            return ""
    try:
        return proc.run(["resolvectl", "dns"], timeout=10).stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def run_dns_audit() -> DnsAudit:
    """Read the configured resolvers and flag the ones outside the tunnel.
    Read-only; never raises."""
    try:
        entries = _parse_dns(_dns_audit_text())
        leaks = dns_leaks(entries, {"127.0.0.1", _TUNNEL_DNS})
    except Exception:
        entries, leaks = [], []
    return DnsAudit(tuple(entries), tuple(leaks))


def _parse_dns(text: str) -> list[ResolverEntry]:
    if sys.platform == "win32":
        return parse_getdnscclient_dns_audit(text)
    if sys.platform == "darwin":
        return parse_scutil_dns_audit(text)
    return parse_resolvectl_dns_audit(text)


def _ipv6_route_text() -> str:
    if sys.platform == "win32":
        try:
            return proc.run(["route", "print", "-6"], timeout=10).stdout
        except (subprocess.TimeoutExpired, OSError):
            return ""
    if sys.platform == "darwin":
        try:
            return proc.run(["netstat", "-rn", "-f", "inet6"], timeout=10).stdout
        except (subprocess.TimeoutExpired, OSError):
            return ""
    try:
        return proc.run(["ip", "-6", "route"], timeout=10).stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _parse_ipv6(text: str) -> list[str]:
    if sys.platform == "win32":
        return parse_ipv6_default_windows(text)
    if sys.platform == "darwin":
        return parse_ipv6_default_macos(text)
    return parse_ipv6_default_linux(text)


def _default_tunnel_devices() -> set[str]:
    if sys.platform == "darwin":
        from . import tun2socks
        return {tun2socks.DEVICE}
    if sys.platform != "win32":
        from ._net_common import TUN_NAME
        return {TUN_NAME}
    return set()  # Windows: the caller passes the tunnel adapter's index


def run_ipv6_audit(tunnel_devices: set[str] | None = None) -> Ipv6Audit:
    """Read the IPv6 default routes and flag the ones outside the tunnel.
    Read-only; never raises. Pass the tunnel device(s) when known (the macOS
    native utun and the Windows TUN index are not fixed)."""
    tunnel = set(tunnel_devices) if tunnel_devices is not None \
        else _default_tunnel_devices()
    try:
        devices = _parse_ipv6(_ipv6_route_text())
        leaks = ipv6_leak(devices, tunnel)
    except Exception:
        devices, leaks = [], []
    return Ipv6Audit(tuple(devices), tuple(leaks))
