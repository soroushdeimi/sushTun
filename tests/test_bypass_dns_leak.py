"""Tests for issue #4: bypass domain normalization, deduplication, and DNS routing."""
import copy
import json
from pathlib import Path

from xrayui.core import render, routing
from xrayui.core.importer import parse_vless
from xrayui.core.settings import DEFAULTS

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"
SAMPLE = "vless://11111111-1111-1111-1111-111111111111@203.0.113.10:443?type=tcp&security=none#x"


def _routing(**over):
    r = copy.deepcopy(DEFAULTS["routing"])
    r.update(over)
    return r


def _dns(**over):
    d = copy.deepcopy(DEFAULTS["dns"])
    d.update(over)
    return d


def _render(routing_cfg, dns_cfg=None):
    rules = routing.build_rules(routing_cfg)
    strategy = routing.domain_strategy_for(routing_cfg)
    return json.loads(render.build_text(
        parse_vless(SAMPLE), "Wi-Fi", TEMPLATE,
        routing_rules=rules, domain_strategy=strategy,
        dns_cfg=dns_cfg or _dns(), include_tun=False,
    ))


def test_bypass_domain_normalization_and_deduplication():
    # Wildcards (*. / .), uppercase, and domain: prefix variants should normalize
    # to clean lowercase domain: entries without duplicates.
    r_cfg = _routing(bypass_domains=[
        "browserleaks.com",
        "BrowserLeaks.com",
        "*.browserleaks.com",
        ".browserleaks.com",
        "domain:*.BROWSERLEAKS.COM",
        "*",
        "",
        "  ",
        "# comment",
        "*.EXAMPLE.org",
    ])
    rules = routing.build_rules(r_cfg)
    direct = next(x for x in rules if x["outboundTag"] == "direct" and "domain" in x)
    domains = direct["domain"]

    assert domains.count("domain:browserleaks.com") == 1
    assert domains.count("domain:example.org") == 1
    assert "domain:*.browserleaks.com" not in domains
    assert "domain:BrowserLeaks.com" not in domains
    assert "domain:*" not in domains
    assert "domain:" not in domains


def test_rendered_config_rules_order_and_dns_with_domestic_and_bypass():
    r_cfg = _routing(bypass_domains=["*.browserleaks.com", "BrowserLeaks.com"])
    d_cfg = _dns(domestic_servers=["178.22.122.100"], servers=["1.1.1.1"])
    cfg = _render(r_cfg, d_cfg)

    # 1. DNS server block: domestic server prepended with clean direct_domains
    servers = cfg["dns"]["servers"]
    assert len(servers) >= 2
    domestic = servers[0]
    assert domestic["address"] == "178.22.122.100"
    assert domestic["tag"] == "direct-dns"
    assert domestic["skipFallback"] is True
    assert domestic["domains"].count("domain:browserleaks.com") == 1
    assert "domain:*.browserleaks.com" not in domestic["domains"]
    assert "domain:BrowserLeaks.com" not in domestic["domains"]

    # 2. Routing rules ordering:
    # template dns rules -> direct-dns rule -> user rules (ads -> block, direct -> direct)
    rules = cfg["routing"]["rules"]
    assert rules[0]["inboundTag"] == ["dns-in"] and rules[0]["outboundTag"] == "dns-out"
    assert rules[1]["inboundTag"] == ["tun-in"] and rules[1]["port"] == 53 and rules[1]["outboundTag"] == "dns-out"
    assert rules[2]["inboundTag"] == ["direct-dns"] and rules[2]["outboundTag"] == "direct"

    # User direct rule follows DNS routing rules and has deduplicated normalized domain
    direct_domain_rule = next(
        r for r in rules[3:] if r.get("outboundTag") == "direct" and "domain" in r
    )
    assert direct_domain_rule["domain"].count("domain:browserleaks.com") == 1


def test_rendered_config_without_domestic_servers():
    r_cfg = _routing(bypass_domains=["browserleaks.com"])
    d_cfg = _dns(domestic_servers=[])
    cfg = _render(r_cfg, d_cfg)

    # Without domestic servers, no direct-dns tag or rule exists
    servers = cfg["dns"]["servers"]
    assert not any(isinstance(s, dict) and s.get("tag") == "direct-dns" for s in servers)
    rules = cfg["routing"]["rules"]
    assert not any(r.get("inboundTag") == ["direct-dns"] for r in rules)

    # But domain traffic still routes direct
    direct_rule = next(r for r in rules if r.get("outboundTag") == "direct" and "domain" in r)
    assert "domain:browserleaks.com" in direct_rule["domain"]


