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
from collections.abc import Callable
from pathlib import Path

from . import proc
from . import tun2socks as t2s
from ._net_common import TUN_ADDRESS, TUN_NAME, TUN_NETMASK, DnsState, Interface

IS_MAC = sys.platform == "darwin"
TUN_PREFIX_LEN = 30
_RESOLV = "/etc/resolv.conf"

# The resolver systemd-resolved is pointed at on the tunnel link: the peer of
# TUN_ADDRESS inside the /30, so queries to it are routed into xray0, where the
# template sends anything on port 53 arriving over tun-in to dns-out.
TUN_DNS = "172.19.0.1"


# -- interface detection ---------------------------------------------------
def _link_types() -> dict[str, str]:
    links = json.loads(proc.run(["ip", "-j", "link", "show"]).stdout or "[]")
    return {link.get("ifname"): link.get("link_type", "") for link in links}


def _linux_detect() -> Interface | None:
    routes = json.loads(proc.run(["ip", "-j", "route", "show", "default"]).stdout or "[]")
    candidates = []
    for route in routes:
        if {"dead", "linkdown"}.intersection(route.get("flags", [])):
            continue
        # Multipath routes keep the device and gateway on each nexthop.
        for hop in route.get("nexthops", [route]):
            if {"dead", "linkdown"}.intersection(hop.get("flags", [])):
                continue
            if hop.get("dev") and hop["dev"] != TUN_NAME and hop.get("gateway"):
                candidates.append({**route, **hop})
    routes = candidates
    if not routes:
        return None
    # The uplink is the physical link, not simply the lowest-metric default:
    # OpenVPN adds its own default at metric 50, under Wi-Fi's 600. Taking it
    # tunneled sushTun through the other VPN (slower, and dropping whenever
    # that VPN reconnects), and the gateway-change repair then never matched
    # the adapter again. Tunnels have no link-layer type ("none").
    types = _link_types()
    physical = [r for r in routes if types.get(r["dev"]) not in ("none", "loopback")]
    r = min(physical or routes, key=lambda route: route.get("metric", 0))
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


def set_dns_loopback(alias: str) -> bool:
    """Send the system's DNS into the tunnel. False if it would not stick."""
    if IS_MAC:
        service = mac_service_name(alias)
        ok = bool(service) and proc.run(
            ["networksetup", "-setdnsservers", service, "127.0.0.1"]).returncode == 0
        _mac_flush_dns()
        return ok
    if _resolved_active():
        # Never 127.0.0.1 on the physical link: resolved pins a link's queries
        # to that link (IP_UNICAST_IF), and loopback is unreachable through a
        # NIC, so every lookup would time out. Claim DNS on the tunnel link
        # instead, as wg-quick and Tailscale do. The physical link keeps what
        # NetworkManager gave it, and the setting dies with xray0, so a crash
        # strands nothing.
        return _claim_tun_dns()
    with open(_RESOLV, "w", encoding="utf-8") as f:
        f.write("nameserver 127.0.0.1\n")
    return True


def _tun_dns_applied() -> bool:
    # "Link 10 (xray0): 172.19.0.1"
    dns = proc.run(["resolvectl", "dns", TUN_NAME])
    if dns.returncode != 0 or TUN_DNS not in dns.stdout.split():
        return False
    # A server alone does not claim queries: NetworkManager may have cleared
    # the routing domain while leaving the address intact.
    domain = proc.run(["resolvectl", "domain", TUN_NAME])
    return domain.returncode == 0 and "~." in domain.stdout.split()


def _claim_tun_dns(attempts: int = 5) -> bool:
    """Point resolved at the tunnel, and check that it took.

    A failed resolvectl used to go unnoticed, and lookups then quietly left
    the physical link in the clear (seen live: resolvectl crashed on a bundled
    library, see proc.child_env). Read the setting back, retry, and report.
    """
    if shutil.which("nmcli"):
        # NetworkManager adopts xray0 as an external device, and while it did
        # the tunnel's resolved settings were seen wiped without a trace minutes
        # after connecting (no bus log, so a RevertLink). Suspected rather than
        # proven, so repair_tun_dns() also re-checks on a timer. Runtime only:
        # it lapses when xray0 disappears.
        proc.run(["nmcli", "device", "set", TUN_NAME, "managed", "no"])
    applied = False
    for _ in range(attempts):
        proc.run(["resolvectl", "dns", TUN_NAME, TUN_DNS])
        # "~." claims every domain for this link, else resolved keeps using
        # the DHCP servers it still holds for other links.
        proc.run(["resolvectl", "domain", TUN_NAME, "~."])
        proc.run(["resolvectl", "default-route", TUN_NAME, "yes"])
        time.sleep(1.0)  # resolved may not have picked up a brand-new link yet
        if _tun_dns_applied():
            applied = True
            break
    proc.run(["resolvectl", "flush-caches"])
    return applied


