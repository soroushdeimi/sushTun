"""Read-only measurements: ping, TCP delay, tunnel throughput, diagnostics."""
from __future__ import annotations

import json
import socket
import sys
import time

from .. import paths
from . import proc

STATS_API_PORT = 10085
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

_THROUGHPUT_PS = """
$idx = [int]$env:IDX; $sec = [int]$env:SECS
$a = Get-NetAdapter -InterfaceIndex $idx -ErrorAction Stop
$s1 = Get-NetAdapterStatistics -Name $a.Name -ErrorAction Stop
Start-Sleep -Seconds $sec
$s2 = Get-NetAdapterStatistics -Name $a.Name -ErrorAction Stop
$rx = [math]::Max(0, $s2.ReceivedBytes - $s1.ReceivedBytes)
$tx = [math]::Max(0, $s2.SentBytes - $s1.SentBytes)
@{ name = $a.Name; rx = $rx; tx = $tx;
   rx_mbps = [math]::Round((($rx * 8) / $sec) / 1MB, 2);
   tx_mbps = [math]::Round((($tx * 8) / $sec) / 1MB, 2) } | ConvertTo-Json -Compress
"""


def ping(target: str, count: int = 4) -> str:
    if IS_WIN:
        args = ["ping", "-4", "-n", str(count), target]
    elif IS_MAC:
        args = ["ping", "-c", str(count), target]
    else:
        args = ["ping", "-4", "-c", str(count), target]
    return proc.run(args, timeout=count * 3 + 5).stdout


