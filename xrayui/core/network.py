"""Windows network orchestration: interface detection, DNS, routes, TUN."""
from __future__ import annotations

import ipaddress
import sys
import time
from dataclasses import dataclass, field

from . import proc

TUN_NAME = "xray0"
WG_TUN_NAME = "sushTun"

_DETECT_PS = """
$candidate = $null
foreach ($route in (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction SilentlyContinue)) {
  if ($route.NextHop -eq '0.0.0.0' -or $route.NextHop -eq '::' -or $route.InterfaceAlias -eq 'xray0' -or $route.InterfaceAlias -eq 'sushTun') { continue }
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


def _flush_dns() -> None:
    proc.run(["ipconfig", "/flushdns"])


def add_routes(server_ip: str, gateway: str, tun_index: int) -> None:
    proc.run(["route", "add", server_ip, "mask", "255.255.255.255", gateway, "metric", "1"])
    proc.run(["route", "add", "0.0.0.0", "mask", "0.0.0.0", "0.0.0.0",
              "if", str(tun_index), "metric", "3"])


def replace_host_route(server_ip: str, gateway: str) -> None:
    """Repoint the host route to the server after the default gateway changes.

    Leaves the tun default route alone — only the pinned host route goes stale
    when Wi-Fi renews its lease or roams, so only it needs refreshing.
    """
    proc.run(["route", "delete", server_ip, "mask", "255.255.255.255"])
    proc.run(["route", "add", server_ip, "mask", "255.255.255.255", gateway, "metric", "1"])


def remove_routes(server_ip: str | None = None) -> None:
    proc.run(["route", "delete", "0.0.0.0", "mask", "0.0.0.0", "0.0.0.0"])
    if server_ip:
        proc.run(["route", "delete", server_ip, "mask", "255.255.255.255"])


def add_host_route(ip: str, gateway: str) -> None:
    """Pin a single host through the physical gateway (same pattern as the
    Xray server route) — used to keep a WireGuard endpoint off its own tunnel."""
    proc.run(["route", "add", ip, "mask", "255.255.255.255", gateway, "metric", "1"])


def remove_host_route(ip: str) -> None:
    proc.run(["route", "delete", ip, "mask", "255.255.255.255"])


def _is_ipv6(prefix: str) -> bool:
    return ":" in prefix.split("/")[0]


def add_prefix_route(prefix: str, tun_index: int) -> None:
    """Add a route for one AllowedIPs prefix via the WireGuard adapter."""
    if _is_ipv6(prefix):
        proc.run(["netsh", "interface", "ipv6", "add", "route", prefix,
                  f"interface={tun_index}", "store=active"])
    else:
        net = ipaddress.ip_network(prefix, strict=False)
        proc.run(["route", "add", str(net.network_address), "mask", str(net.netmask),
                  "0.0.0.0", "if", str(tun_index), "metric", "5"])


def remove_prefix_route(prefix: str, tun_index: int) -> None:
    if _is_ipv6(prefix):
        proc.run(["netsh", "interface", "ipv6", "delete", "route", prefix,
                  f"interface={tun_index}"])
    else:
        net = ipaddress.ip_network(prefix, strict=False)
        proc.run(["route", "delete", str(net.network_address), "mask", str(net.netmask)])


def wait_for_tun(name: str = TUN_NAME, timeout: float = 30.0) -> int | None:
    script = f"(Get-NetAdapter -Name '{name}' -ErrorAction SilentlyContinue).ifIndex"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for ln in proc.ps_lines(script):
            if ln.isdigit():
                return int(ln)
        time.sleep(1.0)
    return None


# On Linux/macOS, swap the Windows implementations for the POSIX backend.
# The Windows code above is left untouched and never runs off-Windows.
if sys.platform != "win32":
    from . import _net_posix as _posix

    detect_interface = _posix.detect_interface
    backup_dns = _posix.backup_dns
    set_dns_loopback = _posix.set_dns_loopback
    restore_dns = _posix.restore_dns
    add_routes = _posix.add_routes
    remove_routes = _posix.remove_routes
    wait_for_tun = _posix.wait_for_tun
    add_host_route = _posix.add_host_route
    remove_host_route = _posix.remove_host_route
    add_prefix_route = _posix.add_prefix_route
    remove_prefix_route = _posix.remove_prefix_route
