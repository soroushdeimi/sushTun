"""Chain lifecycle tests never change the host's network configuration."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import chains, connection, settings
from xrayui.core.network import DnsState, Interface
from xrayui.core.profiles import Profile, ProfileStore
from xrayui.core.state import State

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "runtime.json")
    monkeypatch.setattr(paths, "config_template", lambda: TEMPLATE)
    cfg = copy.deepcopy(settings.DEFAULTS)
    monkeypatch.setattr(connection.app_settings, "load", lambda: copy.deepcopy(cfg))
    calls = []
    net = connection.network
    monkeypatch.setattr(net, "detect_interface", lambda: Interface("eth0", "192.0.2.2", "192.0.2.1"))
    monkeypatch.setattr(net, "foreign_tunnel", lambda _a: None)
    monkeypatch.setattr(net, "backup_dns", lambda _a: DnsState())
    monkeypatch.setattr(connection, "_resolve", lambda host: calls.append(("resolve", host)) or "192.0.2.9")
    for name in ("remove_routes", "add_host_route", "add_default_routes", "set_dns_loopback",
                 "restore_dns"):
        monkeypatch.setattr(net, name, lambda *a, _name=name, **k: calls.append((_name, *a)))
    monkeypatch.setattr(net, "release_stranded_dns", lambda **k: [])
    monkeypatch.setattr(net, "wait_for_tun", lambda **k: 7)
    monkeypatch.setattr(net, "configure_tun", lambda _t: True)
    for name, fn in {
        "mac_other_vpn": lambda _a: None,
        "mac_ensure_scoped_default": lambda *a: False,
        "mac_wait_for_device": lambda **k: True,
        "mac_add_split_routes": lambda native: calls.append(("split", native)),
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
    items = [Profile(uid=f"hop-{i}", address=f"hop{i}.example", id="password") for i in range(3)]
    for item in items:
        ProfileStore().save(item)
    chain = chains.Chain(uid="ordered", name="Ordered", hops=[p.uid for p in items])
    return conn, calls, items, chain, cfg


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin", "mac-bridge"])
def test_entry_owns_route_dns_and_recovery_state(rig, monkeypatch, platform):
    conn, calls, items, chain, _cfg = rig
    monkeypatch.setattr(connection, "IS_MAC", platform in ("darwin", "mac-bridge"))
    monkeypatch.setattr(connection, "IS_WIN", platform == "win32")
    if platform == "mac-bridge":
        monkeypatch.setattr(connection.network, "mac_wait_for_device", lambda **k: False)
    conn.connect(chain)
    assert ("resolve", items[0].address) in calls
    assert not any(c == ("resolve", p.address) for p in items[1:] for c in calls)
    assert ("add_host_route", "192.0.2.9", "192.0.2.1") in calls
    for c in calls:
        if c[0] == "start":
            assert c[1]["dns"]["hosts"][items[0].address] == "192.0.2.9"
            assert items[-1].address not in c[1]["dns"]["hosts"]
    assert conn.state.server_ip == "192.0.2.9"
    assert State().chain_uid == chain.uid
    assert State().profile_uid == items[-1].uid
    conn.disconnect()
    assert ("remove_routes", "192.0.2.9") in calls
    assert State().chain_uid is None
    assert not State().is_connected()


@pytest.mark.parametrize("invalid", ["missing", "mux", "credential"])
def test_invalid_chain_rejected_before_any_network_action(rig, monkeypatch, invalid):
    conn, calls, items, chain, cfg = rig
    if invalid == "missing":
        chain.hops.append("gone")
    elif invalid == "mux":
        cfg["core"]["mux"]["enabled"] = True
    else:
        items[1].id = ""
        ProfileStore().save(items[1])
    monkeypatch.setattr(connection.network, "detect_interface", lambda: pytest.fail("network touched"))
    with pytest.raises(connection.ConnectError):
        conn.connect(chain)
    assert calls == []


def test_resolved_chain_can_connect_without_store_lookup(rig, monkeypatch):
    conn, _calls, items, chain, _cfg = rig
    plan = chains.resolve(chain, items)
    monkeypatch.setattr(ProfileStore, "list", lambda: pytest.fail("looked up saved profiles"))
    conn.connect(plan)
    assert conn.state.chain_uid == chain.uid


def test_failed_chain_start_cleans_entry_route(rig, monkeypatch):
    conn, calls, _items, chain, _cfg = rig
    monkeypatch.setattr(connection, "IS_MAC", False)
    monkeypatch.setattr(connection.network, "wait_for_tun", lambda **k: None)
    with pytest.raises(connection.ConnectError):
        conn.connect(chain)
    assert calls.count(("remove_routes", "192.0.2.9")) == 2
    assert not conn.state.is_connected()
    assert not any(c[0] == "set_dns_loopback" for c in calls)


def test_single_server_save_clears_stale_chain_id(rig):
    conn, _calls, _items, chain, _cfg = rig
    conn.connect(chain)
    conn.state.save(Interface("eth0", "192.0.2.2", "192.0.2.1"), "192.0.2.4", 7,
                    DnsState(), profile_uid="single")
    assert conn.state.chain_uid is None
    assert conn.state.profile_uid == "single"


def test_stale_chain_recovery_removes_entry_route(rig, monkeypatch):
    conn, calls, _items, chain, _cfg = rig
    conn.connect(chain)
    monkeypatch.setattr(connection.xray_mod, "is_xray_running", lambda: False)
    calls.clear()
    assert conn.recover_if_stale()
    assert ("remove_routes", "192.0.2.9") in calls
    assert conn.state.chain_uid is None
    assert not conn.state.is_connected()


def test_invalid_chain_leaves_existing_connection_intact(rig):
    conn, calls, _items, chain, _cfg = rig
    conn.connect(chain)
    calls.clear()
    chain.hops.append("missing")
    with pytest.raises(connection.ConnectError, match="no longer exists"):
        conn.connect(chain)
    assert calls == []
    assert conn.state.is_connected()
    assert conn.state.chain_uid == chain.uid


def test_deleted_hop_error_shows_no_internal_id(rig):
    conn, calls, items, chain, _cfg = rig
    ProfileStore().delete(items[1].uid)
    with pytest.raises(connection.ConnectError) as caught:
        conn.connect(chain)
    assert "no longer exists" in str(caught.value)
    assert not any(p.uid in str(caught.value) for p in items)
    assert calls == []
