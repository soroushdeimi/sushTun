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


# -- *_reason(s) detail functions (i18n: value + an unformatted template) ----
def test_invalid_server_reasons_matches_invalid_servers_formatted():
    servers = ["1.1.1.1", "localhost", "fakedns", "nope nope", "8.8.8.8:5353"]
    details = dns_mod.invalid_server_reasons(servers)
    formatted = [tmpl.format(value=value) for value, tmpl in details]
    assert formatted == dns_mod.invalid_servers(servers)
    assert all(value in tmpl.format(value=value) for value, tmpl in details)


def test_validate_domestic_reasons_matches_validate_domestic_formatted():
    entries = ["localhost", "fakedns", "not a server", "resolver.example.com"]
    details = dns_mod.validate_domestic_reasons(entries)
    formatted = [tmpl.format(value=value) for value, tmpl in details]
    assert formatted == dns_mod.validate_domestic(entries)


def test_raw_override_issue_reasons_matches_raw_override_issues_formatted():
    raw = json.dumps({"servers": ["localhost", {"address": "fakedns"}, "1.1.1.1"]})
    details = dns_mod.raw_override_issue_reasons(raw)
    formatted = [tmpl.format(value=value) for value, tmpl in details]
    assert formatted == dns_mod.raw_override_issues(raw)
    assert len(details) == 2


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


# -- Phase 3: domestic DNS, remote-via-tunnel, raw override -----------------
PROXY_IP = "203.0.113.1"
PROXY_HOST = "example.com"


def test_domestic_presets_are_all_valid_literal_ips():
    assert dns_mod.DOMESTIC_PRESETS
    for name, addrs in dns_mod.DOMESTIC_PRESETS.items():
        assert addrs, name
        for addr in addrs:
            assert dns_mod.validate_domestic([addr]) == [], f"{name}: {addr}"
            assert not any(c.isalpha() for c in addr), f"{name}: {addr} is not a literal IP"


def test_no_domestic_rule_without_both_servers_and_direct_domains():
    block, rules = dns_mod.build_dns_and_rules(_dns(), [], PROXY_IP)
    assert rules == []
    block, rules = dns_mod.build_dns_and_rules(
        _dns(domestic_servers=["178.22.122.100"]), [], PROXY_IP)
    assert rules == []
    block, rules = dns_mod.build_dns_and_rules(_dns(), ["domain:ir"], PROXY_IP)
    assert rules == []


def test_domestic_servers_are_prepended_with_the_right_shape():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(domestic_servers=["178.22.122.100", "185.51.200.2"]),
        ["domain:ir", "geosite:category-ir"], PROXY_IP)
    entries = block["servers"][:2]
    for entry, addr in zip(entries, ["178.22.122.100", "185.51.200.2"], strict=True):
        assert entry == {
            "address": addr, "domains": ["domain:ir", "geosite:category-ir"],
            "skipFallback": True, "tag": "direct-dns",
        }
    assert rules == [{"type": "field", "inboundTag": ["direct-dns"], "outboundTag": "direct"}]


def test_domestic_servers_go_ahead_of_the_users_own_servers():
    block, _ = dns_mod.build_dns_and_rules(
        _dns(domestic_servers=["178.22.122.100"], servers=["1.1.1.1"]),
        ["domain:ir"], PROXY_IP)
    assert block["servers"][0]["address"] == "178.22.122.100"
    assert block["servers"][1] == "1.1.1.1"


def test_bad_domestic_entries_are_dropped_not_fatal():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(domestic_servers=["localhost", "fakedns", "not a server", "178.22.122.100"]),
        ["domain:ir"], PROXY_IP)
    addrs = [e["address"] for e in block["servers"]]
    assert addrs == ["178.22.122.100"]
    reasons = dns_mod.validate_domestic(["localhost", "fakedns", "not a server"])
    assert len(reasons) == 3


