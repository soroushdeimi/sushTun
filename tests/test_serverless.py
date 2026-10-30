"""Serverless entry: the first server is dialed through a fragmenting outbound."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import chains, connection, render, serverless, xraycheck
from xrayui.core import settings as app_settings
from xrayui.core.profiles import Profile, ProfileStore

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"
ON = {"enabled": True}


def _skip_if_no_binary():
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")


def _profile(**over) -> Profile:
    base = dict(name="p", protocol="vless", address="a.example.com", port=443,
                id="11111111-1111-1111-1111-111111111111", encryption="none",
                network="tcp", security="tls", sni="a.example.com")
    base.update(over)
    return Profile(**base)


def _core(**over) -> dict:
    d = copy.deepcopy(app_settings.DEFAULTS["core"])
    d.update(over)
    return d


def _text(profile=None, **kw) -> str:
    return render.build_text(profile or _profile(), "lo", TEMPLATE, include_tun=False, **kw)


def _render(profile=None, **kw) -> dict:
    return json.loads(_text(profile, **kw))


def _out(cfg: dict, tag: str) -> dict:
    return next(o for o in cfg["outbounds"] if o["tag"] == tag)


def _chain_plan():
    items = [_profile(uid="h0", address="hop0.example"),
             _profile(uid="h1", address="hop1.example", sni="hop1.example")]
    return chains.resolve(chains.Chain(uid="c", name="c", hops=["h0", "h1"]), items)


def test_off_is_a_no_op():
    base = _text()
    for off in (None, {"enabled": False}, {"enabled": "yes"}, {}):
        assert _text(serverless_cfg=off) == base


def test_default_setting_is_off():
    assert app_settings.DEFAULTS["serverless"] == {"enabled": False}


def test_single_server_goes_through_serverless():
    cfg = _render(serverless_cfg=ON)
    assert _out(cfg, "proxy")["streamSettings"]["sockopt"] == {"dialerProxy": "serverless"}
    sl = _out(cfg, "serverless")
    assert cfg["outbounds"][0]["tag"] == "proxy"
    assert cfg["outbounds"][-1] is not cfg["outbounds"][0]
    assert sl["protocol"] == "freedom"
    assert sl["streamSettings"]["sockopt"]["interface"] == "lo"
    masks = sl["streamSettings"]["finalmask"]["tcp"]
    # Segment split must come before the TLS-record split or the latter no-ops.
    assert masks[0]["settings"]["packets"] == "1-1"
    assert masks[1]["settings"]["packets"] == "tlshello"
    for mask in masks:
        assert "lengths" not in mask["settings"]
        assert "delays" not in mask["settings"]


def test_hostname_entry_is_pinned_to_server_ip():
    cfg = _render(serverless_cfg=ON, server_ip="203.0.113.7")
    assert cfg["dns"]["hosts"]["a.example.com"] == "203.0.113.7"
    assert _out(cfg, "serverless")["settings"]["domainStrategy"] == "ForceIPv4"


def test_ip_literal_entry_adds_no_hosts_pin():
    cfg = _render(_profile(address="198.51.100.4"), serverless_cfg=ON, server_ip="198.51.100.4")
    assert "198.51.100.4" not in (cfg.get("dns", {}).get("hosts") or {})


def test_chain_entry_moves_and_exit_keeps_its_dialer():
    cfg = _render(_chain_plan(), serverless_cfg=ON, server_ip="203.0.113.7")
    sockopt = _out(cfg, "chain-1")["streamSettings"]["sockopt"]
    assert sockopt["dialerProxy"] == "serverless"
    assert "domainStrategy" not in sockopt
    assert "interface" not in sockopt
    assert _out(cfg, "proxy")["streamSettings"]["sockopt"]["dialerProxy"] == "chain-1"
    assert cfg["outbounds"][0]["tag"] == "proxy"
    assert cfg["dns"]["hosts"]["hop0.example"] == "203.0.113.7"


def test_existing_fragment_is_stripped_from_entry():
    core = _core(fragment={"enabled": True, "packets": "tlshello", "length": "100-200",
                           "interval": "10-20", "max_split": 0})
    cfg = _render(core_cfg=core, serverless_cfg=ON)
    assert "finalmask" not in _out(cfg, "proxy")["streamSettings"]
    assert len(_out(cfg, "serverless")["streamSettings"]["finalmask"]["tcp"]) == 2


def test_tcp_fast_open_moves_to_serverless():
    core = _core(sockopt={"tcp_fast_open": True, "tcp_mptcp": False, "tcp_congestion": ""})
    cfg = _render(core_cfg=core, serverless_cfg=ON)
    assert _out(cfg, "serverless")["streamSettings"]["sockopt"]["tcpFastOpen"] is True
    assert "tcpFastOpen" not in _out(cfg, "proxy")["streamSettings"]["sockopt"]


def test_apply_keeps_udp_mask_and_other_sockopt():
    cfg = {"outbounds": [{"tag": "proxy", "streamSettings": {
        "sockopt": {"interface": "x", "mark": 5},
        "finalmask": {"tcp": [{}], "udp": [{"type": "noise"}]}}}]}
    serverless.apply(cfg, "h.example", None)
    stream = cfg["outbounds"][0]["streamSettings"]
    assert stream["finalmask"] == {"udp": [{"type": "noise"}]}
    assert stream["sockopt"] == {"mark": 5, "dialerProxy": "serverless"}


def test_apply_without_entry_changes_nothing():
    cfg = {"outbounds": [{"tag": "direct"}]}
    serverless.apply(cfg, "h.example", "203.0.113.7")
    assert cfg == {"outbounds": [{"tag": "direct"}]}


@pytest.mark.parametrize("raw,expected", [
    (None, False), ({}, False), ({"enabled": 1}, False), ({"enabled": "true"}, False),
    ({"enabled": False}, False), ({"enabled": True}, True),
])
def test_enabled_needs_exact_true(raw, expected):
    assert serverless.enabled(raw) is expected


@pytest.mark.parametrize("security", ["tls", "reality"])
def test_problem_none_for_tls_and_reality(security):
    assert serverless.problem(_profile(security=security)) is None


@pytest.mark.parametrize("over", [
    {"security": "none"},
    {"protocol": "hysteria2"},
    {"protocol": "wireguard"},
    {"network": "xhttp", "xhttp_extra": '{"downloadSettings":{"address":"elsewhere"}}'},
])
def test_problem_has_message_for_unsupported_entry(over):
    assert serverless.problem(_profile(**over))


def test_xhttp_without_download_settings_is_allowed():
    assert serverless.problem(_profile(network="xhttp")) is None


def test_ineligible_entry_is_not_rewritten():
    cfg = _render(_profile(security="none"), serverless_cfg=ON)
    assert all(o["tag"] != "serverless" for o in cfg["outbounds"])


def test_outbound_returns_independent_copies():
    first = serverless.outbound()
    first["streamSettings"]["finalmask"]["tcp"][0]["settings"]["length"] = "9"
    first["streamSettings"]["sockopt"]["x"] = 1
    again = serverless.outbound()
    assert again["streamSettings"]["finalmask"]["tcp"][0]["settings"]["length"] == "1-114"
    assert again["streamSettings"]["sockopt"] == {"interface": "__IFACE__"}


def test_connect_refuses_ineligible_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "runtime.json")
    cfg = copy.deepcopy(app_settings.DEFAULTS)
    cfg["serverless"]["enabled"] = True
    monkeypatch.setattr(connection.app_settings, "load", lambda: copy.deepcopy(cfg))
    monkeypatch.setattr(connection.network, "detect_interface", lambda: pytest.fail("network touched"))
    with pytest.raises(connection.ConnectError, match="TLS"):
        connection.Connection().connect(_profile(security="none"))


def test_connect_refuses_ineligible_chain_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    cfg = copy.deepcopy(app_settings.DEFAULTS)
    cfg["serverless"]["enabled"] = True
    monkeypatch.setattr(connection.app_settings, "load", lambda: copy.deepcopy(cfg))
    monkeypatch.setattr(connection.network, "detect_interface", lambda: pytest.fail("network touched"))
    items = [_profile(uid="h0", address="hop0.example", security="none"),
             _profile(uid="h1", address="hop1.example")]
    for item in items:
        ProfileStore().save(item)
    chain = chains.Chain(uid="c", name="c", hops=["h0", "h1"])
    with pytest.raises(connection.ConnectError):
        connection.Connection().connect(chain)


def test_xray_accepts_serverless_config():
    _skip_if_no_binary()
    assert xraycheck.check_config(_text(serverless_cfg=ON)) is None
