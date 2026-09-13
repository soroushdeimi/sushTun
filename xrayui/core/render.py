"""Render a runtime Xray config by injecting a Profile into the template.

Only the `proxy` outbound is rewritten; every other part of
config.template.json (inbounds, dns-out/direct/block, routing) is preserved
verbatim, and the __IFACE__ / __INTERFACE__ placeholders are substituted last.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import paths
from . import dns as dns_mod
from . import outbounds
from . import settings as app_settings
from .metrics import STATS_API_PORT
from .profiles import Profile


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


def _apply_dns(cfg: dict, dns_cfg: dict) -> None:
    """Overlay user DNS settings. Untouched keys keep the template's values."""
    block = dns_mod.build_dns(dns_cfg)
    if not block:
        return
    cfg.setdefault("dns", {}).update(block)


def _apply_mtu(cfg: dict, mtu: int) -> None:
    # Below 576 breaks IPv4 minimum reassembly; above 9000 exceeds jumbo frames.
    if not isinstance(mtu, int) or isinstance(mtu, bool) or not 576 <= mtu <= 9000:
        return
    for inbound in cfg.get("inbounds", []):
        if inbound.get("tag") == "tun-in":
            inbound.setdefault("settings", {})["mtu"] = mtu


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
    dns_cfg: dict | None = None,
    tun_mtu: int | None = None,
) -> str:
    tmpl_path = template_path or paths.config_template()
    cfg = json.loads(tmpl_path.read_text(encoding="utf-8"))
    outbounds.apply_profile(cfg, profile)
    if not include_tun:
        _drop_tun_inbound(cfg)
    if routing_rules:
        _apply_routing(cfg, routing_rules)
    if stats:
        _apply_stats(cfg)
    if log_level:
        _apply_log_level(cfg, log_level)
    if dns_cfg:
        _apply_dns(cfg, dns_cfg)
    if tun_mtu:
        _apply_mtu(cfg, tun_mtu)
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
    dns_cfg: dict | None = None,
    tun_mtu: int | None = None,
) -> Path:
    out = paths.runtime_config()
    # Forward by keyword: a positional forward silently mis-binds the next time
    # a parameter is added in the middle.
    out.write_text(
        build_text(
            profile,
            iface_alias,
            template_path=template_path,
            routing_rules=routing_rules,
            stats=stats,
            include_tun=include_tun,
            log_level=log_level,
            dns_cfg=dns_cfg,
            tun_mtu=tun_mtu,
        ),
        encoding="utf-8",
    )
    return out
