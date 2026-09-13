import copy
import json
from pathlib import Path

from xrayui.core import render, routing
from xrayui.core.importer import parse_vless
from xrayui.core.settings import DEFAULTS

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


def _routing(**over):
    r = copy.deepcopy(DEFAULTS["routing"])
    r.update(over)
    return r


def _tags(rules):
    return [x["outboundTag"] for x in rules]


def test_defaults_block_ads_and_direct_private():
    rules = routing.build_rules(_routing())
    assert "block" in _tags(rules)
    direct = next(x for x in rules if x["outboundTag"] == "direct" and "domain" in x)
    assert "geosite:private" in direct["domain"]


def test_low_usage_adds_windows_categories():
    rules = routing.build_rules(_routing(low_usage=True))
    direct = next(x for x in rules if x["outboundTag"] == "direct" and "domain" in x)
    assert "geosite:win-spy" in direct["domain"]
    assert any("telemetry.microsoft.com" in d for d in direct["domain"])


def test_country_toggles():
    rules = routing.build_rules(_routing(direct_iran=True, direct_russia=True, direct_china=True))
    direct_d = next(x for x in rules if x["outboundTag"] == "direct" and "domain" in x)["domain"]
    direct_i = next(x for x in rules if x["outboundTag"] == "direct" and "ip" in x)["ip"]
    assert {"geosite:category-ir", "geosite:category-ru", "geosite:cn"} <= set(direct_d)
    assert {"geoip:ir", "geoip:ru", "geoip:cn"} <= set(direct_i)


def test_custom_domains_normalized_and_passthrough():
    rules = routing.build_rules(_routing(bypass_domains=["example.com", "geosite:google"]))
    direct = next(x for x in rules if x["outboundTag"] == "direct" and "domain" in x)
    assert "domain:example.com" in direct["domain"]
    assert "geosite:google" in direct["domain"]


def test_proxy_domains_rule():
    rules = routing.build_rules(_routing(proxy_domains=["netflix.com"]))
    assert any(x["outboundTag"] == "proxy" for x in rules)


def test_render_keeps_dns_rule_first_and_sets_strategy():
    rules = routing.build_rules(_routing(low_usage=True))
    cfg = json.loads(render.build_text(
        parse_vless("vless://u@1.2.3.4:443?type=tcp&security=none#x"),
        "Wi-Fi", TEMPLATE, routing_rules=rules))
    assert cfg["routing"]["rules"][0].get("inboundTag") == ["dns-in"]
    assert cfg["routing"]["domainStrategy"] == "IPIfNonMatch"


def test_stale_settings_keys_are_dropped(tmp_path, monkeypatch):
    import json

    from xrayui.core import settings as app_settings

    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({
        "routing": {"app_presets": ["Aparat"], "direct_iran": False},
    }), encoding="utf-8")
    loaded = app_settings.load()
    assert "app_presets" not in loaded["routing"]
    assert loaded["routing"]["direct_iran"] is False  # real values still applied


# -- rule sets (Phase 2a) -----------------------------------------------
def test_an_old_settings_json_loads_with_simple_mode_and_identical_rules(tmp_path, monkeypatch):
    import json

    from xrayui.core import settings as app_settings

    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    old = {"routing": {"block_ads": True, "direct_iran": True, "low_usage": False}}
    (tmp_path / "settings.json").write_text(json.dumps(old), encoding="utf-8")

    loaded = app_settings.load()
    assert loaded["routing"]["mode"] == "simple"
    assert routing.build_rules(loaded["routing"]) == routing.build_rules(_routing())


def _rule(**over) -> dict:
    base = {"remarks": "", "enabled": True, "outbound": "proxy", "domain": [], "ip": [],
            "port": "", "network": "", "protocol": [], "process": []}
    base.update(over)
    return base


def _with_set(rules: list, **set_over) -> dict:
    r = _routing(mode="custom1")
    r["sets"] = [{"id": "custom1", "name": "Custom", "domain_strategy": "", "rules": rules,
                  **set_over}]
    return r


