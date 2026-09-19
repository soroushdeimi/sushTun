"""Multi-exit port: one local SOCKS port, a different server per username."""
from __future__ import annotations

import copy
import json
import socket
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import connection, exits, render, routing, settings, xraycheck
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden_main.json"

MAIN = Profile(uid="main", protocol="vless", address="m.example", port=443,
               id="11111111-1111-1111-1111-111111111111", network="tcp", security="tls",
               sni="m.example")
DE = Profile(uid="de1", protocol="vless", address="de.example", port=443,
             id="22222222-2222-2222-2222-222222222222", network="tcp", security="reality",
             sni="www.example.com", pbk="Z84J2IelR9ch3k8VtlVhhs5ycBUlXA7wHBWcBrjqnAw", sid="ab")
NL = Profile(uid="nl1", protocol="trojan", address="nl.example", port=443, id="pw",
             network="ws", security="tls", sni="nl.example", path="/ws")
PROFILES = {p.uid: p for p in (MAIN, DE, NL)}


def _exits_cfg(**over) -> dict:
    cfg = {"enabled": True, "port": 10809, "password": "s3cret",
           "items": [{"user": "de", "profile_uid": "de1"}, {"user": "nl", "profile_uid": "nl1"}]}
    cfg.update(over)
    return cfg


def _core() -> dict:
    return copy.deepcopy(settings.DEFAULTS["core"])


@pytest.fixture(autouse=True)
def _port_free(monkeypatch):
    monkeypatch.setattr(exits, "port_is_free", lambda port: True)


def _render(exit_list, exits_cfg, core=None, profile=MAIN) -> dict:
    r = settings.DEFAULTS["routing"]
    return json.loads(render.build_text(
        profile=profile, iface_alias="eth0", template_path=TEMPLATE,
        routing_rules=routing.build_rules(r), domain_strategy=routing.domain_strategy_for(r),
        stats=True, dns_cfg=settings.DEFAULTS["dns"], server_ip="203.0.113.7",
        core_cfg=core or _core(), exits=exit_list, exits_cfg=exits_cfg))


# -- off means untouched ----------------------------------------------------------
def test_off_by_default():
    assert settings.DEFAULTS["exits"]["enabled"] is False
    assert exits.prepare(settings.DEFAULTS["exits"], _core(), PROFILES.get) == ([], None)


def test_off_renders_main_branch_golden_configs_byte_for_byte():
    # The path the app really takes: prepare() with the defaults, then render.
    from tests.test_golden_main import _profiles, _variants
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["configs"]
    exit_list, warning = exits.prepare(settings.DEFAULTS["exits"], _core(), PROFILES.get)
    assert warning is None
    for pname, profile in _profiles().items():
        for vname, v in _variants().items():
            text = render.build_text(
                profile=profile, iface_alias="eth0", template_path=TEMPLATE,
                routing_rules=routing.build_rules(v["routing"]),
                domain_strategy=routing.domain_strategy_for(v["routing"]),
                stats=v["stats"], include_tun=v["include_tun"], log_level="warning",
                dns_cfg=v["dns"], tun_mtu=1420, server_ip="203.0.113.7", core_cfg=v["core"],
                exits=exit_list, exits_cfg=settings.DEFAULTS["exits"])
            assert text == golden[f"{pname}/{vname}"], f"{pname}/{vname}"


# -- prepare: every problem drops the whole feature -----------------------------------
def test_prepare_returns_one_exit_per_username():
    exit_list, warning = exits.prepare(_exits_cfg(), _core(), PROFILES.get)
    assert warning is None
    assert [(e.user, e.profile.uid) for e in exit_list] == [("de", "de1"), ("nl", "nl1")]


@pytest.mark.parametrize("over,reason", [
    ({"port": 80}, "between 1024 and 65535"),
    ({"port": "10809"}, "between 1024 and 65535"),
    ({"port": 10808}, "already used by sushTun"),   # the local SOCKS port
    ({"port": 10085}, "already used by sushTun"),   # the stats API
    ({"password": ""}, "password is required"),
    ({"items": []}, "at least one exit"),
    ({"items": [{"user": "DE", "profile_uid": "de1"}]}, "not a valid username"),
    ({"items": [{"user": "de", "profile_uid": "de1"},
                {"user": "de", "profile_uid": "nl1"}]}, "used twice"),
    ({"items": [{"user": "de", "profile_uid": "gone"}]}, "no longer exists"),
])
def test_prepare_drops_the_whole_feature_on_a_bad_setting(over, reason):
    exit_list, warning = exits.prepare(_exits_cfg(**over), _core(), PROFILES.get)
    assert exit_list == []
    assert reason in warning


