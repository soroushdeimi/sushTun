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
