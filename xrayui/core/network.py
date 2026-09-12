"""Windows network orchestration: interface detection, DNS, routes, TUN."""
from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import proc

TUN_NAME = "xray0"

# The TUN adapter must own a global-scope address. Left on DHCP it falls back
# to APIPA (169.254.x.x), and Windows source-address selection then prefers the
# physical adapter's global address for global destinations — so the tunnel's
# default route is never chosen and traffic leaves in the clear.
TUN_ADDRESS = "172.19.0.2"
TUN_NETMASK = "255.255.255.252"
TUN_METRIC = 1

# Two /1 routes beat the physical /0 by longest-prefix match, so the tunnel
# wins regardless of the interface metrics Windows hands out.
DEFAULT_SPLIT = (("0.0.0.0", "128.0.0.0"), ("128.0.0.0", "128.0.0.0"))

_DETECT_PS = """
$candidate = $null
foreach ($route in (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction SilentlyContinue)) {
  if ($route.NextHop -eq '0.0.0.0' -or $route.NextHop -eq '::' -or $route.InterfaceAlias -eq 'xray0') { continue }
  if (-not $candidate -or $route.RouteMetric -lt $candidate.RouteMetric) { $candidate = $route }
}
if ($candidate) {
  $cfg = Get-NetIPConfiguration -InterfaceIndex $candidate.InterfaceIndex -ErrorAction SilentlyContinue
  if ($cfg -and $cfg.IPv4Address) {
    '{0}|{1}|{2}|{3}' -f $candidate.InterfaceAlias, $cfg.IPv4Address[0].IPAddress, $candidate.NextHop, $candidate.InterfaceIndex
  }
}
"""

_BACKUP_DNS_PS = """
$alias = $env:ALIAS
$lines = netsh interface ipv4 show dnsservers name="$alias" 2>$null
$mode = 'DHCP'
$servers = New-Object System.Collections.Generic.List[string]
foreach ($line in $lines) {
  if ($line -match 'DNS servers configured through DHCP:\\s*(.*)$') { $mode = 'DHCP'; $v = $matches[1].Trim(); if ($v -and $v -ne 'None') { [void]$servers.Add($v) }; continue }
  if ($line -match 'Statically Configured DNS Servers:\\s*(.*)$') { $mode = 'STATIC'; $v = $matches[1].Trim(); if ($v -and $v -ne 'None') { [void]$servers.Add($v) }; continue }
  if ($line -match '^\\s+(\\d+\\.\\d+\\.\\d+\\.\\d+)\\s*$') { [void]$servers.Add($matches[1]) }
}
Write-Output $mode
foreach ($s in $servers) { Write-Output $s }
"""


_STRANDED_DNS_PS = """
foreach ($e in Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue) {
  if ($e.ServerAddresses.Count -eq 1 -and $e.ServerAddresses[0] -eq '127.0.0.1') {
    Write-Output $e.InterfaceAlias
  }
}
"""


@dataclass
class Interface:
    alias: str
    ipv4: str
    gateway: str
    index: int | None = None


@dataclass
class DnsState:
    mode: str = "DHCP"  # DHCP | STATIC
    servers: list[str] = field(default_factory=list)


def detect_interface() -> Interface | None:
    for ln in proc.ps_lines(_DETECT_PS):
        parts = ln.split("|")
        if len(parts) >= 3 and parts[0]:
            idx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
            return Interface(parts[0], parts[1], parts[2], idx)
    return None


def backup_dns(alias: str) -> DnsState:
    lines = proc.ps_lines(_BACKUP_DNS_PS, env={"ALIAS": alias})
    if not lines:
        return DnsState()
    mode = lines[0].upper() if lines[0].upper() in ("DHCP", "STATIC") else "DHCP"
    return DnsState(mode=mode, servers=lines[1:])


def set_dns_loopback(alias: str) -> None:
    proc.run(
        ["netsh", "interface", "ipv4", "set", "dnsservers",
         f"name={alias}", "static", "127.0.0.1", "primary", "validate=no"]
    )


def restore_dns(alias: str, state: DnsState, retries: int = 1) -> bool:
    """Put the adapter DNS back. Static 127.0.0.1 survives reboot; this undoes it."""
    delay = 2.0
    for attempt in range(max(1, retries)):
        if _restore_dns_once(alias, state):
            _flush_dns()
            return True
        if attempt + 1 < retries:
            time.sleep(delay)
    return False


def _restore_dns_once(alias: str, state: DnsState) -> bool:
    if state.mode == "STATIC" and state.servers:
        servers = ",".join(f"'{s}'" for s in state.servers)
        script = (
            f"try {{ Set-DnsClientServerAddress -InterfaceAlias $env:ALIAS "
            f"-ServerAddresses @({servers}) -ErrorAction Stop; exit 0 }} catch {{ exit 1 }}"
        )
    else:
        script = (
            "try { Set-DnsClientServerAddress -InterfaceAlias $env:ALIAS "
            "-ResetServerAddresses -ErrorAction Stop; exit 0 } catch { exit 1 }"
        )
    if proc.powershell(script, env={"ALIAS": alias}).returncode == 0:
        return True
    # PowerShell can fail at boot before the adapter is up; netsh is a fallback.
    if state.mode == "STATIC" and state.servers:
        rc = proc.run([
            "netsh", "interface", "ipv4", "set", "dnsservers",
            f"name={alias}", "static", state.servers[0], "primary", "validate=no",
        ]).returncode
        if rc != 0:
            return False
        for i, server in enumerate(state.servers[1:], start=2):
            proc.run([
                "netsh", "interface", "ipv4", "add", "dnsservers",
                f"name={alias}", f"address={server}", f"index={i}", "validate=no",
            ])
        return True
    return proc.run([
        "netsh", "interface", "ipv4", "set", "dnsservers",
        f"name={alias}", "dhcp",
    ]).returncode == 0


