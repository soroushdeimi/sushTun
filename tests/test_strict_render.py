"""Strict mode end-to-end through render.build_text.

Proves the protected-domains rule is placed ahead of every user/forwards/exits
rule (but after the template's DNS-inbound rules), that no-direct drops every
direct rule, that a protected name is kept out of the domestic DNS resolver,
and that an untouched install (strict off) renders byte-for-byte the same
config as before.
"""
from __future__ import annotations

import copy
import json

from xrayui.core import render, routing, strict
from xrayui.core import settings as app_settings
from xrayui.core.importer import parse_vless
from xrayui.core.profiles import Profile

# Newer Xray cores require TLS or private address for unencrypted VLESS.
SAMPLE = "vless://u@127.0.0.1:443?type=tcp&security=none#x"


def _profile():
    return parse_vless(SAMPLE)


def _routing(**over):
    r = copy.deepcopy(app_settings.DEFAULTS["routing"])
    r.update(over)
    return r


def _strict(**over):
    c = copy.deepcopy(app_settings.DEFAULTS["strict"])
    c.update(over)
    return c


def _rules(cfg):
    return json.loads(render.build_text(_profile(), "lo", include_tun=False,
                                        routing_rules=routing.build_rules(_routing()),
                                        strict_cfg=cfg))["routing"]["rules"]


def _find(rules, **want):
    for r in rules:
        if all(r.get(k) == v for k, v in want.items()):
            return r
    return None


def test_strict_off_renders_no_protected_rule():
    rules = _rules(_strict(enabled=False))
    assert _find(rules, outboundTag="proxy") is None
    # and the default direct rule is still there (Iran/private direct)
    assert _find(rules, outboundTag="direct") is not None


def test_strict_on_places_protected_rule_ahead_of_user_rules():
    # A user bypass domain that would normally go direct, plus a user custom
    # rule set that also sends a protected name direct -- strict must win.
    r = _routing(bypass_domains=["openai.com"])
    rules = json.loads(render.build_text(
        _profile(), "lo", include_tun=False,
        routing_rules=routing.build_rules(r),
        strict_cfg=_strict(enabled=True)))["routing"]["rules"]

    strict_rule = _find(rules, outboundTag="proxy")
    assert strict_rule is not None
    assert "domain:openai.com" in strict_rule["domain"]

    # The protected rule must come before the user's direct rule for the same
    # name, so the tunnel wins.
    direct_rule = _find(rules, outboundTag="direct")
    assert direct_rule is not None
    assert rules.index(strict_rule) < rules.index(direct_rule)


def test_strict_rule_stays_after_template_dns_rules():
    rules = _rules(_strict(enabled=True))
    strict_rule = _find(rules, outboundTag="proxy")
    dns_in = _find(rules, inboundTag=["dns-in"])
    tun53 = _find(rules, inboundTag=["tun-in"])
    assert strict_rule is not None and dns_in is not None and tun53 is not None
    # DNS-inbound rules must precede the protected rule, or a DNS lookup for a
    # protected name would be misrouted to "proxy" instead of "dns-out".
    assert rules.index(dns_in) < rules.index(strict_rule)
    assert rules.index(tun53) < rules.index(strict_rule)


def test_strict_beats_forwards_and_exits():
    # A forward whose "direct" choice would otherwise capture a protected name
    # must lose to the protected rule.
    from xrayui.core import forwards as forwards_mod
    fwd = forwards_mod.Forward(port=8080, host="1.2.3.4", target_port=80,
                               via="direct", network="tcp")
    rules = json.loads(render.build_text(
        _profile(), "lo", include_tun=False,
        routing_rules=routing.build_rules(_routing()),
        forwards=[fwd],
        strict_cfg=_strict(enabled=True)))["routing"]["rules"]
    strict_rule = _find(rules, outboundTag="proxy")
    fwd_rule = _find(rules, inboundTag=["fwd-8080"])
    assert strict_rule is not None and fwd_rule is not None
    assert rules.index(strict_rule) < rules.index(fwd_rule)


