"""Render a runtime Xray config by injecting a Profile into the template.

Only the `proxy` outbound is rewritten; every other part of
config.template.json (inbounds, dns-out/direct/block, routing) is preserved
verbatim, and the __IFACE__ / __INTERFACE__ placeholders are substituted last.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import paths
from . import coreopts, outbounds
from . import dns as dns_mod
from . import exits as exits_mod
from . import forwards as forwards_mod
from . import routing as routing_mod
from . import settings as app_settings
from .metrics import STATS_API_PORT
from .profiles import Profile


def _apply_dns_routing(cfg: dict, dns_rules: list[dict]) -> None:
    """Insert DNS-related routing rules (domestic DNS / remote-via-tunnel)
    right after the template's own rules and before any user rule. Called
    before _apply_routing appends user rules, so "extend now" already
    means "insert at the right index" -- routing.rules only holds the
    template's own rules at this point. Without this, a user catch-all
    ("port 0-65535 -> proxy") could capture a DNS query these rules exist
    specifically to steer around it.
    """
    cfg.setdefault("routing", {}).setdefault("rules", []).extend(dns_rules)


def _apply_routing(cfg: dict, rules: list[dict], domain_strategy: str | None) -> None:
    routing = cfg.setdefault("routing", {})
    # User rules go after the template's own (dns-in / port-53 rules) and
    # any DNS routing rules _apply_dns_routing already added, so a custom
    # rule can never intercept a DNS query before it reaches dns-out.
    routing.setdefault("rules", []).extend(rules)
    strategy = domain_strategy if domain_strategy in routing_mod.DOMAIN_STRATEGIES else None
    routing["domainStrategy"] = strategy or "IPIfNonMatch"


def _drop_tun_inbound(cfg: dict) -> None:
    # Xray has no native TUN inbound on macOS; there we bridge socks-in to a
    # real TUN device with tun2socks instead, so the tun-in entry is unused.
    cfg["inbounds"] = [i for i in cfg.get("inbounds", []) if i.get("tag") != "tun-in"]


def _apply_log_level(cfg: dict, level: str) -> None:
    if level not in app_settings.LOG_LEVELS:
        return
    cfg.setdefault("log", {})["loglevel"] = level


def _apply_dns_block(cfg: dict, block: dict) -> None:
    """Overlay an already-built dns block. Untouched keys keep the
    template's values."""
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
    domain_strategy: str | None = None,
    stats: bool = False,
    include_tun: bool = True,
    log_level: str | None = None,
    dns_cfg: dict | None = None,
    tun_mtu: int | None = None,
    server_ip: str | None = None,
    core_cfg: dict | None = None,
    exits: list[exits_mod.Exit] | None = None,
    exits_cfg: dict | None = None,
    forwards: list[forwards_mod.Forward] | None = None,
) -> str:
    tmpl_path = template_path or paths.config_template()
    cfg = json.loads(tmpl_path.read_text(encoding="utf-8"))
    outbounds.apply_profile(cfg, profile)
    if not include_tun:
        _drop_tun_inbound(cfg)
    if core_cfg:
        coreopts.apply_all(cfg, core_cfg, profile)

    dns_block: dict = {}
    if dns_cfg:
        direct_domains = routing_mod.direct_domains(routing_rules or [])
        dns_block, dns_routing_rules = dns_mod.build_dns_and_rules(
            dns_cfg, direct_domains, profile.address, server_ip=server_ip)
        if dns_routing_rules:
            # Before _apply_routing: routing.rules only holds the
            # template's own rules right now, so this is where "after the
            # template's rules, before any user rule" actually happens.
            _apply_dns_routing(cfg, dns_routing_rules)

    if exits:
        # Same slot as the DNS rules: after the template's own rules and
        # before every user rule, so a chosen exit beats Iran-direct.
        cfg.setdefault("routing", {}).setdefault("rules", []).extend(
            exits_mod.apply(cfg, exits, exits_cfg or {}, core_cfg, profile))
    if forwards:
        # Same slot: a forward's "through the tunnel / direct" choice must
        # hold whatever the user's routing rules say.
        cfg.setdefault("routing", {}).setdefault("rules", []).extend(
            forwards_mod.apply(cfg, forwards))

    if routing_rules:
        _apply_routing(cfg, routing_rules, domain_strategy)
    if stats:
        _apply_stats(cfg)
    if log_level:
        _apply_log_level(cfg, log_level)
    if dns_block:
        _apply_dns_block(cfg, dns_block)
    if tun_mtu:
        _apply_mtu(cfg, tun_mtu)
    text = json.dumps(cfg, indent=2, ensure_ascii=False)
    return text.replace("__INTERFACE__", iface_alias).replace("__IFACE__", iface_alias)


def build(
    profile: Profile,
    iface_alias: str,
    template_path: Path | None = None,
    routing_rules: list[dict] | None = None,
    domain_strategy: str | None = None,
    stats: bool = False,
    include_tun: bool = True,
    log_level: str | None = None,
    dns_cfg: dict | None = None,
    tun_mtu: int | None = None,
    server_ip: str | None = None,
    core_cfg: dict | None = None,
    exits: list[exits_mod.Exit] | None = None,
    exits_cfg: dict | None = None,
    forwards: list[forwards_mod.Forward] | None = None,
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
            domain_strategy=domain_strategy,
            stats=stats,
            include_tun=include_tun,
            log_level=log_level,
            dns_cfg=dns_cfg,
            tun_mtu=tun_mtu,
            server_ip=server_ip,
            core_cfg=core_cfg,
            exits=exits,
            exits_cfg=exits_cfg,
            forwards=forwards,
        ),
        encoding="utf-8",
    )
    return out
