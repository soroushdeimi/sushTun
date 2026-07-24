"""Windows network orchestration: interface detection, DNS, routes, TUN.

Windows network orchestration.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import proc

TUN_NAME = "xray0"

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


def restore_dns(alias: str, state: DnsState) -> bool:
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
    return proc.powershell(script, env={"ALIAS": alias}).returncode == 0


def add_routes(server_ip: str, gateway: str, tun_index: int) -> None:
    proc.run(["route", "add", server_ip, "mask", "255.255.255.255", gateway, "metric", "1"])
    proc.run(["route", "add", "0.0.0.0", "mask", "0.0.0.0", "0.0.0.0",
              "if", str(tun_index), "metric", "3"])


def remove_routes(server_ip: str | None = None) -> None:
    proc.run(["route", "delete", "0.0.0.0", "mask", "0.0.0.0", "0.0.0.0"])
    if server_ip:
        proc.run(["route", "delete", server_ip, "mask", "255.255.255.255"])


def wait_for_tun(name: str = TUN_NAME, timeout: float = 30.0) -> int | None:
    script = f"(Get-NetAdapter -Name '{name}' -ErrorAction SilentlyContinue).ifIndex"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for ln in proc.ps_lines(script):
            if ln.isdigit():
                return int(ln)
        time.sleep(1.0)
    return None