def test_rendered_config_domestic_set_but_no_bypass_domains():
    r_cfg = _routing(bypass_domains=[])
    d_cfg = _dns(domestic_servers=["178.22.122.100"])
    cfg = _render(r_cfg, d_cfg)

    # Defaults include Iran/private direct domains, so domestic DNS rule is active
    domestic = cfg["dns"]["servers"][0]
    assert domestic["tag"] == "direct-dns"
    assert "domain:ir" in domestic["domains"]
    assert any(r.get("inboundTag") == ["direct-dns"] for r in cfg["routing"]["rules"])

    # If all direct toggles are off and no bypass domains, no domestic DNS is injected
    r_all_off = _routing(
        direct_private=False, direct_iran=False, direct_russia=False,
        direct_china=False, low_usage=False, bypass_domains=[],
    )
    cfg_empty = _render(r_all_off, d_cfg)
    servers_empty = cfg_empty["dns"]["servers"]
    assert not any(isinstance(s, dict) and s.get("tag") == "direct-dns" for s in servers_empty)
    assert not any(r.get("inboundTag") == ["direct-dns"] for r in cfg_empty["routing"]["rules"])


def test_rendered_config_raw_override_present():
    r_cfg = _routing(bypass_domains=["browserleaks.com"])
    d_cfg = _dns(
        domestic_servers=["178.22.122.100"],
        raw_override='{"servers": ["9.9.9.9"]}',
    )
    cfg = _render(r_cfg, d_cfg)

    # Raw override completely replaces the DNS servers list, no direct-dns injected
    assert cfg["dns"]["servers"] == ["9.9.9.9"]
    assert not any(r.get("inboundTag") == ["direct-dns"] for r in cfg["routing"]["rules"])
    # Routing still sends the bypass domain direct
    direct_rule = next(r for r in cfg["routing"]["rules"]
                       if r.get("outboundTag") == "direct" and "domain" in r)
    assert "domain:browserleaks.com" in direct_rule["domain"]


def test_empty_lists_render_clean_config():
    r_cfg = _routing(bypass_domains=[], bypass_ips=[], proxy_domains=[])
    cfg = _render(r_cfg)
    # Default direct domains and IPs exist and contain no empty entries
    direct_rule = next(r for r in cfg["routing"]["rules"]
                       if r.get("outboundTag") == "direct" and "domain" in r)
    assert all(d for d in direct_rule["domain"])
    assert not any(r.get("outboundTag") == "proxy" and "domain" in r for r in cfg["routing"]["rules"])


def test_custom_rules_normalization_and_deduplication():
    set_id = "custom-1"
    custom_set = {
        "id": set_id,
        "name": "Custom",
        "domain_strategy": "IPIfNonMatch",
        "rules": [
            {
                "enabled": True,
                "outbound": "direct",
                "domain": ["*.EXAMPLE.com", "example.com", "DOMAIN:*.example.com", "*"],
            }
        ],
    }
    r_cfg = _routing(mode=set_id, sets=[custom_set])
    rules = routing.build_rules(r_cfg)
    direct = next(r for r in rules if r.get("outboundTag") == "direct" and "domain" in r)
    assert direct["domain"] == ["domain:example.com"]


def test_bypass_ui_hint_and_translation(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel
    _ = QApplication.instance() or QApplication([])
    from xrayui import i18n
    from xrayui.ui.pages.routing_page import RoutingPage
    page = RoutingPage(DEFAULTS["routing"])
    labels = [w.text() for w in page.findChildren(QLabel)]
    hint = (
        'Bypassed sites resolve via the tunnel unless Domestic DNS or '
        '"Resolve bypassed sites with this computer\'s own DNS" is set in DNS settings.'
    )
    assert any(hint in txt for txt in labels)

    # Translation exists in i18n_fa
    i18n.set_language("fa")
    translated = i18n.tr(hint)
    assert translated != hint
    assert "DNS" in translated
    i18n.set_language("en")


def test_norm_domain_preserves_case_for_ext_geosite_regexp():
    assert routing._norm_domain("ext:MyList.dat:Tag") == "ext:MyList.dat:Tag"
    assert routing._norm_domain("geosite:CN") == "geosite:CN"
    assert routing._norm_domain("regexp:^Foo[A-Z]$") == "regexp:^Foo[A-Z]$"


def test_norm_domain_preserves_old_behaviour_for_lowercase_inputs():
    table = [
        "full:example.com",
        "keyword:google",
        "geosite:cn",
        "ext:geoip.dat:cn",
        "regexp:^foo.*bar$",
        "example.com",
        "domain:x.com",
    ]
    for entry in table:
        old_output = entry.strip() if entry.strip().startswith(routing._PREFIXES) else f"domain:{entry.strip()}"
        assert routing._norm_domain(entry) == old_output