def test_domestic_host_port_is_split_like_a_dns_server_object():
    block, _ = dns_mod.build_dns_and_rules(
        _dns(domestic_servers=["178.22.122.100:5353"]), ["domain:ir"], PROXY_IP)
    entry = block["servers"][0]
    assert entry["address"] == "178.22.122.100"
    assert entry["port"] == 5353


def test_domestic_accepts_only_literal_ip_forms():
    for good in ["178.22.122.100", "178.22.122.100:5353", "[2606:4700:4700::1111]:53",
                 "udp://178.22.122.100", "udp://178.22.122.100:5353"]:
        assert dns_mod.validate_domestic([good]) == [], good


def test_domestic_rejects_a_hostname_because_it_is_circular():
    # A hostname domestic resolver would itself need DNS to resolve, which
    # is exactly the loop the direct-dns rule exists to avoid.
    why = dns_mod.validate_domestic(["resolver.example.com"])
    assert why
    assert "IP address" in why[0]
    why_scheme = dns_mod.validate_domestic(["https://dns.example.com/dns-query"])
    assert why_scheme
    assert "IP address" in why_scheme[0]


def test_domestic_hostname_is_dropped_at_render_not_fatal():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(domestic_servers=["resolver.example.com", "178.22.122.100"]),
        ["domain:ir"], PROXY_IP)
    addrs = [e["address"] for e in block["servers"]]
    assert addrs == ["178.22.122.100"]


# -- remote_via_tunnel -------------------------------------------------------
def test_remote_via_tunnel_sets_tag_and_proxy_rule():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, servers=["1.1.1.1"]), [], PROXY_IP)
    assert block["tag"] == "dns-module"
    assert {"type": "field", "inboundTag": ["dns-module"], "outboundTag": "proxy"} in rules


def test_hostname_proxy_gets_a_bootstrap_entry():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, servers=["1.1.1.1"]), [], PROXY_HOST)
    bootstrap = block["servers"][0]
    assert bootstrap["tag"] == "direct-dns"
    assert bootstrap["domains"] == [f"full:{PROXY_HOST}"]
    assert bootstrap["skipFallback"] is True
    assert bootstrap["address"] == "1.1.1.1"  # first literal-IP server, no domestic set
    assert {"type": "field", "inboundTag": ["direct-dns"], "outboundTag": "direct"} in rules


def test_hostname_proxy_with_known_server_ip_is_pinned_not_bootstrapped():
    # connection.py already resolves the proxy and pins a host route to it
    # before Xray starts -- Xray needs no DNS lookup for that name at all.
    block, rules = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, servers=["1.1.1.1"]), [], PROXY_HOST,
        server_ip="198.51.100.7")
    assert block["hosts"] == {PROXY_HOST: "198.51.100.7"}
    assert not any(isinstance(s, dict) and s.get("tag") == "direct-dns"
                   for s in block["servers"])
    # Only the proxy rule remains -- no direct-dns rule, since nothing
    # needs the bootstrap once the proxy host is pinned.
    assert rules == [{"type": "field", "inboundTag": ["dns-module"], "outboundTag": "proxy"}]


def test_a_users_own_hosts_entry_for_the_proxy_host_wins_over_the_pin():
    block, _ = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, servers=["1.1.1.1"],
             hosts=[f"{PROXY_HOST} = 9.9.9.9"]), [], PROXY_HOST,
        server_ip="198.51.100.7")
    assert block["hosts"][PROXY_HOST] == "9.9.9.9"


def test_hostname_dns_server_still_gets_a_bootstrap_even_with_a_pinned_proxy():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, servers=["https://dns.google/dns-query", "1.1.1.1"]),
        [], PROXY_HOST, server_ip="198.51.100.7")
    assert block["hosts"] == {PROXY_HOST: "198.51.100.7"}
    bootstrap = next(s for s in block["servers"] if isinstance(s, dict)
                     and s.get("tag") == "direct-dns")
    assert bootstrap["domains"] == ["full:dns.google"]  # not the pinned proxy host
    assert rules  # the direct-dns rule is still needed for the DoH bootstrap


