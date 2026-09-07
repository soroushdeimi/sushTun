"""Render a runtime Xray config by injecting a Profile into the template.

Only the `proxy` outbound is rewritten; every other part of
config.template.json (inbounds, dns-out/direct/block, routing) is preserved
verbatim, and the __IFACE__ / __INTERFACE__ placeholders are substituted last.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import paths
from . import settings as app_settings
from .metrics import STATS_API_PORT
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


def _wg_endpoint(p: Profile) -> str:
    addr = p.address
    if ":" in addr and not addr.startswith("["):
        return f"[{addr}]:{p.port}"
    return f"{addr}:{p.port}"


def _wg_reserved(raw: str) -> list[int]:
    s = (raw or "").strip().strip("[]")
    if not s:
        return []
    s = s.replace("-", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) == 3 and all(p.lstrip("+-").isdigit() for p in parts):
        return [int(p) & 0xFF for p in parts]
    return []


def _apply_wireguard(proxy: dict, p: Profile) -> None:
    # Xray WireGuard outbounds do not accept streamSettings.
    proxy.pop("streamSettings", None)
    addrs = [a.strip() for a in (p.wg_local_address or "").split(",") if a.strip()]
    peer: dict = {
        "endpoint": _wg_endpoint(p),
        "publicKey": p.pbk,
        "allowedIPs": ["0.0.0.0/0", "::/0"],
    }
    if p.wg_preshared:
        peer["preSharedKey"] = p.wg_preshared
    if p.wg_keepalive:
        peer["keepAlive"] = int(p.wg_keepalive)
    settings: dict = {
        "secretKey": p.id,
        "peers": [peer],
        "mtu": int(p.wg_mtu) if p.wg_mtu else 1420,
        "noKernelTun": True,
        "domainStrategy": "ForceIP",
    }
    if addrs:
        settings["address"] = addrs
    reserved = _wg_reserved(p.wg_reserved)
    if reserved:
        settings["reserved"] = reserved
    proxy["protocol"] = "wireguard"
    proxy["settings"] = settings


def _apply_profile(cfg: dict, p: Profile) -> None:
    proxy = next((o for o in cfg.get("outbounds", []) if o.get("tag") == "proxy"), None)
    if proxy is None:
        raise ValueError("template has no outbound tagged 'proxy'")
    if (p.protocol or "").lower() == "wireguard":
        _apply_wireguard(proxy, p)
        return
    user: dict = {"id": p.id, "encryption": p.encryption}
    if p.flow:
        user["flow"] = p.flow
    proxy["protocol"] = p.protocol
    proxy["settings"] = {"vnext": [{"address": p.address, "port": p.port, "users": [user]}]}
    proxy["streamSettings"] = _stream_settings(p)


def _apply_routing(cfg: dict, rules: list[dict]) -> None:
    routing = cfg.setdefault("routing", {})
    routing.setdefault("rules", []).extend(rules)
    routing["domainStrategy"] = "IPIfNonMatch"


def _drop_tun_inbound(cfg: dict) -> None:
    # Xray has no native TUN inbound on macOS; there we bridge socks-in to a
    # real TUN device with tun2socks instead, so the tun-in entry is unused.
    cfg["inbounds"] = [i for i in cfg.get("inbounds", []) if i.get("tag") != "tun-in"]


def _apply_log_level(cfg: dict, level: str) -> None:
    if level not in app_settings.LOG_LEVELS:
        return
    cfg.setdefault("log", {})["loglevel"] = level


def _apply_stats(cfg: dict) -> None:
    cfg["stats"] = {}
    cfg["api"] = {"tag": "api", "services": ["StatsService"]}
    cfg["policy"] = {"system": {
        "statsInboundUplink": True, "statsInboundDownlink": True,
        "statsOutboundUplink": True, "statsOutboundDownlink": True,
    }}
    cfg.setdefault("inbounds", []).append({
        "tag": "api", "listen": "127.0.0.1", "port": STATS_API_PORT,
        "protocol": "dokodemo-door", "settings": {"address": "127.0.0.1"},
    })
    rules = cfg.setdefault("routing", {}).setdefault("rules", [])
    rules.insert(0, {"type": "field", "inboundTag": ["api"], "outboundTag": "api"})


def build_text(
    profile: Profile,
    iface_alias: str,
    template_path: Path | None = None,
    routing_rules: list[dict] | None = None,
    stats: bool = False,
    include_tun: bool = True,
    log_level: str | None = None,
) -> str:
    tmpl_path = template_path or paths.config_template()
    cfg = json.loads(tmpl_path.read_text(encoding="utf-8"))
    _apply_profile(cfg, profile)
    if not include_tun:
        _drop_tun_inbound(cfg)
    if routing_rules:
        _apply_routing(cfg, routing_rules)
    if stats:
        _apply_stats(cfg)
    if log_level:
        _apply_log_level(cfg, log_level)
    text = json.dumps(cfg, indent=2, ensure_ascii=False)
    return text.replace("__INTERFACE__", iface_alias).replace("__IFACE__", iface_alias)


def build(
    profile: Profile,
    iface_alias: str,
    template_path: Path | None = None,
    routing_rules: list[dict] | None = None,
    stats: bool = False,
    include_tun: bool = True,
    log_level: str | None = None,
) -> Path:
    out = paths.runtime_config()
    out.write_text(
        build_text(profile, iface_alias, template_path, routing_rules, stats,
                   include_tun, log_level),
        encoding="utf-8",
    )
    return out
