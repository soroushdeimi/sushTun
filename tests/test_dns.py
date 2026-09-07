"""User-customizable DNS: settings -> the Xray `dns` object.

Empty settings must mean "inherit the template". The alternative -- emitting
`"servers": []` -- makes Xray fall back to the OS resolver, which
set_dns_loopback has just pinned to 127.0.0.1, which is dns-in, which routes to
dns-out, which asks the built-in resolver, which asks the OS resolver again.
A closed loop and a total DNS blackout that reads as "the VPN is broken".
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xrayui.core import dns as dns_mod
from xrayui.core import render, routing
from xrayui.core import settings as app_settings
from xrayui.core.importer import parse_vless

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"
SAMPLE = "vless://u@1.2.3.4:443?type=tcp&security=none#x"


def _dns(**over):
    d = copy.deepcopy(app_settings.DEFAULTS["dns"])
    d.update(over)
    return d


def _render(**kw):
    return json.loads(render.build_text(parse_vless(SAMPLE), "Wi-Fi", TEMPLATE, **kw))


# -- the no-op contract ----------------------------------------------------
def test_empty_settings_produce_no_dns_override():
    assert dns_mod.build_dns(_dns()) == {}


def test_defaults_leave_the_template_dns_untouched():
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    out = _render(dns_cfg=_dns())
    assert out["dns"] == template["dns"]


def test_servers_replace_the_list_but_keep_the_template_strategy():
    out = _render(dns_cfg=_dns(servers=["1.1.1.1"]))
    assert out["dns"]["servers"] == ["1.1.1.1"]
    assert out["dns"]["queryStrategy"] == "UseIPv4"  # merged, not replaced


def test_hosts_only_keeps_the_template_servers():
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    out = _render(dns_cfg=_dns(hosts=["a.com = 1.2.3.4"]))
    assert out["dns"]["servers"] == template["dns"]["servers"]
    assert out["dns"]["hosts"] == {"a.com": "1.2.3.4"}


def test_dns_override_does_not_disturb_routing_rules():
    rules = routing.build_rules(copy.deepcopy(app_settings.DEFAULTS["routing"]))
    out = _render(routing_rules=rules, dns_cfg=_dns(servers=["9.9.9.9"]))
    assert out["routing"]["rules"][0]["inboundTag"] == ["dns-in"]
    tun = next(r for r in out["routing"]["rules"] if r.get("inboundTag") == ["tun-in"])
    assert tun["port"] == 53 and tun["outboundTag"] == "dns-out"


# -- builder semantics -----------------------------------------------------
def test_server_order_is_preserved():
    servers = ["9.9.9.9", "1.1.1.1", "8.8.8.8"]
    assert dns_mod.build_dns(_dns(servers=servers))["servers"] == servers


def test_blank_and_duplicate_servers_are_dropped():
    out = dns_mod.build_dns(_dns(servers=["1.1.1.1", "  ", "1.1.1.1", ""]))
    assert out["servers"] == ["1.1.1.1"]


def test_known_query_strategy_is_applied():
    assert dns_mod.build_dns(_dns(query_strategy="UseIP"))["queryStrategy"] == "UseIP"


def test_bogus_query_strategy_is_ignored_rather_than_written_through():
    assert "queryStrategy" not in dns_mod.build_dns(_dns(query_strategy="UseCarrierPigeon"))


def test_hand_edited_settings_cannot_break_the_build():
    out = dns_mod.build_dns({
        "servers": [None, 5, "1.1.1.1", {"address": "8.8.8.8", "port": 53}],
        "hosts": ["= 1.2.3.4", "a.com =", "b.com = not!a!host", "ok.com = 1.2.3.4"],
        "query_strategy": 42,
    })
    assert out["servers"] == ["1.1.1.1", {"address": "8.8.8.8", "port": 53}]
    assert out["hosts"] == {"ok.com": "1.2.3.4"}
    assert "queryStrategy" not in out


def test_a_hosts_map_hand_written_into_settings_still_works():
    # _merge would mangle it, but build_dns should not also choke on it.
    out = dns_mod.build_dns({"hosts": {"a.com": "1.2.3.4", "bad.com": 7}})
    assert out["hosts"] == {"a.com": "1.2.3.4"}


def test_single_host_address_stays_a_string_multiples_become_a_list():
    out = dns_mod.build_dns(_dns(hosts=["a.com = 1.2.3.4", "b.com = 1.2.3.4, 5.6.7.8"]))
    assert out["hosts"]["a.com"] == "1.2.3.4"
    assert out["hosts"]["b.com"] == ["1.2.3.4", "5.6.7.8"]


def test_hosts_keys_are_not_prefixed_like_routing_domains():
    # routing._norm_domain turns "example.com" into "domain:example.com".
    # A hosts key is an exact match; prefixing would silently widen it.
    out = dns_mod.build_dns(_dns(hosts=["example.com = 1.2.3.4"]))
    assert list(out["hosts"]) == ["example.com"]


# -- server validation -----------------------------------------------------
# Every form below was confirmed accepted by a real `xray run -test` against
# Xray 26.3.27, not taken from the docs -- the docs list "8.8.8.8:5353" as
# valid and the binary rejects it.
@pytest.mark.parametrize("entry", [
    "8.8.8.8", "dns.google", "2606:4700:4700::1111",
    "tcp://8.8.8.8", "tcp://8.8.8.8:53", "tcp+local://8.8.8.8",
    "udp://8.8.8.8", "udp://8.8.8.8:5353", "h2c://1.1.1.1/dns-query",
    "https://1.1.1.1/dns-query", "https+local://9.9.9.9/dns-query",
    "quic+local://94.140.14.14",
])
def test_validate_server_accepts_the_forms_xray_actually_takes(entry):
    assert dns_mod.validate_server(entry) == ""


@pytest.mark.parametrize("entry", ["8.8.8.8:5353", "[2606:4700:4700::1111]:53"])
def test_a_bare_host_port_is_rejected_because_xray_parses_it_as_a_url(entry):
    # "first path segment in URL cannot contain colon" -- a port needs a scheme.
    why = dns_mod.validate_server(entry)
    assert "scheme" in why


def test_validate_server_rejects_localhost_because_it_loops_back_into_this_app():
    why = dns_mod.validate_server("localhost")
    assert "loop" in why


def test_validate_server_rejects_fakedns_and_junk():
    assert dns_mod.validate_server("fakedns")
    assert dns_mod.validate_server("not a server")
    assert dns_mod.validate_server("https://")


def test_every_preset_passes_validation_and_uses_literal_ips():
    assert dns_mod.PRESETS
    for name, servers in dns_mod.PRESETS.items():
        assert servers, name
        for entry in servers:
            assert dns_mod.validate_server(entry) == "", f"{name}: {entry}"
        # A hostname would need another resolver to bootstrap it.
        assert not any(c.isalpha() for s in servers
                       for c in s.split("://")[-1].split("/")[0]), name


def test_invalid_servers_explains_each_rejection():
    reasons = dns_mod.invalid_servers(["1.1.1.1", "localhost", "nope nope"])
    assert len(reasons) == 2
    assert any("localhost" in r for r in reasons)


# -- hosts text round trip -------------------------------------------------
def test_hosts_from_lines_accepts_equals_and_whitespace_forms():
    hosts = dns_mod.hosts_from_lines([
        "a.com = 1.2.3.4",
        "b.com 5.6.7.8",
        "c.com = 1.1.1.1, 2.2.2.2",
        "# a comment",
        "",
    ])
    assert hosts == {"a.com": "1.2.3.4", "b.com": "5.6.7.8",
                     "c.com": ["1.1.1.1", "2.2.2.2"]}


def test_hosts_from_lines_drops_a_bare_domain_with_no_address():
    assert dns_mod.hosts_from_lines(["example.com"]) == {}


def test_hosts_round_trip_through_text():
    hosts = {"a.com": "1.2.3.4", "b.com": ["1.1.1.1", "2.2.2.2"]}
    assert dns_mod.hosts_from_lines(dns_mod.hosts_to_lines(hosts)) == hosts


# -- settings integration --------------------------------------------------
def test_dns_settings_round_trip_through_the_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({
        "dns": {"servers": ["1.1.1.1"], "hosts": ["a.com = 1.2.3.4"], "bogus": 1},
    }), encoding="utf-8")
    loaded = app_settings.load()
    assert loaded["dns"]["servers"] == ["1.1.1.1"]
    assert loaded["dns"]["hosts"] == ["a.com = 1.2.3.4"]
    assert "bogus" not in loaded["dns"]
    assert loaded["dns"]["query_strategy"] == ""
    # And the saved shape survives all the way into the rendered config.
    assert dns_mod.build_dns(loaded["dns"])["hosts"] == {"a.com": "1.2.3.4"}


# -- tun mtu ---------------------------------------------------------------
def test_tun_mtu_overrides_the_template():
    tun = next(i for i in _render(tun_mtu=1280)["inbounds"] if i["tag"] == "tun-in")
    assert tun["settings"]["mtu"] == 1280


def test_out_of_range_mtu_is_ignored_rather_than_written_through():
    for bad in (0, 42, 99999, "1420", True):
        tun = next(i for i in _render(tun_mtu=bad)["inbounds"] if i["tag"] == "tun-in")
        assert tun["settings"]["mtu"] == 1420


def test_tun_mtu_is_a_known_setting_with_a_safe_default():
    assert app_settings.DEFAULTS["tun_mtu"] == 1420
    assert app_settings.load()["tun_mtu"] == 1420


def test_tun_adapter_gets_a_resolver_from_the_template():
    tun = next(i for i in json.loads(TEMPLATE.read_text(encoding="utf-8"))["inbounds"]
               if i["tag"] == "tun-in")
    assert tun["settings"]["dns"] == ["127.0.0.1"]
