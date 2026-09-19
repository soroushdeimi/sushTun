"""Stream-settings building shared by stream-based outbounds (vless, vmess,
trojan, shadowsocks).
"""
from __future__ import annotations

import json

from ..profiles import Profile, normalize_pcs, valid_pcs, valid_pqv

_PLACEHOLDER = "__IFACE__"


def _parse_extra(text: str) -> dict:
    """xhttp_extra is free-form JSON text a user pastes in; never let a typo
    there break the render -- drop it silently like a bad routing rule."""
    text = (text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


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
        if p.ech:
            tls["echConfigList"] = p.ech
        if p.pcs:
            pcs = normalize_pcs(p.pcs)
            if valid_pcs(pcs):
                tls["pinnedPeerCertSha256"] = pcs
        if p.vcn:
            tls["verifyPeerCertByName"] = p.vcn
        # allow_insecure is intentionally never rendered here: the bundled
        # Xray 26.3.27 binary hard-refuses "allowInsecure" outright (its own
        # error: 'will be removed automatically after 2026-06-01, please use
        # "pinnedPeerCertSha256"(pcs) and "verifyPeerCertByName"(vcn)
        # instead') -- emitting it would make Xray refuse to start, which
        # the app must never do for a value the UI itself offered. The field
        # and checkbox survive for round-tripping an imported link/config
        # that set it, but pcs/vcn are what actually works now.
        stream["tlsSettings"] = tls
    elif p.security == "reality":
        reality: dict = {}
        for key, val in (("serverName", p.sni), ("fingerprint", p.fp),
                         ("publicKey", p.pbk), ("shortId", p.sid), ("spiderX", p.spx)):
            if val:
                reality[key] = val
        if valid_pqv(p.pqv):
            reality["mldsa65Verify"] = p.pqv.strip()
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
    elif p.network == "xhttp":
        xhttp: dict = {}
        if p.path:
            xhttp["path"] = p.path
        if p.host:
            xhttp["host"] = p.host
        if p.xhttp_mode:
            xhttp["mode"] = p.xhttp_mode
        extra = _parse_extra(p.xhttp_extra)
        if extra:
            xhttp["extra"] = extra
        stream["xhttpSettings"] = xhttp
    elif p.network == "httpupgrade":
        hu: dict = {}
        if p.path:
            hu["path"] = p.path
        if p.host:
            hu["host"] = p.host
        stream["httpupgradeSettings"] = hu
    elif p.network == "tcp" and p.header_type == "http":
        request: dict = {"path": [p.path or "/"]}
        hosts = [h.strip() for h in p.host.split(",") if h.strip()]
        if hosts:
            request["headers"] = {"Host": hosts}
        stream["tcpSettings"] = {"header": {"type": "http", "request": request}}
    return stream
