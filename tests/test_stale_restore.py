"""Stale-session recovery: leftover DNS after a crash or power-off."""
from __future__ import annotations

import sys
import types

import pytest

from xrayui import paths
from xrayui.core import bootrestore, connection, network
from xrayui.core.network import DnsState, Interface
from xrayui.core.state import State, WgState


def _patch_state(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "config.runtime.json")


def _write_connected(tmp_path, alias="Wi-Fi"):
    state = State()
    iface = Interface(alias, "192.168.1.50", "192.168.1.1", 12)
    state.save(iface, "203.0.113.10", 23, DnsState(mode="DHCP", servers=[]))
    return state


def test_recover_if_stale_restores_when_xray_is_dead(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    _write_connected(tmp_path)

    calls = []
    monkeypatch.setattr(connection.xray_mod, "is_xray_running", lambda: False)
    monkeypatch.setattr(connection.network, "remove_routes", lambda ip=None: calls.append(("routes", ip)))
    monkeypatch.setattr(
        connection.network, "restore_dns",
        lambda alias, dns, retries=1: calls.append(("dns", alias, retries)) or True,
    )
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: calls.append(("uninstall",)))
    monkeypatch.setattr(connection.hotspot, "disable", lambda: calls.append(("ics",)))

    conn = connection.Connection()
    conn.xray.stop = lambda: calls.append(("xray-stop",))
    conn.tun2socks.stop = lambda: None
    assert conn.recover_if_stale(dns_retries=3) is True
    assert ("dns", "Wi-Fi", 3) in calls
    assert ("uninstall",) in calls
    assert not conn.state.is_connected()


def test_recover_if_stale_skips_when_xray_still_running(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    _write_connected(tmp_path)
    monkeypatch.setattr(connection.xray_mod, "is_xray_running", lambda: True)
    restored = []
    monkeypatch.setattr(connection.Connection, "_restore", lambda self, dns_retries=1: restored.append(True))

    conn = connection.Connection()
    assert conn.recover_if_stale() is False
    assert restored == []
    assert conn.state.is_connected()


def test_recover_if_stale_noop_when_not_connected(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(connection.xray_mod, "is_xray_running", lambda: False)
    conn = connection.Connection()
    assert conn.recover_if_stale() is False


def test_restore_clears_gateway_flag(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    state = _write_connected(tmp_path)
    state.set_gateway(True)
    monkeypatch.setattr(connection.network, "remove_routes", lambda ip=None: None)
    monkeypatch.setattr(connection.network, "restore_dns", lambda *a, **k: True)
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: None)
    ics = []
    monkeypatch.setattr(connection.hotspot, "disable", lambda: ics.append(True))

    conn = connection.Connection()
    conn.xray.stop = lambda: None
    conn.tun2socks.stop = lambda: None
    conn._restore()
    assert ics == [True]
    assert not conn.state.gateway_on()


def test_restore_leaves_wg_lane_state_untouched(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    _write_connected(tmp_path)
    wg_state = WgState()
    wg_state.save("sushTun", "wg-uid", 7, "198.51.100.5", ["192.168.1.0/24"])

    monkeypatch.setattr(connection.network, "remove_routes", lambda ip=None: None)
    monkeypatch.setattr(connection.network, "restore_dns", lambda *a, **k: True)
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: None)
    monkeypatch.setattr(connection.hotspot, "disable", lambda: None)

    conn = connection.Connection()
    conn.xray.stop = lambda: None
    conn.tun2socks.stop = lambda: None
    conn._restore()

    assert not conn.state.is_connected()
    assert wg_state.is_connected()
    assert wg_state.routes() == ["192.168.1.0/24"]
    assert wg_state.device == "sushTun"


def test_connect_refuses_while_wg_lane_runs_full_tunnel(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    wg_state = WgState()
    wg_state.save("sushTun", "wg-uid", 7, "198.51.100.5", ["0.0.0.0/0", "::/0"])

    from xrayui.core.profiles import Profile
    conn = connection.Connection()
    with pytest.raises(connection.ConnectError, match="WireGuard lane"):
        conn.connect(Profile(protocol="vless", address="a.com", id="u", port=443))


def test_connect_allows_when_wg_lane_runs_split_tunnel(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    wg_state = WgState()
    wg_state.save("sushTun", "wg-uid", 7, "198.51.100.5", ["192.168.1.0/24"])
    monkeypatch.setattr(connection.network, "detect_interface", lambda: None)

    from xrayui.core.profiles import Profile
    conn = connection.Connection()
    with pytest.raises(connection.ConnectError, match="no active internet interface"):
        conn.connect(Profile(protocol="vless", address="a.com", id="u", port=443))


def test_bootrestore_action_uses_restore_flag(monkeypatch):
    monkeypatch.setattr(bootrestore.sys, "frozen", True, raising=False)
    monkeypatch.setattr(bootrestore.sys, "executable", r"C:\Apps\sushTun.exe")
    exe, arg = bootrestore._action()
    assert exe.endswith("sushTun.exe")
    assert arg == "--restore-stale"


def test_restore_argv_detects_flag():
    assert bootrestore.is_restore_argv(["sushTun.exe", "--restore-stale"])
    assert not bootrestore.is_restore_argv(["sushTun.exe"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows adapter DNS")
def test_restore_dns_falls_back_to_netsh(monkeypatch):
    monkeypatch.setattr(
        network.proc, "powershell",
        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout=""),
    )
    ran = []

    def fake_run(args, **k):
        ran.append(args)
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(network.proc, "run", fake_run)
    ok = network.restore_dns("Wi-Fi", DnsState(mode="DHCP"), retries=1)
    assert ok
    assert any("dhcp" in " ".join(a) for a in ran)
    assert any("/flushdns" in a for a in ran)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows adapter DNS")
def test_restore_dns_retries_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def once(alias, state):
        attempts["n"] += 1
        return attempts["n"] >= 2

    monkeypatch.setattr(network, "_restore_dns_once", once)
    monkeypatch.setattr(network.time, "sleep", lambda *_: None)
    monkeypatch.setattr(network, "_flush_dns", lambda: None)
    assert network.restore_dns("Wi-Fi", DnsState(), retries=3)
    assert attempts["n"] == 2
