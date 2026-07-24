"""EXPERIMENTAL Linux/macOS network backend (unverified on this build).

Mirrors the Windows network interface using ip/route/networksetup. Not yet
tested end-to-end; the connect path on these platforms may need iteration.
"""
from __future__ import annotations

import json
import sys
import time

from . import proc
from .network import TUN_NAME, DnsState, Interface

IS_MAC = sys.platform == "darwin"
_RESOLV = "/etc/resolv.conf"


# -- interface detection ---------------------------------------------------
def _linux_detect() -> Interface | None:
    routes = json.loads(proc.run(["ip", "-j", "route", "show", "default"]).stdout or "[]")
    routes = [r for r in routes if r.get("dev") != TUN_NAME and r.get("gateway")]
    if not routes:
        return None
    r = routes[0]
    dev, gw = r["dev"], r["gateway"]
    ip = ""
    addrs = json.loads(proc.run(["ip", "-j", "-4", "addr", "show", "dev", dev]).stdout or "[]")
    for entry in addrs:
        for info in entry.get("addr_info", []):
            if info.get("family") == "inet":
                ip = info["local"]
                break
    return Interface(dev, ip, gw, None)


def _mac_detect() -> Interface | None:
    out = proc.run(["route", "-n", "get", "default"]).stdout
    gw = dev = ""
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("gateway:"):
            gw = line.split(":", 1)[1].strip()
        elif line.startswith("interface:"):
            dev = line.split(":", 1)[1].strip()
    if not (dev and gw):
        return None
    ip = proc.run(["ipconfig", "getifaddr", dev]).stdout.strip()
    return Interface(dev, ip, gw, None)


def detect_interface() -> Interface | None:
    return _mac_detect() if IS_MAC else _linux_detect()


# -- DNS -------------------------------------------------------------------
def _mac_service(dev: str) -> str | None:
    out = proc.run(["networksetup", "-listnetworkserviceorder"]).stdout
    service = None
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("(") and ")" in stripped and "Hardware Port" not in stripped:
            service = stripped.split(")", 1)[1].strip()
        elif f"Device: {dev})" in stripped:
            return service
    return None


def backup_dns(alias: str) -> DnsState:
    if IS_MAC:
        service = _mac_service(alias) or ""
        current = proc.run(["networksetup", "-getdnsservers", service]).stdout.split()
        servers = [] if (not current or "aren't" in " ".join(current)) else current
        return DnsState(mode="MACOS", servers=[service, *servers])
    try:
        with open(_RESOLV, encoding="utf-8") as f:
            return DnsState(mode="FILE", servers=f.read().splitlines())
    except OSError:
        return DnsState(mode="FILE", servers=[])


def set_dns_loopback(alias: str) -> None:
    if IS_MAC:
        service = _mac_service(alias)
        if service:
            proc.run(["networksetup", "-setdnsservers", service, "127.0.0.1"])
        return
    with open(_RESOLV, "w", encoding="utf-8") as f:
        f.write("nameserver 127.0.0.1\n")


def restore_dns(alias: str, state: DnsState) -> bool:
    if state.mode == "MACOS":
        service = state.servers[0] if state.servers else _mac_service(alias)
        rest = state.servers[1:] or ["empty"]
        if service:
            proc.run(["networksetup", "-setdnsservers", service, *rest])
        return True
    try:
        with open(_RESOLV, "w", encoding="utf-8") as f:
            f.write("\n".join(state.servers) + "\n")
        return True
    except OSError:
        return False


# -- routes ----------------------------------------------------------------
def add_routes(server_ip: str, gateway: str, tun_index: int) -> None:
    if IS_MAC:
        proc.run(["route", "-n", "add", "-host", server_ip, gateway])
        proc.run(["route", "-n", "add", "-net", "0.0.0.0/1", "-interface", TUN_NAME])
        proc.run(["route", "-n", "add", "-net", "128.0.0.0/1", "-interface", TUN_NAME])
    else:
        proc.run(["ip", "route", "add", server_ip, "via", gateway])
        proc.run(["ip", "route", "add", "default", "dev", TUN_NAME])


def remove_routes(server_ip: str | None = None) -> None:
    if IS_MAC:
        proc.run(["route", "-n", "delete", "-net", "0.0.0.0/1", "-interface", TUN_NAME])
        proc.run(["route", "-n", "delete", "-net", "128.0.0.0/1", "-interface", TUN_NAME])
        if server_ip:
            proc.run(["route", "-n", "delete", "-host", server_ip])
    else:
        proc.run(["ip", "route", "del", "default", "dev", TUN_NAME])
        if server_ip:
            proc.run(["ip", "route", "del", server_ip])


def wait_for_tun(name: str = TUN_NAME, timeout: float = 30.0) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if IS_MAC:
            # macOS assigns utunN dynamically; treat any utun as the tunnel.
            if "utun" in proc.run(["ifconfig", "-l"]).stdout:
                return 0
        else:
            links = json.loads(proc.run(["ip", "-j", "link", "show", name]).stdout or "[]")
            if links:
                return links[0].get("ifindex", 0)
        time.sleep(1.0)
    return None