def test_server_ip_none_keeps_the_bootstrap_for_the_proxy_host():
    block, _ = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, servers=["1.1.1.1"]), [], PROXY_HOST, server_ip=None)
    assert "hosts" not in block
    bootstrap = block["servers"][0]
    assert bootstrap["domains"] == [f"full:{PROXY_HOST}"]


def test_hostname_dns_server_also_gets_a_bootstrap_entry():
    block, _ = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, servers=["https://dns.google/dns-query", "1.1.1.1"]),
        [], PROXY_IP)
    bootstrap = block["servers"][0]
    assert "full:dns.google" in bootstrap["domains"]
    assert f"full:{PROXY_IP}" not in bootstrap["domains"]  # the proxy itself is an IP


def test_ip_proxy_with_ip_servers_gets_no_bootstrap():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, servers=["1.1.1.1", "8.8.8.8"]), [], PROXY_IP)
    assert not any(s.get("tag") == "direct-dns" for s in block["servers"] if isinstance(s, dict))
    assert rules == [{"type": "field", "inboundTag": ["dns-module"], "outboundTag": "proxy"}]


def test_bootstrap_never_uses_a_domestic_server_even_when_one_is_set():
    # A domestic resolver returns poisoned answers for blocked foreign
    # names (e.g. a DoH hostname) in the exact scenario this bootstrap
    # exists to resolve correctly, so it must never be picked here even
    # when one is configured and would otherwise be preferred.
    block, _ = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, domestic_servers=["178.22.122.100"], servers=["1.1.1.1"]),
        ["domain:ir"], PROXY_HOST)
    bootstrap = next(s for s in block["servers"] if s.get("tag") == "direct-dns"
                      and f"full:{PROXY_HOST}" in s.get("domains", []))
    assert bootstrap["address"] == "1.1.1.1"


def test_bootstrap_falls_back_to_1111_with_no_domestic_or_literal_ip_servers():
    block, _ = dns_mod.build_dns_and_rules(
        _dns(remote_via_tunnel=True, servers=[]), [], PROXY_HOST)
    bootstrap = block["servers"][0]
    assert bootstrap["address"] == "1.1.1.1"


def test_domestic_and_remote_via_tunnel_coexist_with_one_direct_dns_rule():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(domestic_servers=["178.22.122.100"], remote_via_tunnel=True, servers=["1.1.1.1"]),
        ["domain:ir"], PROXY_HOST)
    direct_dns_entries = [s for s in block["servers"]
                          if isinstance(s, dict) and s.get("tag") == "direct-dns"]
    assert len(direct_dns_entries) == 2  # one for direct_domains, one bootstrap
    direct_dns_rules = [r for r in rules if r.get("inboundTag") == ["direct-dns"]]
    assert len(direct_dns_rules) == 1


# -- parallel query / serve stale -------------------------------------------
def test_parallel_query_and_serve_stale_are_opt_in():
    block, _ = dns_mod.build_dns_and_rules(_dns(), [], PROXY_IP)
    assert "enableParallelQuery" not in block
    assert "serveStale" not in block
    block, _ = dns_mod.build_dns_and_rules(
        _dns(parallel_query=True, serve_stale=True), [], PROXY_IP)
    assert block["enableParallelQuery"] is True
    assert block["serveStale"] is True


# -- raw override -------------------------------------------------------------
def test_raw_override_replaces_the_whole_block_and_ignores_other_settings():
    raw = json.dumps({"servers": ["9.9.9.9"], "queryStrategy": "UseIPv4"})
    block, rules = dns_mod.build_dns_and_rules(
        _dns(raw_override=raw, domestic_servers=["178.22.122.100"], remote_via_tunnel=True,
             servers=["1.1.1.1"]),
        ["domain:ir"], PROXY_HOST)
    assert block == {"servers": ["9.9.9.9"], "queryStrategy": "UseIPv4"}
    assert rules == []