def test_no_direct_drops_every_direct_rule():
    r = _routing(bypass_domains=["example.com"])
    rules = json.loads(render.build_text(
        _profile(), "lo", include_tun=False,
        routing_rules=routing.build_rules(r),
        strict_cfg=_strict(enabled=True, no_direct=True)))["routing"]["rules"]
    assert _find(rules, outboundTag="direct") is None
    # the protected rule is still present and goes to proxy
    assert _find(rules, outboundTag="proxy") is not None
    # block rules survive (they are not "direct")
    assert _find(rules, outboundTag="block") is not None


def test_no_direct_without_enabled_is_ignored():
    rules = _rules(_strict(enabled=False, no_direct=True))
    assert _find(rules, outboundTag="direct") is not None


def test_protected_name_kept_out_of_domestic_dns():
    # Iran direct puts "domain:ir" and the private geosite in the domestic DNS
    # resolver's domain list. A protected name that the user also bypassed
    # must be stripped from that list so it resolves through the tunnel.
    r = _routing(bypass_domains=["openai.com"])
    dns_cfg = copy.deepcopy(app_settings.DEFAULTS["dns"])
    dns_cfg["domestic_servers"] = ["178.22.122.100"]
    text = render.build_text(
        _profile(), "lo", include_tun=False,
        routing_rules=routing.build_rules(r),
        dns_cfg=dns_cfg,
        strict_cfg=_strict(enabled=True))
    cfg = json.loads(text)
    # The domestic server object carries the direct domains in "domains".
    domestic = [s for s in cfg["dns"]["servers"] if isinstance(s, dict)
                and s.get("tag") == "direct-dns"]
    assert domestic, "expected a domestic DNS server object"
    all_domains = [d for s in domestic for d in s.get("domains", [])]
    assert not any("openai" in d for d in all_domains), all_domains
    # unrelated direct domains survive
    assert any("ir" in d for d in all_domains)


def test_domestic_dns_unchanged_when_strict_off():
    r = _routing(bypass_domains=["openai.com"])
    dns_cfg = copy.deepcopy(app_settings.DEFAULTS["dns"])
    dns_cfg["domestic_servers"] = ["178.22.122.100"]
    text_off = render.build_text(
        _profile(), "lo", include_tun=False,
        routing_rules=routing.build_rules(r), dns_cfg=dns_cfg)
    text_on = render.build_text(
        _profile(), "lo", include_tun=False,
        routing_rules=routing.build_rules(r), dns_cfg=dns_cfg,
        strict_cfg=_strict(enabled=True))
    off = json.loads(text_off)
    on = json.loads(text_on)
    off_dom = [d for s in off["dns"]["servers"] if isinstance(s, dict)
               for d in s.get("domains", [])]
    on_dom = [d for s in on["dns"]["servers"] if isinstance(s, dict)
              for d in s.get("domains", [])]
    # strict off: the bypassed protected name stays in the domestic resolver
    assert any("openai" in d for d in off_dom)
    # strict on: it is removed
    assert not any("openai" in d for d in on_dom)


def test_untouched_install_renders_identical_config():
    # The whole point of "off by default": with no strict_cfg (or strict off)
    # the rendered bytes are exactly what they were before this feature.
    base = render.build_text(_profile(), "lo", include_tun=False,
                             routing_rules=routing.build_rules(_routing()))
    off = render.build_text(_profile(), "lo", include_tun=False,
                            routing_rules=routing.build_rules(_routing()),
                            strict_cfg=_strict(enabled=False))
    assert base == off


def test_strict_incompatible_with_serverless_only(caplog):
    # serverless-only makes "proxy" a fragmenting direct outbound, so strict
    # cannot protect. render must not add the protected rule in that case, and
    # must log a WARNING (never claim protection that is not active).
    import logging

    only = Profile(name="Serverless only", protocol="serverless", address="",
                   uid="serverless-only")
    assert strict.problem(only) is not None
    with caplog.at_level(logging.WARNING, logger="xrayui.core.render"):
        rules = json.loads(render.build_text(
            only, "lo", include_tun=False,
            routing_rules=routing.build_rules(_routing()),
            strict_cfg=_strict(enabled=True)))["routing"]["rules"]
    # No protected "proxy" rule is rendered for the incompatible mode.
    assert _find(rules, outboundTag="proxy") is None
    # The incompatibility is surfaced, not silently ignored.
    assert any("strict" in r.message for r in caplog.records)