def tcp_connect_delay(host: str, port: int, attempts: int = 3, timeout: float = 3.0) -> dict:
    results: list[float | None] = []
    for _ in range(attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        start = time.perf_counter()
        try:
            s.connect((host, int(port)))
            results.append((time.perf_counter() - start) * 1000)
        except OSError:
            results.append(None)
        finally:
            s.close()
        time.sleep(0.25)
    ok = [r for r in results if r is not None]
    return {
        "results": results,
        "avg": sum(ok) / len(ok) if ok else None,
        "min": min(ok) if ok else None,
        "max": max(ok) if ok else None,
    }


def throughput_sample(tun_index: int, seconds: int = 5) -> dict | None:
    if not IS_WIN:
        return None  # Get-NetAdapterStatistics has no Linux/macOS equivalent here
    out = proc.powershell(
        _THROUGHPUT_PS, env={"IDX": tun_index, "SECS": seconds}, timeout=seconds + 10
    ).stdout.strip()
    try:
        return json.loads(out)
    except ValueError:
        return None


_BASELINE_PS = """
$tun = [int]$env:TUN_IDX; $sec = [int]$env:SECS; $alias = $env:PHYS_ALIAS
$ta = Get-NetAdapter -InterfaceIndex $tun -ErrorAction Stop
$pa = Get-NetAdapter -Name $alias -ErrorAction SilentlyContinue
function Cpu { (Get-Process xray -ErrorAction SilentlyContinue |
                 Measure-Object -Property CPU -Sum).Sum }
$t1 = Get-NetAdapterStatistics -Name $ta.Name -ErrorAction Stop
$p1 = if ($pa) { Get-NetAdapterStatistics -Name $pa.Name -ErrorAction SilentlyContinue }
$c1 = Cpu
Start-Sleep -Seconds $sec
$t2 = Get-NetAdapterStatistics -Name $ta.Name -ErrorAction Stop
$p2 = if ($pa) { Get-NetAdapterStatistics -Name $pa.Name -ErrorAction SilentlyContinue }
$c2 = Cpu
function Mbps($a, $b) { [math]::Round((([math]::Max(0, $b - $a) * 8) / $sec) / 1MB, 2) }
@{
  tun_name     = $ta.Name
  tun_rx_mbps  = Mbps $t1.ReceivedBytes $t2.ReceivedBytes
  tun_tx_mbps  = Mbps $t1.SentBytes     $t2.SentBytes
  phys_name    = if ($pa) { $pa.Name } else { '' }
  phys_rx_mbps = if ($p1 -and $p2) { Mbps $p1.ReceivedBytes $p2.ReceivedBytes } else { 0 }
  phys_tx_mbps = if ($p1 -and $p2) { Mbps $p1.SentBytes     $p2.SentBytes } else { 0 }
  xray_cpu_pct = [math]::Round(((($c2 - $c1) / $sec) * 100), 1)
  cores        = [Environment]::ProcessorCount
} | ConvertTo-Json -Compress
"""


def baseline_sample(tun_index: int, phys_alias: str | None, seconds: int = 5) -> dict | None:
    """Tunnel and physical throughput plus xray CPU, over one sample window.

    Answers the only question worth asking before tuning anything: CPU near
    100% of a core means the userspace TCP stack is the ceiling; low CPU with
    tunnel throughput tracking the physical adapter means the WAN link is.
    """
    if not IS_WIN:
        return None
    out = proc.powershell(
        _BASELINE_PS,
        env={"TUN_IDX": tun_index, "SECS": seconds, "PHYS_ALIAS": phys_alias or ""},
        timeout=seconds + 20,
    ).stdout.strip()
    try:
        return json.loads(out)
    except ValueError:
        return None


def format_baseline(s: dict) -> str:
    cpu = float(s.get("xray_cpu_pct") or 0.0)
    rx, tx = s.get("tun_rx_mbps") or 0, s.get("tun_tx_mbps") or 0
    lines = [f"Tunnel   {s.get('tun_name', '?'):<22} "
             f"RX ~{rx} Mbit/s   TX ~{tx} Mbit/s"]
    if s.get("phys_name"):
        lines.append(f"Physical {s['phys_name']:<22} "
                     f"RX ~{s.get('phys_rx_mbps') or 0} Mbit/s   "
                     f"TX ~{s.get('phys_tx_mbps') or 0} Mbit/s")
    lines.append(f"\nxray CPU {cpu}% of one core ({s.get('cores') or 1} cores)\n")
    if rx < 1 and tx < 1:
        lines.append("Almost no traffic during the sample — start a download and retry.")
    elif cpu >= 80:
        lines.append("CPU-bound: the userspace TCP stack is the ceiling. MTU tuning and")
        lines.append("the kernel-level track would have a real payoff here.")
    else:
        lines.append("Not CPU-bound: the WAN link to the server is the ceiling, so there")
        lines.append("is nothing on the client side worth optimizing.")
    return "\n".join(lines)


def query_stats(port: int = STATS_API_PORT) -> dict | None:
    """Total inbound traffic since connect, via the Xray stats API. up/down bytes."""
    out = proc.run(
        [str(paths.xray_exe()), "api", "statsquery", f"--server=127.0.0.1:{port}"],
        timeout=5,
    ).stdout.strip()
    try:
        data = json.loads(out)
    except ValueError:
        return None
    up = down = 0
    for s in data.get("stat") or []:
        name = s.get("name", "")
        value = int(s.get("value", 0) or 0)
        if not name.startswith("inbound>>>"):
            continue
        if name.endswith(">>>uplink"):
            up += value
        elif name.endswith(">>>downlink"):
            down += value
    return {"up": up, "down": down}


def diagnostics(server_ip: str | None, alias: str | None, tun_index: int | None) -> str:
    parts: list[str] = []
    if server_ip:
        parts.append("--- Relay ping ---")
        parts.append(ping(server_ip, 2))
    if alias:
        parts.append(f"--- DNS on {alias} ---")
        parts.append(_dns_diagnostics(alias))
    if server_ip:
        parts.append("--- Relay route ---")
        parts.append(_route_diagnostics(server_ip))
    if tun_index is not None:
        parts.append("--- Tunnel interface ---")
        parts.append(_tun_diagnostics())
    parts.append("--- Last log lines ---")
    parts.append(_tail_log(8))
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _dns_diagnostics(alias: str) -> str:
    if IS_WIN:
        return proc.run(["netsh", "interface", "ipv4", "show", "dnsservers",
                         f"name={alias}"]).stdout
    if IS_MAC:
        from ._net_posix import mac_service_name
        service = mac_service_name(alias) or alias
        return proc.run(["networksetup", "-getdnsservers", service]).stdout
    return proc.run(["cat", "/etc/resolv.conf"]).stdout


def _route_diagnostics(server_ip: str) -> str:
    if IS_WIN:
        return proc.run(["route", "print", "-4", server_ip]).stdout
    if IS_MAC:
        return proc.run(["route", "-n", "get", server_ip]).stdout
    return proc.run(["ip", "route", "get", server_ip]).stdout


def _tun_diagnostics() -> str:
    if IS_WIN:
        return proc.run(["netsh", "interface", "ipv4", "show", "interfaces"]).stdout
    if IS_MAC:
        from .tun2socks import DEVICE
        return proc.run(["ifconfig", DEVICE]).stdout
    from .network import TUN_NAME
    return proc.run(["ip", "addr", "show", TUN_NAME]).stdout


def _tail_log(n: int) -> str:
    p = paths.log_file()
    if not p.exists():
        return "(no log yet)"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])
