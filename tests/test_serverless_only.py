"""Serverless only: a connection with no server, straight out through the fragmenting outbound."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import connection, render, routing, serverless, xraycheck
from xrayui.core import settings as app_settings
from xrayui.core.network import DnsState, Interface
from xrayui.core.state import State

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"
BOOT = ["192.168.1.1"]


def _skip_if_no_binary():
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")


def _text(**kw) -> str:
    kw.setdefault("serverless_bootstrap", BOOT)
    return render.build_text(serverless.only_profile(), "lo", TEMPLATE, include_tun=False, **kw)


def _render(**kw) -> dict:
    return json.loads(_text(**kw))


def _masks(out: dict) -> list[str]:
    return [m["settings"]["packets"] for m in out["streamSettings"]["finalmask"]["tcp"]]


def test_the_proxy_outbound_is_the_fragmenting_direct_one():
    cfg = _render(serverless_cfg={"enabled": True})
    first = cfg["outbounds"][0]
    assert first["tag"] == "proxy"
    assert first["protocol"] == "freedom"
    assert first["settings"]["domainStrategy"] == "ForceIPv4"
    assert first["streamSettings"]["sockopt"]["interface"] == "lo"
    assert _masks(first) == ["1-1", "tlshello"]
    text = json.dumps(cfg)
    assert "vnext" not in text and "vless" not in text
    assert not any(o["tag"] == "serverless" for o in cfg["outbounds"])


def test_dns_goes_through_doh_with_the_system_resolver_for_the_front():
    dns = _render()["dns"]
    assert dns["servers"] == [
        "https://cloudflare-dns.com/dns-query",
        "https://1dot1dot1dot1.cloudflare-dns.com/dns-query",
        {"address": "192.168.1.1", "domains": ["full:challenges.cloudflare.com"],
         "skipFallback": True},
    ]
    for host in serverless.DOH_HOSTS:
        assert dns["hosts"][host] == serverless.DOH_FRONT
    assert dns["queryStrategy"] == "UseIPv4"


def test_doh_queries_race_so_one_stalled_handshake_cannot_hang_dns():
    # Measured from Iran: about one fragmented handshake in five stalls, and a
    # lone DoH client then waits on that one connection for over a minute.
    assert _render()["dns"]["enableParallelQuery"] is True


def test_user_dns_cannot_replace_our_servers_but_its_hosts_stay():
    user = copy.deepcopy(app_settings.DEFAULTS["dns"])
    user["servers"] = ["8.8.4.4"]
    user["query_strategy"] = "UseIP"
    user["hosts"] = ["my.example = 10.1.1.1"]
    dns = _render(dns_cfg=user)["dns"]
    assert dns["servers"][:2] == serverless.DOH_URLS
    assert len(dns["servers"]) == 3
    assert dns["queryStrategy"] == "UseIPv4"
    assert dns["hosts"]["my.example"] == "10.1.1.1"
    assert dns["hosts"][serverless.DOH_HOSTS[0]] == serverless.DOH_FRONT


@pytest.mark.parametrize("given, expected", [
    (["127.0.0.1", "not-an-ip", "10.0.0.1"], "10.0.0.1"),
    (["::1", "2001:db8::53"], "2001:db8::53"),
    (None, "1.1.1.1"),
    ([], "1.1.1.1"),
    (["localhost"], "1.1.1.1"),
    (["fe80::1%en0", "192.168.1.1"], "192.168.1.1"),
    (["fe80::1%en0", "2001:db8::53"], "2001:db8::53"),
    (["169.254.1.1", "fe80::1"], "1.1.1.1"),
    (["0.0.0.0", "10.0.0.1"], "10.0.0.1"),
])
def test_bootstrap_resolver_choice(given, expected):
    dns = _render(serverless_bootstrap=given)["dns"]
    assert dns["servers"][-1]["address"] == expected


def test_blocks_come_first_and_the_other_rules_stay():
    rules_in = routing.build_rules(app_settings.DEFAULTS["routing"])
    dns_cfg = copy.deepcopy(app_settings.DEFAULTS["dns"])
    dns_cfg["domestic_servers"] = ["178.22.122.100"]
    base = json.loads(TEMPLATE.read_text(encoding="utf-8"))["routing"]["rules"]
    rules = _render(routing_rules=rules_in, dns_cfg=dns_cfg)["routing"]["rules"]
    assert rules[0] == {"type": "field", "ip": serverless.SINKHOLES, "outboundTag": "block"}
    assert rules[1] == {"type": "field", "network": "udp", "port": "443", "outboundTag": "block"}
    rest = rules[2:]
    for rule in base:
        assert rule in rest
    assert any(r.get("outboundTag") == "direct" and "geoip:ir" in (r.get("ip") or [])
               for r in rest)
    assert any(r.get("inboundTag") for r in rest if r not in base)  # the dns rule


def test_fragment_mux_and_fingerprint_options_skip_the_stand_in():
    core = copy.deepcopy(app_settings.DEFAULTS["core"])
    core["fragment"] = {**core.get("fragment", {}), "enabled": True}
    core["mux"] = {**core.get("mux", {}), "enabled": True}
    core["default_fp"] = "chrome"
    first = _render(core_cfg=core)["outbounds"][0]
    assert len(first["streamSettings"]["finalmask"]["tcp"]) == 2
    assert _masks(first) == ["1-1", "tlshello"]
    assert "mux" not in first
    assert "tlsSettings" not in first["streamSettings"]


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "runtime.json")
    monkeypatch.setattr(paths, "config_template", lambda: TEMPLATE)
    cfg = copy.deepcopy(app_settings.DEFAULTS)
    monkeypatch.setattr(connection.app_settings, "load", lambda: copy.deepcopy(cfg))
    calls = []
    net = connection.network
    monkeypatch.setattr(net, "detect_interface", lambda: Interface("eth0", "192.0.2.2", "192.0.2.1"))
    monkeypatch.setattr(net, "foreign_tunnel", lambda _a: None)
    monkeypatch.setattr(net, "backup_dns", lambda _a: DnsState())
    monkeypatch.setattr(net, "system_dns_servers", lambda *a: ["192.0.2.53"])
    monkeypatch.setattr(connection, "_resolve", lambda host: calls.append(("resolve", host)) or "192.0.2.9")
    for name in ("remove_routes", "add_host_route", "add_default_routes", "set_dns_loopback",
                 "restore_dns", "replace_host_route"):
        monkeypatch.setattr(net, name, lambda *a, _name=name, **k: calls.append((_name, *a)))
    monkeypatch.setattr(net, "release_stranded_dns", lambda **k: [])
    monkeypatch.setattr(net, "wait_for_tun", lambda **k: 7)
    monkeypatch.setattr(net, "configure_tun", lambda _t: True)
    monkeypatch.setattr(net, "repair_tun_routes", lambda: False)
    for name, fn in {
        "mac_other_vpn": lambda _a: None,
        "mac_ensure_scoped_default": lambda *a: False,
        "mac_wait_for_device": lambda **k: True,
        "mac_add_split_routes": lambda native: None,
        "mac_route_device": lambda _a: connection.t2s.DEVICE,
    }.items():
        monkeypatch.setattr(net, name, fn, raising=False)
    monkeypatch.setattr(connection.t2s, "kill_stale", lambda: None)
    monkeypatch.setattr(connection.t2s, "bring_up_device", lambda **k: True)
    monkeypatch.setattr(connection, "_wait_port", lambda *a, **k: True)
    monkeypatch.setattr(connection.bootrestore, "install", lambda: None)
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: None)
    conn = connection.Connection()
    monkeypatch.setattr(conn, "_setup_gateway", lambda: None)
    monkeypatch.setattr(conn, "_retry_without_extras", lambda *a: None)
    monkeypatch.setattr(conn.xray, "start", lambda p: calls.append(("start", json.loads(p.read_text()))))
    monkeypatch.setattr(conn.xray, "stop", lambda: calls.append(("stop",)))
    monkeypatch.setattr(conn.xray, "is_running", lambda: True)
    monkeypatch.setattr(conn.tun2socks, "start", lambda *a: calls.append(("bridge",)))
    monkeypatch.setattr(conn.tun2socks, "stop", lambda: None)
    return conn, calls


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_connect_needs_no_server_route_or_lookup(rig, monkeypatch, platform):
    conn, calls = rig
    monkeypatch.setattr(connection, "IS_MAC", platform == "darwin")
    conn.connect(serverless.only_profile())
    assert not any(c[0] == "add_host_route" for c in calls)
    assert not any(c[0] == "resolve" for c in calls)
    started = [c[1] for c in calls if c[0] == "start"]
    assert started and serverless.DOH_URLS[0] in started[0]["dns"]["servers"]
    assert started[0]["dns"]["servers"][-1]["address"] == "192.0.2.53"
    assert not conn.state.server_ip
    assert State().profile_uid == serverless.ONLY_UID
    conn.disconnect()
    assert not State().is_connected()


def test_a_failed_connect_with_no_server_still_cleans_up(rig, monkeypatch):
    conn, calls = rig
    monkeypatch.setattr(connection, "IS_MAC", False)
    monkeypatch.setattr(connection.network, "wait_for_tun", lambda **k: None)
    with pytest.raises(connection.ConnectError):
        conn.connect(serverless.only_profile())
    assert not conn.state.is_connected()
    assert not any(c[0] == "add_host_route" for c in calls)
    assert ("stop",) in calls


def test_repair_route_with_no_saved_server_does_nothing(rig, monkeypatch):
    conn, calls = rig
    monkeypatch.setattr(connection, "IS_MAC", False)
    conn.connect(serverless.only_profile())
    monkeypatch.setattr(connection.network, "detect_interface",
                        lambda: Interface("eth0", "192.0.2.2", "192.0.2.77"))
    calls.clear()
    assert conn.repair_route_if_needed() is None
    assert calls == []


def test_the_rendered_config_passes_the_real_binary(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    assert xraycheck.check_config(_text()) is None
