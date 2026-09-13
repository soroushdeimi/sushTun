import json

from xrayui.core import routing_io

# Small fixtures written in the same shape v2rayN uses, not copied from it
# (v2rayN is GPL-3.0; sushTun is MIT).
BARE_ARRAY = json.dumps([
    {"remarks": "ads", "outboundTag": "block", "domain": ["geosite:category-ads-all"]},
    {"remarks": "unsupported tag", "outboundTag": "balancer:foo", "domain": ["x.com"]},
    {"remarks": "lan", "outboundTag": "direct", "ip": ["geoip:private"]},
])

ROUTING_ITEM_STRING_RULESET = json.dumps({
    "Remarks": "MySet",
    "DomainStrategy": "IPOnDemand",
    "RuleSet": json.dumps([
        {"remarks": "r1", "outboundTag": "proxy", "domain": ["netflix.com"]},
    ]),
})

TEMPLATE_WITH_URL_ITEM = json.dumps({
    "Version": "2",
    "RoutingItems": [
        {"Remarks": "Local", "RuleSet": [{"outboundTag": "block", "ip": ["geoip:cn"]}]},
        {"Remarks": "Remote", "Url": "https://example.invalid/rules.json"},
    ],
})


def test_import_bare_array_counts_skipped_rules():
    sets, skipped = routing_io.import_rules(BARE_ARRAY)
    assert len(sets) == 1
    assert skipped == 1
    rules = sets[0]["rules"]
    assert len(rules) == 2
    assert {r["outbound"] for r in rules} == {"block", "direct"}


def test_import_single_routing_item_with_string_ruleset():
    sets, skipped = routing_io.import_rules(ROUTING_ITEM_STRING_RULESET)
    assert skipped == 0
    assert len(sets) == 1
    assert sets[0]["name"] == "MySet"
    assert sets[0]["domain_strategy"] == "IPOnDemand"
    assert sets[0]["rules"][0]["domain"] == ["netflix.com"]


def test_import_template_fetches_url_only_items():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return json.dumps([{"outboundTag": "proxy", "domain": ["a.com"]}])

    sets, skipped = routing_io.import_rules(TEMPLATE_WITH_URL_ITEM, fetch=fake_fetch)
    assert skipped == 0
    assert calls == ["https://example.invalid/rules.json"]
    assert {s["name"] for s in sets} == {"Local", "Remote"}
    remote = next(s for s in sets if s["name"] == "Remote")
    assert remote["rules"][0]["domain"] == ["a.com"]


def test_import_case_insensitive_keys():
    text = json.dumps([{"Remarks": "x", "OutboundTag": "direct", "Ip": ["geoip:private"]}])
    sets, skipped = routing_io.import_rules(text)
    assert skipped == 0
    assert sets[0]["rules"][0]["ip"] == ["geoip:private"]


def test_import_url_uses_the_v2rayng_user_agent():
    seen = {}

    def fake_fetch(url):
        seen["url"] = url
        return json.dumps([{"outboundTag": "proxy", "domain": ["a.com"]}])

    sets, skipped = routing_io.import_url("https://example.invalid/x.json", fetch=fake_fetch)
    assert seen["url"] == "https://example.invalid/x.json"
    assert routing_io._UA == "v2rayNG/1.8.5"
    assert len(sets) == 1


def test_export_then_import_round_trips_rule_content():
    original = [
        {"remarks": "a", "enabled": True, "outbound": "block", "domain": ["geosite:ads"],
         "ip": [], "port": "", "network": "", "protocol": [], "process": []},
        {"remarks": "b", "enabled": True, "outbound": "proxy", "domain": [], "ip": [],
         "port": "443", "network": "tcp", "protocol": ["http"], "process": []},
    ]
    exported = routing_io.export_rules({"rules": original})
    reimported, skipped = routing_io.import_rules(json.dumps(exported))

    assert skipped == 0
    assert len(reimported) == 1
    got = reimported[0]["rules"]
    assert [r["outbound"] for r in got] == ["block", "proxy"]
    assert got[0]["domain"] == ["geosite:ads"]
    assert got[1]["port"] == "443"
    assert got[1]["protocol"] == ["http"]


def test_import_invalid_json_returns_nothing():
    sets, skipped = routing_io.import_rules("not json at all")
    assert sets == []
    assert skipped == 0
