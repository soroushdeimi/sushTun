"""WireGuard lane orchestration: connect/disconnect route bookkeeping and guards."""
from __future__ import annotations

import pytest

from xrayui import paths
from xrayui.core import wgtunnel
from xrayui.core.network import Interface
from xrayui.core.profiles import Profile


def _patch_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)


def _wg_profile(**overrides) -> Profile:
    base = dict(
        protocol="wireguard", address="home.example.com", port=51820,
        id="cCWrsuGEXF6jGYh13IXrgA2lh7eJFRGX3h1VOZrNkmE=",
        pbk="bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
        wg_local_address="10.10.0.2/32",
    )
    base.update(overrides)
    return Profile(**base)


def _make_tunnel(monkeypatch, tmp_path, on_step=None):
    _patch_state_dir(monkeypatch, tmp_path)
    return wgtunnel.WgTunnel(on_step=on_step)


def test_connect_rejects_non_wireguard_profile(monkeypatch, tmp_path):
    t = _make_tunnel(monkeypatch, tmp_path)
    with pytest.raises(wgtunnel.WgError, match="WireGuard"):
        t.connect(Profile(protocol="vless", address="a.com", id="u"))


def test_connect_rejects_wg_reserved_profile(monkeypatch, tmp_path):
    t = _make_tunnel(monkeypatch, tmp_path)
    with pytest.raises(wgtunnel.WgError, match="Reserved"):
        t.connect(_wg_profile(wg_reserved="1,2,3"))