def repair_tun_dns() -> bool | None:
    """Re-claim the tunnel's DNS if another program cleared it.

    None: nothing to do. True: it had been cleared and is back. False: it had
    been cleared and would not come back, so lookups are leaving outside.
    """
    if IS_MAC or not _resolved_active() or _tun_dns_applied():
        return None
    return _claim_tun_dns(attempts=2)


def restore_dns(alias: str, state: DnsState, retries: int = 1) -> bool:
    if state.mode == "MACOS":
        service = state.servers[0] if state.servers else mac_service_name(alias)
        rest = state.servers[1:] or ["empty"]
        if not service:
            return False
        for attempt in range(max(1, retries)):
            if proc.run(["networksetup", "-setdnsservers", service, *rest]).returncode == 0:
                _mac_flush_dns()
                return True
            if attempt + 1 < retries:
                time.sleep(1.0)
        return False
    if state.mode == "RESOLVED" or _resolved_active():
        # Only the tunnel link was touched, and it is usually gone with xray
        # already, so a failure here is expected. Never revert the physical
        # link outright: that also wipes the servers NetworkManager pushed,
        # leaving no DNS at all until the next reconnect.
        proc.run(["resolvectl", "revert", TUN_NAME])
        # Older builds pinned the physical link itself to 127.0.0.1; undo that.
        if alias in stranded_loopback_adapters():
            proc.run(["resolvectl", "revert", alias])
        proc.run(["resolvectl", "flush-caches"])
        return True
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
def _ip_route(*args: str):
    result = proc.run(["ip", *args])
    if result.returncode != 0:
        raise RuntimeError(f"ip {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def add_host_route(server_ip: str, gateway: str) -> None:
    if IS_MAC:
        proc.run(["route", "-n", "add", "-host", server_ip, gateway])
    else:
        _ip_route("route", "add", server_ip, "via", gateway)


def replace_host_route(server_ip: str, gateway: str) -> None:
    """Repoint the pinned server route after the gateway moved."""
    if not IS_MAC:
        _ip_route("route", "replace", server_ip, "via", gateway)
        return
    if proc.run(["route", "-n", "change", "-host", server_ip, gateway]).returncode != 0:
        proc.run(["route", "-n", "delete", "-host", server_ip])
        add_host_route(server_ip, gateway)


def mac_ensure_scoped_default(iface: str, gateway: str) -> bool:
    """Give `iface` its own (scoped) default route if it lost it. True if added.

    Xray pins direct/proxy/dns-out to the interface (IP_BOUND_IF), and macOS
    then looks up only routes scoped to it. macOS normally keeps one per
    interface, but VPN helpers (seen with OpenVPN Connect) can leave just the
    global default behind: every pinned connection without a host route of
    its own failed with "network is unreachable", so Iran-direct sites and
    the domestic DNS never loaded while the tunnel itself worked.
    """
    out = proc.run(["route", "-n", "get", "-ifscope", iface, "default"]).stdout
    if "IFSCOPE" in out:
        return False
    return proc.run(["route", "-n", "add", "-ifscope", iface, "default", gateway]).returncode == 0


def mac_other_vpn(iface: str) -> str | None:
    """Another VPN's device currently carrying the default traffic, if any."""
    dev = mac_route_device("1.1.1.1")
    return dev if dev and dev not in (iface, t2s.DEVICE) else None


def mac_route_device(dest: str) -> str | None:
    """The interface macOS would send `dest` out of, per `route -n get`."""
    for line in proc.run(["route", "-n", "get", dest]).stdout.splitlines():
        line = line.strip()
        if line.startswith("interface:"):
            return line.split(":", 1)[1].strip() or None
    return None


# macOS takes over with four /2 routes rather than the two /1s used elsewhere.
# VPN apps there (OpenVPN Connect, WireGuard, most NetworkExtensions) claim
# 0/1 + 128/1 themselves; ours then failed with "File exists". A /2 is more
# specific than their /1, so ours win and both can run at once, while the
# other VPN keeps its own narrower routes (a company subnet, its DNS server).
MAC_SPLIT = ("0.0.0.0/2", "64.0.0.0/2", "128.0.0.0/2", "192.0.0.0/2")
# Earlier builds used these; still removed so an old session cannot strand them.
_MAC_OLD_SPLIT = ("0.0.0.0/1", "128.0.0.0/1")


def _mac_via(native: bool) -> list[str]:
    # Xray's own utun is reached by interface. The tun2socks device only
    # forwards what is addressed to its point-to-point next-hop.
    return ["-interface", t2s.DEVICE] if native else [t2s.ADDRESS]


def mac_add_split_routes(native: bool) -> None:
    for dest in MAC_SPLIT:
        result = proc.run(["route", "-n", "add", "-net", dest, *_mac_via(native)])
        if result.returncode != 0:
            raise RuntimeError(f"route add {dest} failed: {result.stderr.strip()}")


def mac_wait_for_device(timeout: float = 15.0, alive: Callable[[], bool] | None = None) -> bool:
    """True once the utun device exists; False on timeout or when `alive`
    says its owner has exited."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.run(["ifconfig", t2s.DEVICE]).returncode == 0:
            return True
        if alive is not None and not alive():
            return False
        time.sleep(0.3)
    return False


def add_default_routes(tun_index: int | None = None) -> None:
    if IS_MAC:
        mac_add_split_routes(native=False)
        return
    for dest in ("0.0.0.0/1", "128.0.0.0/1"):
        _ip_route("route", "add", dest, "dev", TUN_NAME)


def repair_tun_routes() -> bool | None:
    """Restore missing Linux split routes without replacing another VPN's routes."""
    if IS_MAC:
        return None
    routes = json.loads(_ip_route("-j", "-4", "route", "show", "table", "main").stdout)
    installed = {r.get("dst") for r in routes if r.get("dev") == TUN_NAME}
    missing = [d for d in ("0.0.0.0/1", "128.0.0.0/1") if d not in installed]
    for dest in missing:
        _ip_route("route", "add", dest, "dev", TUN_NAME)
    return True if missing else None


def remove_routes(server_ip: str | None = None) -> None:
    if IS_MAC:
        for dest in (*MAC_SPLIT, *_MAC_OLD_SPLIT):
            for native in (True, False):
                proc.run(["route", "-n", "delete", "-net", dest, *_mac_via(native)])
        if server_ip:
            proc.run(["route", "-n", "delete", "-host", server_ip])
    else:
        proc.run(["ip", "route", "del", "default", "dev", TUN_NAME])
        for dest in ("0.0.0.0/1", "128.0.0.0/1"):
            proc.run(["ip", "route", "del", dest, "dev", TUN_NAME])
        if server_ip:
            proc.run(["ip", "route", "del", server_ip])


def wait_for_tun(name: str = TUN_NAME, timeout: float = 30.0,
                 alive: Callable[[], bool] | None = None) -> int | None:
    # Linux only: Xray creates TUN_NAME itself. macOS has no equivalent path —
    # its connect flow drives tun2socks.bring_up_device() directly instead.
    if IS_MAC:
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        links = json.loads(proc.run(["ip", "-j", "link", "show", name]).stdout or "[]")
        if links:
            return links[0].get("ifindex", 0)
        if alive is not None and not alive():
            return None
        time.sleep(1.0)
    return None


def foreign_tunnel(iface: str) -> str | None:
    """The device another VPN steers traffic through ahead of ours, if any.

    Clients like v2rayN/sing-box install policy-routing rules that sit ahead of
    the main table, so our routes there would be silently outvoted. A VPN that
    only adds a default route to the main table (OpenVPN, WireGuard via
    NetworkManager) loses to our two /1 routes, so it can run alongside.
    """
    if IS_MAC:
        # Nothing to refuse: MAC_SPLIT outranks another VPN's routes, as the
        # /1s do on Windows. mac_other_vpn() names it for the log.
        return None
    try:
        route = json.loads(proc.run(["ip", "-j", "route", "get", "1.1.1.1"]).stdout or "[]")[0]
        dev = route["dev"]
    except (ValueError, IndexError, KeyError, TypeError):
        return None  # offline: nothing to conflict with
    # `ip route get` names the table only when it is not main.
    if route.get("table") in (None, "main"):
        return None
    return dev if dev not in (iface, TUN_NAME) else None