def test_prepare_drops_the_feature_when_the_port_is_busy(monkeypatch):
    monkeypatch.undo()  # the real bind test
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        if port < 1024:
            pytest.skip("the OS handed out a privileged port")
        exit_list, warning = exits.prepare(_exits_cfg(port=port), _core(), PROFILES.get)
    assert exit_list == []
    assert f"port {port} is in use" in warning


def test_connection_logs_the_warning_and_keeps_going(monkeypatch):
    monkeypatch.setattr(connection.ProfileStore, "get", lambda self, uid: PROFILES.get(uid))
    steps: list[str] = []
    conn = connection.Connection(on_step=steps.append)
    assert conn._exits({"exits": _exits_cfg(password=""), "core": _core()}) == []
    assert steps and steps[0].startswith("WARNING: Multi-exit port is off")


# -- apply ------------------------------------------------------------------------------
def _exit_list(**over):
    exit_list, warning = exits.prepare(_exits_cfg(**over), _core(), PROFILES.get)
    assert warning is None
    return exit_list


def test_inbound_is_local_password_socks_without_udp():
    out = _render(_exit_list(), _exits_cfg())
    inbound = next(i for i in out["inbounds"] if i["tag"] == "exits-in")
    assert inbound["listen"] == "127.0.0.1" and inbound["port"] == 10809
    assert inbound["settings"] == {
        "auth": "password", "udp": False,
        "accounts": [{"user": "de", "pass": "s3cret"}, {"user": "nl", "pass": "s3cret"}]}


def test_each_exit_has_its_own_outbound_bound_to_the_physical_interface():
    out = _render(_exit_list(), _exits_cfg())
    tags = [o["tag"] for o in out["outbounds"]]
    assert "exit-de1" in tags and "exit-nl1" in tags
    for tag in ("exit-de1", "exit-nl1"):
        ob = next(o for o in out["outbounds"] if o["tag"] == tag)
        assert ob["streamSettings"]["sockopt"]["interface"] == "eth0"


def test_exit_rules_come_before_every_user_rule():
    out = _render(_exit_list(), _exits_cfg())
    rules = out["routing"]["rules"]
    exit_idx = [i for i, r in enumerate(rules) if r.get("inboundTag") == ["exits-in"]]
    first_user = next(i for i, r in enumerate(rules) if "inboundTag" not in r)
    assert exit_idx and max(exit_idx) < first_user  # so Iran-direct can't win
    assert rules[exit_idx[0]] == {"type": "field", "inboundTag": ["exits-in"], "user": ["de"],
                                  "outboundTag": "exit-de1"}
    assert rules[exit_idx[-1]] == {"type": "field", "inboundTag": ["exits-in"],
                                   "outboundTag": "block"}


def test_the_live_server_as_an_exit_reuses_the_proxy_outbound():
    items = [{"user": "main", "profile_uid": "main"}]
    out = _render(_exit_list(items=items), _exits_cfg(items=items))
    assert [o["tag"] for o in out["outbounds"]].count("exit-main") == 0
    rule = next(r for r in out["routing"]["rules"] if r.get("user") == ["main"])
    assert rule["outboundTag"] == "proxy"


def test_core_options_apply_to_exits_like_the_main_server(monkeypatch):
    from xrayui.core import coreopts
    monkeypatch.setattr(coreopts, "available_tcp_congestion", lambda: ["reno"])
    core = _core()
    core["fragment"]["enabled"] = True
    core["mux"]["enabled"] = True
    core["default_fp"] = "chrome"
    core["sockopt"] = {"tcp_fast_open": True, "tcp_mptcp": False, "tcp_congestion": "reno"}
    out = _render(_exit_list(), _exits_cfg(), core=core)
    nl = next(o for o in out["outbounds"] if o["tag"] == "exit-nl1")  # trojan: mux-eligible
    assert nl["mux"]["enabled"] is True
    assert nl["streamSettings"]["tlsSettings"]["fingerprint"] == "chrome"
    assert nl["streamSettings"]["finalmask"]["tcp"][0]["type"] == "fragment"
    assert nl["streamSettings"]["sockopt"]["tcpFastOpen"] is True
    assert nl["streamSettings"]["sockopt"]["tcpCongestion"] == "reno"


def test_xray_test_accepts_the_multi_exit_config(tmp_path, monkeypatch):
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    text = render.build_text(profile=MAIN, iface_alias="lo", template_path=TEMPLATE,
                             include_tun=False, core_cfg=_core(),
                             exits=_exit_list(), exits_cfg=_exits_cfg())
    assert '"tag": "exits-in"' in text  # also without a DNS config
    assert xraycheck.check_config(text) is None
