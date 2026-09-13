"""Hysteria2 outbound builder.

Security is always TLS -- Hysteria2 is TLS/QUIC by protocol design, so
unlike the other builders this never reads p.security. skipFallback/realm/
gecko are out of scope; only the salamander obfuscation mask is built.
"""
from __future__ import annotations

import re

from ..profiles import Profile, normalize_pcs, valid_pcs

_PLACEHOLDER = "__IFACE__"

_PORTS_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")


def normalize_ports(raw: str) -> str | None:
    """udpHop.ports goes straight into an Xray range/list expression, so a
    bad value must be caught here rather than only breaking port-hopping
    at connect time. ':' is accepted as an alternate separator some links
    use and normalized to '-'; anything that isn't a valid range/list of
    ports 1-65535 is dropped entirely -- udpHop is omitted rather than
    sent malformed, so the server's plain listening port still works.
    """
    s = (raw or "").replace(":", "-").replace(" ", "")
    if not s or not _PORTS_RE.match(s):
        return None
    for part in s.split(","):
        for bound in part.split("-"):
            if not 1 <= int(bound) <= 65535:
                return None
    return s


def normalize_hop_interval(raw: str) -> str | None:
    """udpHop.interval: Xray accepts a plain integer (seconds) or its own
    "1-2" range form, but -- confirmed against a real xray binary --
    refuses a unit suffix like "30s" outright ('Invalid integer range').
    A bare number or one with a trailing "s" are both accepted here and
    normalized; anything else (including empty) is omitted so Xray falls
    back to its own default instead of refusing to start.
    """
    s = (raw or "").strip()
    if s.isdigit():
        return s
    if s.endswith("s") and s[:-1].isdigit():
        return s[:-1]
    if re.fullmatch(r"\d+-\d+", s):
        return s
    return None


def apply(proxy: dict, p: Profile) -> None:
    proxy["protocol"] = "hysteria"
    proxy["settings"] = {"address": p.address, "port": p.port, "version": 2}

    tls: dict = {}
    if p.sni:
        tls["serverName"] = p.sni
    if p.alpn:
        tls["alpn"] = [a.strip() for a in p.alpn.split(",") if a.strip()]
    if p.pcs:
        pcs = normalize_pcs(p.pcs)
        if valid_pcs(pcs):
            tls["pinnedPeerCertSha256"] = pcs
    if p.vcn:
        tls["verifyPeerCertByName"] = p.vcn

    # allow_insecure is never rendered here either -- same reason as every
    # other protocol (core/outbounds/_common.py): the bundled Xray binary
    # hard-refuses "allowInsecure" now.

    quic: dict = {}
    ports = normalize_ports(p.hy2_ports)
    if ports:
        hop: dict = {"ports": ports}
        interval = normalize_hop_interval(p.hy2_hop_interval)
        if interval:
            hop["interval"] = interval
        quic["udpHop"] = hop
    if p.hy2_up_mbps > 0 or p.hy2_down_mbps > 0:
        quic["congestion"] = "brutal"
        if p.hy2_up_mbps > 0:
            quic["brutalUp"] = f"{p.hy2_up_mbps}mbps"
        if p.hy2_down_mbps > 0:
            quic["brutalDown"] = f"{p.hy2_down_mbps}mbps"
    else:
        quic["congestion"] = "bbr"

    finalmask: dict = {"quicParams": quic}
    if p.hy2_obfs_password:
        finalmask["udp"] = [
            {"type": "salamander", "settings": {"password": p.hy2_obfs_password}}
        ]

    proxy["streamSettings"] = {
        "network": "hysteria",
        "security": "tls",
        "sockopt": {"interface": _PLACEHOLDER},
        "hysteriaSettings": {"version": 2, "auth": p.id},
        "tlsSettings": tls,
        "finalmask": finalmask,
    }