def test_connect_rejects_full_tunnel_while_proxy_up(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    (tmp_path / "connected.flag").write_text("connected", encoding="utf-8")
    t = wgtunnel.WgTunnel()
    with pytest.raises(wgtunnel.WgError, match="full tunnel"):
        t.connect(_wg_profile(wg_allowed_ips=""))


def _patch_happy_path(monkeypatch, iface, added_prefixes, host_routes):
    monkeypatch.setattr(wgtunnel.network, "detect_interface", lambda: iface)
    monkeypatch.setattr(wgtunnel, "_resolve", lambda host: "203.0.113.10")
    monkeypatch.setattr(wgtunnel.network, "add_host_route",
                         lambda ip, gw: host_routes.append(ip))
    monkeypatch.setattr(wgtunnel.wg_mod.WireGuardTunnel, "start", lambda self: None)
    monkeypatch.setattr(wgtunnel.wg_mod, "wait_for_uapi", lambda device, timeout=15.0: True)
    monkeypatch.setattr(wgtunnel.wg_mod, "uapi_set", lambda device, payload: "errno=0\n\n")
    monkeypatch.setattr(wgtunnel.network, "wait_for_tun", lambda device: 42)
    monkeypatch.setattr(wgtunnel.WgTunnel, "_assign_address", lambda self, profile, tun_index: None)
    monkeypatch.setattr(wgtunnel.network, "add_prefix_route",
                         lambda prefix, tun_index: added_prefixes.append(prefix))


def test_connect_lan_collision_warns_but_does_not_block(monkeypatch, tmp_path):
    messages = []
    t = _make_tunnel(monkeypatch, tmp_path, on_step=messages.append)
    iface = Interface("Wi-Fi", "192.168.1.50", "192.168.1.1", 5)
    _patch_happy_path(monkeypatch, iface, [], [])

    t.connect(_wg_profile(wg_allowed_ips="192.168.1.0/24"))

    assert any("Warning" in m and "192.168.1.0/24" in m for m in messages)
    assert t.state.is_connected()


def test_connect_happy_path_records_state_and_routes(monkeypatch, tmp_path):
    t = _make_tunnel(monkeypatch, tmp_path)
    iface = Interface("Wi-Fi", "10.0.0.5", "10.0.0.1", 5)
    added_prefixes: list[str] = []
    host_routes: list[str] = []
    _patch_happy_path(monkeypatch, iface, added_prefixes, host_routes)

    profile = _wg_profile(wg_allowed_ips="192.168.1.0/24, 10.0.0.0/8")
    t.connect(profile)

    assert added_prefixes == ["192.168.1.0/24", "10.0.0.0/8"]
    assert host_routes == ["203.0.113.10"]
    assert t.state.is_connected()
    assert t.state.routes() == added_prefixes
    assert t.state.endpoint_ip == "203.0.113.10"
    assert t.state.profile_uid == profile.uid


def test_connect_skips_host_pin_when_endpoint_via_proxy(monkeypatch, tmp_path):
    t = _make_tunnel(monkeypatch, tmp_path)
    iface = Interface("Wi-Fi", "10.0.0.5", "10.0.0.1", 5)
    added_prefixes: list[str] = []
    host_routes: list[str] = []
    _patch_happy_path(monkeypatch, iface, added_prefixes, host_routes)

    t.connect(_wg_profile(wg_allowed_ips="192.168.1.0/24", wg_endpoint_via_proxy=True))
    assert host_routes == []


def test_connect_failure_tears_down_partial_state(monkeypatch, tmp_path):
    t = _make_tunnel(monkeypatch, tmp_path)
    iface = Interface("Wi-Fi", "10.0.0.5", "10.0.0.1", 5)
    removed_hosts = []
    monkeypatch.setattr(wgtunnel.network, "detect_interface", lambda: iface)
    monkeypatch.setattr(wgtunnel, "_resolve", lambda host: "203.0.113.10")
    monkeypatch.setattr(wgtunnel.network, "add_host_route", lambda ip, gw: None)
    monkeypatch.setattr(wgtunnel.network, "remove_host_route", lambda ip: removed_hosts.append(ip))
    monkeypatch.setattr(wgtunnel.wg_mod.WireGuardTunnel, "start", lambda self: None)
    monkeypatch.setattr(wgtunnel.wg_mod.WireGuardTunnel, "stop", lambda self: None)
    monkeypatch.setattr(wgtunnel.wg_mod, "wait_for_uapi", lambda device, timeout=15.0: False)

    with pytest.raises(wgtunnel.WgError, match="UAPI"):
        t.connect(_wg_profile(wg_allowed_ips="192.168.1.0/24"))

    assert removed_hosts == ["203.0.113.10"]
    assert not t.state.is_connected()


def test_disconnect_removes_exactly_recorded_routes(monkeypatch, tmp_path):
    t = _make_tunnel(monkeypatch, tmp_path)
    t.state.save("sushTun", "uid123", 42, "203.0.113.10", ["192.168.1.0/24", "10.0.0.0/8"])

    removed_prefixes = []
    removed_hosts = []
    stopped = []

    monkeypatch.setattr(
        wgtunnel.network, "remove_prefix_route",
        lambda prefix, tun_index: removed_prefixes.append((prefix, tun_index)),
    )
    monkeypatch.setattr(wgtunnel.network, "remove_host_route", lambda ip: removed_hosts.append(ip))
    monkeypatch.setattr(wgtunnel.wg_mod.WireGuardTunnel, "stop", lambda self: stopped.append(True))
    monkeypatch.setattr(wgtunnel.wg_mod.WireGuardTunnel, "is_running", lambda self: True)

    t.disconnect()

    assert {p for p, _ in removed_prefixes} == {"192.168.1.0/24", "10.0.0.0/8"}
    assert all(idx == 42 for _, idx in removed_prefixes)
    assert removed_hosts == ["203.0.113.10"]
    assert stopped == [True]
    assert not t.state.is_connected()


def test_recover_if_stale_cleans_up_when_wg_not_running(monkeypatch, tmp_path):
    t = _make_tunnel(monkeypatch, tmp_path)
    t.state.save("sushTun", "uid123", 42, "203.0.113.10", ["192.168.1.0/24"])
    monkeypatch.setattr(wgtunnel.wg_mod.WireGuardTunnel, "is_running", lambda self: False)
    monkeypatch.setattr(wgtunnel.wg_mod.WireGuardTunnel, "stop", lambda self: None)
    monkeypatch.setattr(wgtunnel.network, "remove_prefix_route", lambda prefix, tun_index: None)
    monkeypatch.setattr(wgtunnel.network, "remove_host_route", lambda ip: None)

    assert t.recover_if_stale() is True
    assert not t.state.is_connected()


def test_recover_if_stale_skips_when_wg_still_running(monkeypatch, tmp_path):
    t = _make_tunnel(monkeypatch, tmp_path)
    t.state.save("sushTun", "uid123", 42, "203.0.113.10", ["192.168.1.0/24"])
    monkeypatch.setattr(wgtunnel.wg_mod.WireGuardTunnel, "is_running", lambda self: True)

    assert t.recover_if_stale() is False
    assert t.state.is_connected()
