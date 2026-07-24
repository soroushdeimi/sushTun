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


def test_app_presets_expand():
    rules = routing.build_rules(_routing(app_presets=["Aparat"]))
    direct = next(x for x in rules if x["outboundTag"] == "direct" and "domain" in x)
    assert "domain:aparat.com" in direct["domain"]


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
