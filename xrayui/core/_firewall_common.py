"""Shared helpers for the per-OS firewall backends.

The firewall is an outbound-only lockdown: while connected it drops any packet
leaving the machine that is not (a) on the tunnel device, (b) to a proxy server
IP, (c) to a DNS resolver (Xray dials resolvers directly out the physical NIC,
not through the tunnel), (d) loopback, or (e) -- when allow_lan is on -- the
LAN / link-local / DHCP. Inbound traffic is never filtered, so a misrule cannot
cut the user's downloads; it can only (safely) stop a leak.
"""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path

from .. import paths

# Private + link-local ranges allowed when firewall.allow_lan is on.
LAN_V4 = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
LAN_V6 = ("fe80::/10",)
# DHCP client -> server, as seen on the OUTPUT path. v4: 68 -> 67; v6: 547 -> 546.
DHCP_V4 = (68, 67)
DHCP_V6 = (547, 546)

# The recognisable tag every rule carries, so a leftover can be found and
# removed even after the state file is gone.
TAG = "sushtun"


class FirewallError(Exception):
    """The firewall could not be installed or verified as live."""


def split_ips(server_ips) -> tuple[list[str], list[str]]:
    """Split `server_ips` into (ipv4, ipv6), dropping anything unparseable."""
    v4: list[str] = []
    v6: list[str] = []
    for ip in server_ips or []:
        try:
            addr = ipaddress.ip_address(str(ip).strip())
        except ValueError:
            continue
        (v4 if addr.version == 4 else v6).append(str(addr))
    return v4, v6


def resolver_ips(dns_cfg) -> list[str]:
    """The literal-IP DNS resolvers Xray dials directly out the physical NIC.

    The template's dns-out outbound is bound to the uplink interface, so these
    queries never traverse the tunnel; the firewall must allow them or it would
    break DNS and, with it, the whole connection. Hostname resolvers are
    resolved through the tunnel (loopback) first, so only literal IPs are
    needed here.
    """
    ips: set[str] = set()
    for entry in (dns_cfg or {}).get("servers") or []:
        host = _server_host(entry)
        try:
            ipaddress.ip_address(host)
        except ValueError:
            continue
        ips.add(host)
    return sorted(ips)


def _server_host(entry) -> str:
    """The bare host of a DNS server entry (DoH URL, host:port, or bare IP)."""
    addr = str(entry.get("address") or "") if isinstance(entry, dict) else str(entry or "")
    if "://" in addr:
        addr = addr.split("://", 1)[1]
    addr = addr.split("/", 1)[0]  # drop a DoH path
    if addr.startswith("[") and "]" in addr:
        return addr[1:addr.index("]")]
    if addr.count(":") == 1:  # a scheme-less host:port
        addr = addr.rsplit(":", 1)[0]
    return addr


# -- state persistence -------------------------------------------------------
# The install state (pf enable token, the backed-up main ruleset, the rules we
# loaded) must survive a crash so recover_stale / the boot-restore task can
# undo the firewall on the next launch. It lives in the state dir, root-only.

_STATE_NAME = "firewall.json"


def _state_path() -> Path:
    return paths.state_dir() / _STATE_NAME


def save_state(data: dict) -> None:
    d = paths.state_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = _state_path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # holds the pf token + the user's main ruleset
    except OSError:
        pass
    tmp.replace(target)


def load_state() -> dict | None:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear_state() -> None:
    _state_path().unlink(missing_ok=True)
