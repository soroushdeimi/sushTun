"""Read-only measurements: ping, TCP delay, tunnel throughput, diagnostics."""
from __future__ import annotations

import json
import socket
import time

from .. import paths
from . import proc

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
    return proc.run(["ping", "-4", "-n", str(count), target], timeout=count * 3 + 5).stdout


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
    out = proc.powershell(
        _THROUGHPUT_PS, env={"IDX": tun_index, "SECS": seconds}, timeout=seconds + 10
    ).stdout.strip()
    try:
        return json.loads(out)
    except ValueError:
        return None


def diagnostics(server_ip: str | None, alias: str | None, tun_index: int | None) -> str:
    parts: list[str] = []
    if server_ip:
        parts.append("--- Relay ping ---")
        parts.append(ping(server_ip, 2))
    if alias:
        parts.append(f"--- DNS on {alias} ---")
        parts.append(proc.run(["netsh", "interface", "ipv4", "show", "dnsservers",
                               f"name={alias}"]).stdout)
    if server_ip:
        parts.append("--- Relay route ---")
        parts.append(proc.run(["route", "print", "-4", server_ip]).stdout)
    if tun_index is not None:
        parts.append("--- Tunnel interface ---")
        parts.append(proc.run(["netsh", "interface", "ipv4", "show", "interfaces"]).stdout)
    parts.append("--- Last log lines ---")
    parts.append(_tail_log(8))
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _tail_log(n: int) -> str:
    p = paths.log_file()
    if not p.exists():
        return "(no log yet)"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])
