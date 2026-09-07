"""EXPERIMENTAL Linux/macOS network backend (unverified on this build).

Linux mirrors the Windows network interface using ip/route (Xray's native TUN
inbound works there). macOS has no native Xray TUN inbound at all, so the
connect path there instead bridges Xray's SOCKS inbound through tun2socks
(see tun2socks.py) — routes and DNS below target that bridge device.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from . import proc
from . import tun2socks as t2s
from .network import TUN_ADDRESS, TUN_NAME, TUN_NETMASK, DnsState, Interface

IS_MAC = sys.platform == "darwin"
TUN_PREFIX_LEN = 30
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
def mac_service_name(dev: str) -> str | None:
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
        service = mac_service_name(alias) or ""
        current = proc.run(["networksetup", "-getdnsservers", service]).stdout.split()
        servers = [] if (not current or "aren't" in " ".join(current)) else current
        return DnsState(mode="MACOS", servers=[service, *servers])
    if _resolved_active():
        # resolvectl revert restores the link wholesale, so nothing to record.
        return DnsState(mode="RESOLVED", servers=[])
    try:
        with open(_RESOLV, encoding="utf-8") as f:
            return DnsState(mode="FILE", servers=f.read().splitlines())
    except OSError:
        return DnsState(mode="FILE", servers=[])


def _mac_flush_dns() -> None:
    proc.run(["dscacheutil", "-flushcache"])
    proc.run(["killall", "-HUP", "mDNSResponder"])


def _resolved_active() -> bool:
    """Is systemd-resolved managing DNS?

    On Ubuntu/Fedora/Arch /etc/resolv.conf is a symlink into /run that
    resolved rewrites, so writing it directly either fails or is silently
    reverted. resolvectl is the only durable way in.
    """
    if IS_MAC:
        return False
    return (Path("/run/systemd/resolve").exists()
            and shutil.which("resolvectl") is not None)


def set_dns_loopback(alias: str) -> None:
    if IS_MAC:
        service = mac_service_name(alias)
        if service:
            proc.run(["networksetup", "-setdnsservers", service, "127.0.0.1"])
        _mac_flush_dns()
        return
    if _resolved_active():
        proc.run(["resolvectl", "dns", alias, "127.0.0.1"])
        # "~." claims every domain for this link, else resolved keeps using
        # the DHCP servers it still holds for other links.
        proc.run(["resolvectl", "domain", alias, "~."])
        proc.run(["resolvectl", "flush-caches"])
        return
    with open(_RESOLV, "w", encoding="utf-8") as f:
        f.write("nameserver 127.0.0.1\n")


def restore_dns(alias: str, state: DnsState, retries: int = 1) -> bool:
    if state.mode == "MACOS":
        service = state.servers[0] if state.servers else mac_service_name(alias)
        rest = state.servers[1:] or ["empty"]
        if service:
            proc.run(["networksetup", "-setdnsservers", service, *rest])
        _mac_flush_dns()
        return True
    if state.mode == "RESOLVED" or _resolved_active():
        ok = proc.run(["resolvectl", "revert", alias]).returncode == 0
        proc.run(["resolvectl", "flush-caches"])
        return ok
    try:
        with open(_RESOLV, "w", encoding="utf-8") as f:
            f.write("\n".join(state.servers) + "\n")
        return True
    except OSError:
        return False


def stranded_loopback_adapters(exclude: str | None = None) -> list[str]:
    """Links whose only resolver is 127.0.0.1, per `resolvectl dns`.

    Only meaningful under systemd-resolved, which tracks DNS per link. With a
    plain /etc/resolv.conf there is a single global file and restore_dns
    already rewrites it, so there is nothing left to strand.
    """
    if not _resolved_active():
        return []
    found = []
    for line in proc.run(["resolvectl", "dns"]).stdout.splitlines():
        # "Link 2 (eth0): 127.0.0.1"
        if not line.startswith("Link ") or "(" not in line or "):" not in line:
            continue
        alias = line.split("(", 1)[1].split(")", 1)[0].strip()
        servers = line.split("):", 1)[1].split()
        if servers == ["127.0.0.1"] and alias != exclude:
            found.append(alias)
    return found


def release_stranded_dns(exclude: str | None = None) -> list[str]:
    reset = []
    for alias in stranded_loopback_adapters(exclude):
        if proc.run(["resolvectl", "revert", alias]).returncode == 0:
            reset.append(alias)
    if reset:
        proc.run(["resolvectl", "flush-caches"])
    return reset


# -- tun adapter -----------------------------------------------------------
def configure_tun(index: int, address: str = TUN_ADDRESS, mask: str = TUN_NETMASK) -> bool:
    """Address the TUN device and bring it up. macOS: tun2socks does this."""
    if IS_MAC:
        return True
    proc.run(["ip", "address", "replace", f"{address}/{TUN_PREFIX_LEN}", "dev", TUN_NAME])
    proc.run(["ip", "link", "set", "dev", TUN_NAME, "up"])
    out = proc.run(["ip", "-4", "-o", "address", "show", "dev", TUN_NAME]).stdout
    return address in out


# -- routes ----------------------------------------------------------------
def add_host_route(server_ip: str, gateway: str) -> None:
    if IS_MAC:
        proc.run(["route", "-n", "add", "-host", server_ip, gateway])
    else:
        proc.run(["ip", "route", "add", server_ip, "via", gateway])


def add_default_routes(tun_index: int | None = None) -> None:
    if IS_MAC:
        # Route via the tun2socks point-to-point address, not -interface: the
        # utun device only forwards what's addressed to its own next-hop.
        proc.run(["route", "-n", "add", "-net", "0.0.0.0/1", t2s.ADDRESS])
        proc.run(["route", "-n", "add", "-net", "128.0.0.0/1", t2s.ADDRESS])
        return
    for dest in ("0.0.0.0/1", "128.0.0.0/1"):
        proc.run(["ip", "route", "add", dest, "dev", TUN_NAME])


def remove_routes(server_ip: str | None = None) -> None:
    if IS_MAC:
        proc.run(["route", "-n", "delete", "-net", "0.0.0.0/1", t2s.ADDRESS])
        proc.run(["route", "-n", "delete", "-net", "128.0.0.0/1", t2s.ADDRESS])
        if server_ip:
            proc.run(["route", "-n", "delete", "-host", server_ip])
    else:
        proc.run(["ip", "route", "del", "default", "dev", TUN_NAME])
        for dest in ("0.0.0.0/1", "128.0.0.0/1"):
            proc.run(["ip", "route", "del", dest, "dev", TUN_NAME])
        if server_ip:
            proc.run(["ip", "route", "del", server_ip])


def wait_for_tun(name: str = TUN_NAME, timeout: float = 30.0) -> int | None:
    # Linux only: Xray creates TUN_NAME itself. macOS has no equivalent path —
    # its connect flow drives tun2socks.bring_up_device() directly instead.
    if IS_MAC:
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        links = json.loads(proc.run(["ip", "-j", "link", "show", name]).stdout or "[]")
        if links:
            return links[0].get("ifindex", 0)
        time.sleep(1.0)
    return None