def test_invalid_raw_override_json_is_ignored_falls_through():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(raw_override="{not json", servers=["1.1.1.1"]), [], PROXY_IP)
    assert block["servers"] == ["1.1.1.1"]


def test_raw_override_non_object_json_is_ignored():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(raw_override="[1, 2, 3]", servers=["1.1.1.1"]), [], PROXY_IP)
    assert block["servers"] == ["1.1.1.1"]


def test_raw_override_drops_localhost_and_fakedns_at_render_time():
    raw = json.dumps({"servers": ["localhost", "1.1.1.1", {"address": "fakedns"},
                                  {"address": "8.8.8.8"}]})
    block, _ = dns_mod.build_dns_and_rules(_dns(raw_override=raw), [], PROXY_IP)
    assert block["servers"] == ["1.1.1.1", {"address": "8.8.8.8"}]


def test_raw_override_refuses_to_save_localhost_or_fakedns():
    assert dns_mod.raw_override_issues(json.dumps({"servers": ["localhost"]}))
    assert dns_mod.raw_override_issues(json.dumps({"servers": [{"address": "fakedns"}]}))
    assert dns_mod.raw_override_issues(json.dumps({"servers": ["1.1.1.1"]})) == []


def test_raw_override_issues_never_refuses_invalid_json_or_non_object():
    assert dns_mod.raw_override_issues("{not json") == []
    assert dns_mod.raw_override_issues("[1, 2]") == []
    assert dns_mod.raw_override_issues("") == []


# -- render.py rule ordering --------------------------------------------------
def test_defaults_produce_no_dns_routing_rules_byte_identical_render():
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    out = _render(dns_cfg=_dns())
    assert out["routing"]["rules"] == template["routing"]["rules"]


def test_server_ip_is_a_no_op_without_remote_via_tunnel():
    # server_ip only matters once remote_via_tunnel is on; passing it with
    # default DNS settings must render exactly as if it were never passed.
    with_ip = _render(dns_cfg=_dns(), server_ip="198.51.100.7")
    without_ip = _render(dns_cfg=_dns())
    assert with_ip == without_ip


def test_domestic_dns_rule_lands_after_template_rules_and_before_a_user_catch_all():
    r = copy.deepcopy(app_settings.DEFAULTS["routing"])
    r["direct_iran"] = True
    rules = routing.build_rules(r)
    user_catch_all = {"type": "field", "port": "0-65535", "outboundTag": "proxy"}
    out = _render(
        routing_rules=rules + [user_catch_all],
        dns_cfg=_dns(domestic_servers=["178.22.122.100"]),
    )
    template_rules = json.loads(TEMPLATE.read_text(encoding="utf-8"))["routing"]["rules"]
    got = out["routing"]["rules"]
    assert got[:len(template_rules)] == template_rules
    direct_dns_idx = next(i for i, x in enumerate(got) if x.get("inboundTag") == ["direct-dns"])
    catch_all_idx = got.index(user_catch_all)
    assert len(template_rules) <= direct_dns_idx < catch_all_idx


def test_remote_via_tunnel_rule_also_lands_before_a_user_catch_all():
    user_catch_all = {"type": "field", "port": "0-65535", "outboundTag": "proxy"}
    out = _render(
        routing_rules=[user_catch_all],
        dns_cfg=_dns(remote_via_tunnel=True, servers=["1.1.1.1"]),
    )
    got = out["routing"]["rules"]
    dns_module_idx = next(i for i, x in enumerate(got) if x.get("inboundTag") == ["dns-module"])
    catch_all_idx = got.index(user_catch_all)
    assert dns_module_idx < catch_all_idx


# -- xray run -test on real rendered configs ----------------------------------
def _skip_if_no_binary():
    from xrayui import paths
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")


