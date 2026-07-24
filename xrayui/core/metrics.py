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
