"""Stream-settings building shared by stream-based outbounds (vless today;
vmess/trojan/shadowsocks will reuse this once they land).
"""
from __future__ import annotations

from ..profiles import Profile

_PLACEHOLDER = "__IFACE__"


def stream_settings(p: Profile) -> dict:
    stream: dict = {"network": p.network, "security": p.security,
                    "sockopt": {"interface": _PLACEHOLDER}}
    if p.security == "tls":
        tls: dict = {}
        if p.sni:
            tls["serverName"] = p.sni
        if p.fp:
            tls["fingerprint"] = p.fp
        if p.alpn:
            tls["alpn"] = [a.strip() for a in p.alpn.split(",") if a.strip()]
        stream["tlsSettings"] = tls
    elif p.security == "reality":
        reality: dict = {}
        for key, val in (("serverName", p.sni), ("fingerprint", p.fp),
                         ("publicKey", p.pbk), ("shortId", p.sid), ("spiderX", p.spx)):
            if val:
                reality[key] = val
        stream["realitySettings"] = reality

    if p.network == "ws":
        ws: dict = {}
        if p.path:
            ws["path"] = p.path
        if p.host:
            ws["headers"] = {"Host": p.host}
        stream["wsSettings"] = ws
    elif p.network == "grpc":
        stream["grpcSettings"] = {"serviceName": p.service_name}
    elif p.network in ("h2", "http"):
        h2: dict = {}
        if p.path:
            h2["path"] = p.path
        if p.host:
            h2["host"] = [h.strip() for h in p.host.split(",") if h.strip()]
        stream["httpSettings"] = h2
    return stream
