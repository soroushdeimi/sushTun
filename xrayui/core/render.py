"""Render a runtime Xray config by injecting a Profile into the template.

Only the `proxy` outbound is rewritten; every other part of
config.template.json (inbounds, dns-out/direct/block, routing) is preserved
verbatim, and the __IFACE__ / __INTERFACE__ placeholders are substituted last.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import paths
from .profiles import Profile

_PLACEHOLDER = "__IFACE__"


def _stream_settings(p: Profile) -> dict:
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


def _apply_profile(cfg: dict, p: Profile) -> None:
    proxy = next((o for o in cfg.get("outbounds", []) if o.get("tag") == "proxy"), None)
    if proxy is None:
        raise ValueError("template has no outbound tagged 'proxy'")
    user: dict = {"id": p.id, "encryption": p.encryption}
    if p.flow:
        user["flow"] = p.flow
    proxy["protocol"] = p.protocol
    proxy["settings"] = {"vnext": [{"address": p.address, "port": p.port, "users": [user]}]}
    proxy["streamSettings"] = _stream_settings(p)


def build_text(profile: Profile, iface_alias: str, template_path: Path | None = None) -> str:
    tmpl_path = template_path or paths.config_template()
    cfg = json.loads(tmpl_path.read_text(encoding="utf-8"))
    _apply_profile(cfg, profile)
    text = json.dumps(cfg, indent=2, ensure_ascii=False)
    return text.replace("__INTERFACE__", iface_alias).replace("__IFACE__", iface_alias)


def build(profile: Profile, iface_alias: str, template_path: Path | None = None) -> Path:
    out = paths.runtime_config()
    out.write_text(build_text(profile, iface_alias, template_path), encoding="utf-8")
    return out
