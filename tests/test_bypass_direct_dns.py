"""Tests for dns.bypass_use_system_dns: resolving bypassed domains via system DNS."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xrayui.core import connection, render, routing, xraycheck
from xrayui.core import dns as dns_mod
from xrayui.core import settings as app_settings
from xrayui.core.importer import parse_vless
from xrayui.core.network import DnsState, Interface
from xrayui.core.profiles import Profile
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


def _render(routing_cfg, dns_cfg=None, system_dns=None, iface="Wi-Fi"):
    rules = routing.build_rules(routing_cfg)
    strategy = routing.domain_strategy_for(routing_cfg)
    return json.loads(render.build_text(
        parse_vless(SAMPLE), iface, TEMPLATE,
        routing_rules=rules, domain_strategy=strategy,
        dns_cfg=dns_cfg if dns_cfg is not None else _dns(),
        include_tun=False, system_dns=system_dns,
    ))


def _find_asset_dir() -> Path | None:
    p = xraycheck.paths.asset_dir()
    if (p / "geosite.dat").exists():
        return p
    brew_assets = Path("/opt/homebrew/share/xray")
    if (brew_assets / "geosite.dat").exists():
        return brew_assets
    main_repo = Path(__file__).resolve().parent.parent.parent / "sushTun"
    if (main_repo / "geosite.dat").exists():
        return main_repo
    return None


def _skip_if_no_xray(monkeypatch):
    brew_xray = Path("/opt/homebrew/bin/xray")
    if brew_xray.exists():
        monkeypatch.setattr(xraycheck.paths, "xray_exe", lambda: brew_xray)
    elif not xraycheck.paths.xray_exe().exists():
        pytest.skip("xray binary not present")
    assets = _find_asset_dir()
    if assets:
        monkeypatch.setattr(xraycheck.paths, "asset_dir", lambda: assets)


def test_flag_off_renders_identically_to_missing_key():
    r_cfg = _routing(bypass_domains=["browserleaks.com"])
    # Render with key explicitly False and system_dns supplied
    d_off = _dns(bypass_use_system_dns=False, servers=["1.1.1.1"])
    cfg_off = _render(r_cfg, d_off, system_dns=["192.168.1.1"])

    # Render without the key at all and system_dns None
    d_no_key = _dns(servers=["1.1.1.1"])
    d_no_key.pop("bypass_use_system_dns", None)
    cfg_no_key = _render(r_cfg, d_no_key, system_dns=None)

    assert cfg_off["dns"] == cfg_no_key["dns"]
    assert cfg_off["routing"] == cfg_no_key["routing"]


def test_flag_on_with_bypass_domain_injects_system_dns_and_routing():
    r_cfg = _routing(bypass_domains=["browserleaks.com"])
    d_cfg = _dns(bypass_use_system_dns=True, servers=["1.1.1.1"])
    cfg = _render(r_cfg, d_cfg, system_dns=["192.168.1.1"], iface="eth0")

    # 1. DNS servers: system DNS entry prepended
    servers = cfg["dns"]["servers"]
    assert len(servers) >= 2
    sys_entry = servers[0]
    assert sys_entry["address"] == "192.168.1.1"
    assert sys_entry["tag"] == "direct-dns"
    assert sys_entry["skipFallback"] is True
    assert "domain:browserleaks.com" in sys_entry["domains"]

    # 2. Routing rules: direct-dns -> direct before user rules
    rules = cfg["routing"]["rules"]
    assert rules[0]["inboundTag"] == ["dns-in"]
    assert rules[1]["inboundTag"] == ["tun-in"]
    assert rules[2]["inboundTag"] == ["direct-dns"]
    assert rules[2]["outboundTag"] == "direct"

    # User rules follow
    direct_domain_rule = next(
        r for r in rules[3:] if r.get("outboundTag") == "direct" and "domain" in r
    )
    assert "domain:browserleaks.com" in direct_domain_rule["domain"]

    # 3. Direct outbound binds to the physical interface
    direct_out = next(o for o in cfg["outbounds"] if o.get("tag") == "direct")
    assert direct_out["streamSettings"]["sockopt"]["interface"] == "eth0"


def test_domestic_servers_wins_over_system_dns():
    r_cfg = _routing(bypass_domains=["browserleaks.com"])
    d_cfg = _dns(
        bypass_use_system_dns=True,
        domestic_servers=["178.22.122.100"],
        servers=["1.1.1.1"],
    )
    cfg = _render(r_cfg, d_cfg, system_dns=["192.168.1.1"])

    servers = cfg["dns"]["servers"]
    assert servers[0]["address"] == "178.22.122.100"
    assert not any(isinstance(s, dict) and s.get("address") == "192.168.1.1" for s in servers)


def test_no_bypass_domains_adds_nothing():
    r_cfg = _routing(
        direct_private=False, direct_iran=False, direct_russia=False,
        direct_china=False, low_usage=False, bypass_domains=[],
    )
    d_cfg = _dns(bypass_use_system_dns=True, servers=["1.1.1.1"])
    cfg = _render(r_cfg, d_cfg, system_dns=["192.168.1.1"])

    servers = cfg["dns"]["servers"]
    assert not any(isinstance(s, dict) and s.get("tag") == "direct-dns" for s in servers)
    assert not any(r.get("inboundTag") == ["direct-dns"] for r in cfg["routing"]["rules"])


def test_system_dns_sanitization():
    raw_system_dns = [
        "127.0.0.1",
        "127.1.2.3",
        "::1",
        "junk_string",
        "0.0.0.0",
        "::",
        "169.254.1.1",
        "fe80::1",
        "172.19.0.2",   # TUN_ADDRESS
        "172.19.0.1",   # TUN_DNS
        "192.168.1.1",
        "192.168.1.1",   # duplicate
        "10.0.0.1",
        "1.1.1.1",
        "8.8.8.8",       # exceeds cap of 3
    ]
    cleaned = dns_mod.clean_system_dns(raw_system_dns)
    assert cleaned == ["192.168.1.1", "10.0.0.1", "1.1.1.1"]

    # Render with this list
    r_cfg = _routing(bypass_domains=["browserleaks.com"])
    d_cfg = _dns(bypass_use_system_dns=True, servers=["8.8.4.4"])
    cfg = _render(r_cfg, d_cfg, system_dns=raw_system_dns)

    sys_servers = [s for s in cfg["dns"]["servers"] if isinstance(s, dict) and s.get("tag") == "direct-dns"]
    assert len(sys_servers) == 3
    assert [s["address"] for s in sys_servers] == ["192.168.1.1", "10.0.0.1", "1.1.1.1"]


def test_empty_or_none_system_dns_adds_nothing_and_does_not_crash():
    r_cfg = _routing(bypass_domains=["browserleaks.com"])
    d_cfg = _dns(bypass_use_system_dns=True, servers=["1.1.1.1"])

    for empty_dns in (None, [], ["127.0.0.1", "junk"]):
        cfg = _render(r_cfg, d_cfg, system_dns=empty_dns)
        servers = cfg["dns"]["servers"]
        assert not any(isinstance(s, dict) and s.get("tag") == "direct-dns" for s in servers)
        assert not any(r.get("inboundTag") == ["direct-dns"] for r in cfg["routing"]["rules"])


def test_raw_override_present_keeps_unchanged_behaviour():
    raw = json.dumps({"servers": ["1.1.1.1"]})
    r_cfg = _routing(bypass_domains=["browserleaks.com"])
    d_cfg = _dns(raw_override=raw, bypass_use_system_dns=True)
    cfg = _render(r_cfg, d_cfg, system_dns=["192.168.1.1"])

    assert cfg["dns"]["servers"] == ["1.1.1.1"]
    assert not any(r.get("inboundTag") == ["direct-dns"] for r in cfg["routing"]["rules"])


def test_settings_schema_default_and_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)

    # Defaults to False
    loaded = app_settings.load()
    assert loaded["dns"]["bypass_use_system_dns"] is False

    # Round trip with True
    loaded["dns"]["bypass_use_system_dns"] = True
    app_settings.save(loaded)
    reloaded = app_settings.load()
    assert reloaded["dns"]["bypass_use_system_dns"] is True


def test_connection_plumbs_system_dns_when_flag_on_and_omits_when_off(monkeypatch, tmp_path):
    monkeypatch.setattr(connection.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(connection.paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(connection.paths, "runtime_config", lambda: tmp_path / "runtime.json")
    monkeypatch.setattr(connection.paths, "config_template", lambda: TEMPLATE)

    rendered_configs = []
    orig_build = render.build

    def record_build(*args, **kwargs):
        rendered_configs.append(kwargs)
        return orig_build(*args, **kwargs)

    monkeypatch.setattr(render, "build", record_build)

    net = connection.network
    monkeypatch.setattr(net, "detect_interface", lambda: Interface("eth0", "192.0.2.2", "192.0.2.1"))
    monkeypatch.setattr(net, "foreign_tunnel", lambda _a: None)
    monkeypatch.setattr(net, "backup_dns", lambda _a: DnsState("DHCP", ["192.168.1.1"]))
    monkeypatch.setattr(connection, "_resolve", lambda host: "192.0.2.9")
    for name in ("remove_routes", "add_host_route", "add_default_routes", "set_dns_loopback", "restore_dns"):
        monkeypatch.setattr(net, name, lambda *a, **k: None)
    monkeypatch.setattr(net, "release_stranded_dns", lambda **k: [])
    monkeypatch.setattr(net, "wait_for_tun", lambda **k: 7)
    monkeypatch.setattr(net, "configure_tun", lambda _t: True)
    conn = connection.Connection()
    monkeypatch.setattr(conn, "_setup_gateway", lambda: None)
    monkeypatch.setattr(conn, "_retry_without_extras", lambda *a: None)
    monkeypatch.setattr(conn.xray, "start", lambda p: None)
    monkeypatch.setattr(conn.xray, "stop", lambda: None)
    monkeypatch.setattr(conn.xray, "is_running", lambda: True)

    profile = Profile(uid="p1", address="server.example", id="pass")

    # 1. Flag OFF: system_dns is None or not passed to render.build
    cfg = copy.deepcopy(DEFAULTS)
    cfg["dns"]["bypass_use_system_dns"] = False
    cfg["routing"]["bypass_domains"] = ["browserleaks.com"]
    monkeypatch.setattr(connection.app_settings, "load", lambda: copy.deepcopy(cfg))

    conn._connect_generic(profile, Interface("eth0", "192.0.2.2", "192.0.2.1"), "192.0.2.9", DnsState("DHCP", ["192.168.1.1"]))
    assert len(rendered_configs) == 1
    assert rendered_configs[0].get("system_dns") is None

    # 2. Flag ON: system_dns reaches render.build
    rendered_configs.clear()
    cfg["dns"]["bypass_use_system_dns"] = True
    monkeypatch.setattr(connection.app_settings, "load", lambda: copy.deepcopy(cfg))

    conn._connect_generic(profile, Interface("eth0", "192.0.2.2", "192.0.2.1"), "192.0.2.9", DnsState("DHCP", ["192.168.1.1"]))
    assert len(rendered_configs) == 1
    assert rendered_configs[0].get("system_dns") == ["192.168.1.1"]


def test_rendered_config_validates_with_xray_run_test(tmp_path, monkeypatch):
    _skip_if_no_xray(monkeypatch)
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)

    r_cfg = _routing(bypass_domains=["browserleaks.com"])
    d_cfg = _dns(bypass_use_system_dns=True)
    text = render.build_text(
        parse_vless(SAMPLE), "eth0", TEMPLATE,
        routing_rules=routing.build_rules(r_cfg),
        domain_strategy=routing.domain_strategy_for(r_cfg),
        dns_cfg=d_cfg, include_tun=False,
        system_dns=["192.168.1.1", "1.1.1.1"],
    )
    err = xraycheck.check_config(text)
    assert err is None
