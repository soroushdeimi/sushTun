"""Hysteria2 outbound builder.

Security is always TLS -- Hysteria2 is TLS/QUIC by protocol design, so
unlike the other builders this never reads p.security. skipFallback/realm/
gecko are out of scope; only the salamander obfuscation mask is built.
"""
from __future__ import annotations

from ..profiles import Profile

_PLACEHOLDER = "__IFACE__"


def apply(proxy: dict, p: Profile) -> None:
    proxy["protocol"] = "hysteria"
    proxy["settings"] = {"address": p.address, "port": p.port, "version": 2}

    tls: dict = {}
    if p.sni:
        tls["serverName"] = p.sni
    if p.alpn:
        tls["alpn"] = [a.strip() for a in p.alpn.split(",") if a.strip()]
    if p.pcs:
        tls["pinnedPeerCertSha256"] = p.pcs
    if p.vcn:
        tls["verifyPeerCertByName"] = p.vcn

    # allow_insecure is never rendered here either -- same reason as every
    # other protocol (core/outbounds/_common.py): the bundled Xray binary
    # hard-refuses "allowInsecure" now.

    quic: dict = {}
    if p.hy2_ports:
        quic["udpHop"] = {"ports": p.hy2_ports, "interval": p.hy2_hop_interval or "30"}
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