def test_custom_set_splits_domain_ip_process_and_keeps_shared_fields():
    rule = _rule(outbound="block", domain=["example.com"], ip=["1.2.3.0/24"],
                 process=["firefox"], port="443", network="tcp", protocol=["http"])
    out = routing.build_rules(_with_set([rule]))

    assert len(out) == 3
    for r in out:
        assert r["port"] == "443"
        assert r["network"] == "tcp"
        assert r["protocol"] == ["http"]
        assert r["outboundTag"] == "block"
    domain_r = next(r for r in out if "domain" in r)
    ip_r = next(r for r in out if "ip" in r)
    proc_r = next(r for r in out if "process" in r)
    assert domain_r["domain"] == ["domain:example.com"]
    assert ip_r["ip"] == ["1.2.3.0/24"]
    assert proc_r["process"] == ["firefox"]
    assert "domain" not in ip_r and "ip" not in domain_r


def test_custom_set_rule_with_only_shared_fields_emitted_as_is():
    rule = _rule(outbound="proxy", port="0-65535")
    out = routing.build_rules(_with_set([rule]))
    assert out == [{"type": "field", "outboundTag": "proxy", "port": "0-65535"}]


def test_custom_set_skips_disabled_rules():
    rules = [_rule(enabled=False, domain=["skip.example.com"]),
             _rule(enabled=True, domain=["keep.example.com"])]
    out = routing.build_rules(_with_set(rules))
    assert len(out) == 1
    assert out[0]["domain"] == ["domain:keep.example.com"]


def test_custom_set_drops_hash_comments_and_unescapes_comma():
    rule = _rule(domain=["#a comment", "keep.example.com<COMMA>more"])
    out = routing.build_rules(_with_set([rule]))
    assert out[0]["domain"] == ["domain:keep.example.com,more"]


def test_custom_set_sanitizes_bad_ip_port_network():
    rule = _rule(
        outbound="proxy",
        ip=["not-an-ip", "geoip:cn", "10.0.0.0/8", "ext:file.dat:tag"],
        port="not-a-port", network="quic",
    )
    out = routing.build_rules(_with_set([rule]))
    assert len(out) == 1
    assert out[0]["ip"] == ["geoip:cn", "10.0.0.0/8", "ext:file.dat:tag"]
    assert "port" not in out[0]
    assert "network" not in out[0]


def test_custom_set_drops_a_rule_with_a_bad_outbound():
    rule = _rule(outbound="balancer:foo", domain=["example.com"])
    assert routing.build_rules(_with_set([rule])) == []


def test_unknown_or_missing_set_falls_back_to_simple():
    r = _routing(mode="does-not-exist", block_ads=True)
    assert routing.build_rules(r) == routing.build_rules(_routing(block_ads=True))


def test_low_usage_applies_in_custom_mode_as_a_rule_before_the_sets_rules():
    r = _with_set([_rule(domain=["example.com"])])
    r["low_usage"] = True
    out = routing.build_rules(r)
    assert out[0]["outboundTag"] == "direct"
    assert "geosite:win-spy" in out[0]["domain"]
    assert out[1]["domain"] == ["domain:example.com"]


def test_domain_strategy_whitelist_and_active_set_precedence():
    r = _routing(domain_strategy="AsIs")
    assert routing.domain_strategy_for(r) == "AsIs"

    r2 = _routing(domain_strategy="bogus")
    assert routing.domain_strategy_for(r2) == "IPIfNonMatch"

    r3 = _with_set([_rule()], domain_strategy="IPOnDemand")
    r3["domain_strategy"] = "AsIs"  # the active set's own value wins
    assert routing.domain_strategy_for(r3) == "IPOnDemand"


def test_render_apply_routing_rejects_an_unknown_domain_strategy():
    cfg = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    render._apply_routing(cfg, [], "not-a-real-strategy")
    assert cfg["routing"]["domainStrategy"] == "IPIfNonMatch"


def test_user_rules_stay_after_the_dns_rules_in_custom_mode():
    rules = routing.build_rules(_with_set([_rule(domain=["example.com"])]))
    cfg = json.loads(render.build_text(
        parse_vless("vless://u@1.2.3.4:443?type=tcp&security=none#x"),
        "Wi-Fi", TEMPLATE, routing_rules=rules,
        domain_strategy=routing.domain_strategy_for(_with_set([]))))
    template_rules = json.loads(TEMPLATE.read_text(encoding="utf-8"))["routing"]["rules"]
    got = cfg["routing"]["rules"]
    assert got[:len(template_rules)] == template_rules
    assert got[len(template_rules):] == rules
