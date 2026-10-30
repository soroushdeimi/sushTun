"""Serverless entry: the first server is dialed through a local direct
outbound that splits the TLS ClientHello into small TLS records and TCP
segments, so filtering that reads the server name from it misses it."""
from __future__ import annotations

import copy
import ipaddress

from ..i18n import tr
from . import outbounds
from .profiles import Profile

TAG = "serverless"
# v26.3.27 parses only the singular length/delay keys (plural ones fail with
# "LengthMin can't be 0"). Order matters: with tlshello first, the record
# split silently did nothing; segment-then-tlshello was measured to do both.
SEGMENT_MASK = {"type": "fragment", "settings": {
    "packets": "1-1", "length": "1-114", "delay": "1", "maxSplit": "11"}}
HELLO_MASK = {"type": "fragment", "settings": {
    "packets": "tlshello", "length": "6-104", "delay": "0", "maxSplit": "0"}}
_MOVED_SOCKOPT = ("tcpFastOpen", "tcpMptcp", "tcpCongestion")


def enabled(cfg: dict | None) -> bool:
    return isinstance(cfg, dict) and cfg.get("enabled") is True


def problem(profile: Profile) -> str | None:
    name = profile.name or profile.address
    protocol = str(profile.protocol or "").lower()
    if protocol in ("wireguard", "hysteria2"):
        return tr(
            "Serverless works only with TCP servers; {name} uses {protocol}.",
            name=name,
            protocol=protocol,
        )
    if profile.security not in ("tls", "reality"):
        return tr("Serverless needs a TLS or REALITY server; {name} has no TLS.", name=name)
    if profile.network == "xhttp" and outbounds.has_download_settings(profile):
        return tr(
            "Serverless cannot cover {name}: its XHTTP download settings dial separately.",
            name=name,
        )
    return None


def outbound() -> dict:
    return {
        "tag": TAG,
        "protocol": "freedom",
        "settings": {"domainStrategy": "ForceIPv4"},
        "streamSettings": {
            "sockopt": {"interface": "__IFACE__"},
            "finalmask": {
                "tcp": [
                    copy.deepcopy(SEGMENT_MASK),
                    copy.deepcopy(HELLO_MASK),
                ]
            },
        },
    }


def apply(cfg: dict, entry_address: str, server_ip: str | None) -> None:
    outbounds_list = cfg.setdefault("outbounds", [])
    entry = next((o for o in outbounds_list if o.get("tag") == "chain-1"), None)
    if entry is None:
        entry = next((o for o in outbounds_list if o.get("tag") == "proxy"), None)
    if entry is None:
        return

    new_out = outbound()
    stream = entry.setdefault("streamSettings", {})
    sockopt = stream.setdefault("sockopt", {})
    sockopt.pop("interface", None)
    sockopt.pop("domainStrategy", None)
    new_sockopt = new_out["streamSettings"]["sockopt"]
    for key in _MOVED_SOCKOPT:
        if key in sockopt:
            new_sockopt[key] = sockopt.pop(key)
    sockopt["dialerProxy"] = TAG

    finalmask = stream.get("finalmask")
    if isinstance(finalmask, dict):
        finalmask.pop("tcp", None)
        if not finalmask:
            stream.pop("finalmask", None)

    outbounds_list.append(new_out)

    if server_ip and entry_address:
        try:
            ipaddress.ip_address(entry_address)
        except ValueError:
            dns = cfg.setdefault("dns", {})
            hosts = dict(dns.get("hosts") or {})
            hosts[entry_address] = server_ip
            dns["hosts"] = hosts


# -- Serverless only: no server at all, every site straight from this device --
ONLY_UID = "serverless-only"
ONLY_PROTOCOL = "serverless"


def only_profile() -> Profile:
    """Stand-in profile for a connection with no server behind it."""
    return Profile(name="Serverless only", protocol=ONLY_PROTOCOL, address="", uid=ONLY_UID)


def is_only(profile) -> bool:
    return isinstance(profile, Profile) and profile.protocol == ONLY_PROTOCOL


# DoH is blocked by name and by address, but the filter leaves the addresses
# of DOH_FRONT open. Pointing the DoH name there, with the handshake going out
# through the fragmenting "proxy", makes the resolver reachable.
DOH_URL = "https://cloudflare-dns.com/dns-query"
DOH_HOST = "cloudflare-dns.com"
DOH_FRONT = "challenges.cloudflare.com"
FALLBACK_BOOTSTRAP = "1.1.1.1"
# What the filter answers blocked names with; a connection to one just hangs.
SINKHOLES = ["10.10.34.0/24", "2001:4188:2:600::/64"]
# Dropped so the DNS block can only ever use our two servers.
_DNS_KEYS = ("servers", "queryStrategy", "disableFallback", "tag", "clientIp")


def only_outbound() -> dict:
    out = outbound()
    out["tag"] = "proxy"
    return out


def apply_only_outbound(cfg: dict) -> None:
    """Make the first outbound ("proxy") the fragmenting direct one, so every
    rule that sends traffic to "proxy" now means "direct, fragmented"."""
    outbounds_list = cfg.setdefault("outbounds", [])
    for i, out in enumerate(outbounds_list):
        if out.get("tag") == "proxy":
            outbounds_list[i] = only_outbound()
            return
    outbounds_list.insert(0, only_outbound())


def _bootstrap_ip(bootstrap: list[str] | None) -> str:
    # IPv4 first: routers often list a scoped link-local IPv6 resolver first,
    # and queries are UseIPv4 anyway.
    found = []
    for item in bootstrap or []:
        try:
            found.append((item, ipaddress.ip_address(item)))
        except ValueError:
            continue
    for item, ip in found:
        if ip.version == 4 and not (ip.is_loopback or ip.is_link_local or ip.is_unspecified):
            return item
    for item, ip in found:
        if ip.version == 6 and "%" not in item and not (
                ip.is_loopback or ip.is_link_local or ip.is_unspecified):
            return item
    return FALLBACK_BOOTSTRAP


def apply_only_network(cfg: dict, bootstrap: list[str] | None) -> None:
    """DNS over the fragmenting outbound, plus the rules that keep a filtered
    answer or a QUIC attempt from hanging a connection."""
    dns = cfg.setdefault("dns", {})
    hosts = dict(dns.get("hosts") or {})
    for key in _DNS_KEYS:
        dns.pop(key, None)
    hosts[DOH_HOST] = DOH_FRONT
    # DOH_FRONT itself goes to the system resolver (plain UDP through the NIC).
    # The OS resolver points at Xray while connected, so it cannot be localhost.
    dns["servers"] = [DOH_URL, {"address": _bootstrap_ip(bootstrap),
                                "domains": [f"full:{DOH_FRONT}"], "skipFallback": True}]
    dns["hosts"] = hosts
    dns["queryStrategy"] = "UseIPv4"
    rules = cfg.setdefault("routing", {}).setdefault("rules", [])
    # QUIC is blocked so browsers fall back to TCP+TLS, where fragmenting works.
    rules[:0] = [
        {"type": "field", "ip": list(SINKHOLES), "outboundTag": "block"},
        {"type": "field", "network": "udp", "port": "443", "outboundTag": "block"},
    ]