@pytest.mark.parametrize("dns_over", [
    {},
    {"domestic_servers": ["178.22.122.100", "185.51.200.2"]},
    {"remote_via_tunnel": True, "servers": ["1.1.1.1"]},
    {"domestic_servers": ["178.22.122.100"], "remote_via_tunnel": True, "servers": ["1.1.1.1"]},
], ids=["defaults", "domestic", "remote_via_tunnel", "both"])
def test_xray_test_accepts_the_fully_rendered_config(tmp_path, monkeypatch, dns_over):
    _skip_if_no_binary()
    from xrayui.core import xraycheck
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)

    r = copy.deepcopy(app_settings.DEFAULTS["routing"])
    r["direct_iran"] = True
    rules = routing.build_rules(r)
    text = render.build_text(
        parse_vless(SAMPLE), "lo", TEMPLATE, routing_rules=rules,
        domain_strategy=routing.domain_strategy_for(r), include_tun=False,
        dns_cfg=_dns(**dns_over),
    )
    assert xraycheck.check_config(text) is None


# -- company / internal networks -------------------------------------------------------
MAHSAN = "mahsan.co = 192.168.92.21, 192.168.92.11"


def test_internal_lines_are_parsed_and_bad_ones_dropped():
    lines = [MAHSAN, "*.shetab.org = 10.20.3.7", "# a comment", "",
             "no-server.example", "not a domain = 1.2.3.4",
             "corp.example = dns.corp.example",     # a name would need DNS to find DNS
             "mahsan.co = 9.9.9.9"]                 # a second line for the same domain
    assert dns_mod.clean_internal(lines) == [
        ("mahsan.co", ["192.168.92.21", "192.168.92.11"]), ("shetab.org", ["10.20.3.7"])]
    reasons = [tmpl for _v, tmpl in dns_mod.internal_reasons(lines)]
    assert reasons == [dns_mod.REASON_INTERNAL_FORMAT, dns_mod.REASON_INTERNAL_DOMAIN,
                       dns_mod.REASON_INTERNAL_SERVER_IP]


def test_internal_servers_come_first_and_never_fall_back():
    block, rules = dns_mod.build_dns_and_rules(_dns(internal=[MAHSAN]), [], PROXY_IP)
    assert block["servers"][:2] == [
        {"address": ip, "domains": ["domain:mahsan.co"], "skipFallback": True,
         "tag": "internal-dns"} for ip in ("192.168.92.21", "192.168.92.11")]
    assert {"type": "field", "inboundTag": ["internal-dns"],
            "outboundTag": "internal"} in rules


def test_internal_queries_leave_through_an_unbound_outbound():
    # No interface binding: the OS has to route them into the company VPN,
    # which owns a more specific route to its DNS server than our /1s.
    out = _render(dns_cfg=_dns(internal=[MAHSAN]))
    internal = [o for o in out["outbounds"] if o["tag"] == "internal"]
    assert internal == [{"tag": "internal", "protocol": "freedom"}]
    for o in out["outbounds"]:
        if o["tag"] in ("proxy", "direct", "dns-out"):
            assert o["streamSettings"]["sockopt"]["interface"] == "Wi-Fi"


def test_no_internal_networks_add_nothing():
    out = _render(dns_cfg=_dns())
    assert all(o["tag"] != "internal" for o in out["outbounds"])
    assert "internal-dns" not in json.dumps(out)


def test_internal_networks_work_with_remote_dns_through_the_tunnel():
    block, rules = dns_mod.build_dns_and_rules(
        _dns(internal=[MAHSAN], remote_via_tunnel=True), [], PROXY_IP)
    assert block["servers"][0]["tag"] == "internal-dns"
    tags = [r["inboundTag"][0] for r in rules]
    assert "internal-dns" in tags and "dns-module" in tags


def test_xray_test_accepts_internal_networks(tmp_path, monkeypatch):
    _skip_if_no_binary()
    from xrayui.core import xraycheck
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    text = render.build_text(parse_vless(SAMPLE), "lo", TEMPLATE, include_tun=False,
                             dns_cfg=_dns(internal=[MAHSAN, "shetab.org = 10.20.3.7"]))
    assert '"internal-dns"' in text
    assert xraycheck.check_config(text) is None