def stranded_loopback_adapters(exclude: str | None = None) -> list[str]:
    """Adapters whose only IPv4 resolver is 127.0.0.1.

    A session that never restored leaves its adapter pointing at a resolver
    that dies with the xray process. State records one alias, so an adapter
    stranded by an *older* session is never put back — switch to it and
    Windows reports no internet.
    """
    return [a for a in proc.ps_lines(_STRANDED_DNS_PS) if a and a != exclude]


def release_stranded_dns(exclude: str | None = None) -> list[str]:
    """Reset stranded adapters to DHCP. Returns the aliases actually reset.

    Only adapters whose sole resolver is 127.0.0.1 qualify, and only while
    xray is not running to answer there. DHCP is the safe target: we hold no
    backup for an adapter some earlier session hijacked.
    """
    reset: list[str] = []
    for alias in stranded_loopback_adapters(exclude):
        rc = proc.run(["netsh", "interface", "ipv4", "set", "dnsservers",
                       f"name={alias}", "dhcp"]).returncode
        if rc == 0:
            reset.append(alias)
    if reset:
        _flush_dns()
    return reset


def _flush_dns() -> None:
    proc.run(["ipconfig", "/flushdns"])


def tun_ipv4(index: int) -> str:
    """The adapter's routable IPv4, ignoring an APIPA fallback."""
    script = (
        f"(Get-NetIPAddress -InterfaceIndex {int(index)} -AddressFamily IPv4 "
        f"-ErrorAction SilentlyContinue).IPAddress"
    )
    for ln in proc.ps_lines(script):
        if ln and not ln.startswith("169.254."):
            return ln
    return ""


def configure_tun(index: int, address: str = TUN_ADDRESS, mask: str = TUN_NETMASK) -> bool:
    """Give the TUN adapter a routable address and a low interface metric.

    Addressed by index first (immune to a renamed or localized adapter), then
    by name in case this netsh build will not take an index.

    Returns False when Windows did not take the address. The caller must treat
    that as a failed connect: an APIPA-only tunnel silently carries nothing.
    """
    for target in (str(index), TUN_NAME):
        proc.run(["netsh", "interface", "ipv4", "set", "address",
                  f"name={target}", "static", address, mask])
        proc.run(["netsh", "interface", "ipv4", "set", "interface",
                  f"interface={target}", f"metric={TUN_METRIC}"])
        if tun_ipv4(index) == address:
            return True
    return False


def add_host_route(server_ip: str, gateway: str) -> None:
    """Pin the server route before anything else can default into the tunnel."""
    proc.run(["route", "add", server_ip, "mask", "255.255.255.255", gateway, "metric", "1"])


def add_default_routes(tun_index: int) -> None:
    for dest, mask in DEFAULT_SPLIT:
        proc.run(["route", "add", dest, "mask", mask, "0.0.0.0",
                  "if", str(tun_index), "metric", "1"])


def replace_host_route(server_ip: str, gateway: str) -> None:
    """Repoint the host route to the server after the default gateway changes.

    Leaves the tun default route alone — only the pinned host route goes stale
    when Wi-Fi renews its lease or roams, so only it needs refreshing.
    """
    proc.run(["route", "delete", server_ip, "mask", "255.255.255.255"])
    add_host_route(server_ip, gateway)


def remove_routes(server_ip: str | None = None) -> None:
    # The bare /0 is what releases before the split default installed.
    proc.run(["route", "delete", "0.0.0.0", "mask", "0.0.0.0", "0.0.0.0"])
    for dest, mask in DEFAULT_SPLIT:
        proc.run(["route", "delete", dest, "mask", mask, "0.0.0.0"])
    if server_ip:
        proc.run(["route", "delete", server_ip, "mask", "255.255.255.255"])


def wait_for_tun(name: str = TUN_NAME, timeout: float = 30.0,
                 alive: Callable[[], bool] | None = None) -> int | None:
    """The TUN adapter's index, or None. Gives up early once `alive` says
    xray has exited, rather than waiting out the timeout for nothing."""
    script = f"(Get-NetAdapter -Name '{name}' -ErrorAction SilentlyContinue).ifIndex"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for ln in proc.ps_lines(script):
            if ln.isdigit():
                return int(ln)
        if alive is not None and not alive():
            return None
        time.sleep(1.0)
    return None


def foreign_tunnel(iface: str) -> str | None:
    """Another VPN's device carrying the default traffic. Linux-only check."""
    return None


def repair_tun_dns() -> bool | None:
    """Re-claim DNS cleared by another program. Only resolved (Linux) needs it."""
    return None


# On Linux/macOS, swap the Windows implementations for the POSIX backend.
# The Windows code above is left untouched and never runs off-Windows.
if sys.platform != "win32":
    from . import _net_posix as _posix

    detect_interface = _posix.detect_interface
    backup_dns = _posix.backup_dns
    set_dns_loopback = _posix.set_dns_loopback
    restore_dns = _posix.restore_dns
    stranded_loopback_adapters = _posix.stranded_loopback_adapters
    release_stranded_dns = _posix.release_stranded_dns
    configure_tun = _posix.configure_tun
    add_host_route = _posix.add_host_route
    add_default_routes = _posix.add_default_routes
    remove_routes = _posix.remove_routes
    wait_for_tun = _posix.wait_for_tun
    foreign_tunnel = _posix.foreign_tunnel
    repair_tun_dns = _posix.repair_tun_dns
