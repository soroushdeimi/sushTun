"""Firewall wiring in the connect/disconnect flow.

Proves the firewall is installed only when enabled, after the tunnel routes
are up, and removed on disconnect and on a failed connect. The network layer
is stubbed so nothing touches the host.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import connection, settings
from xrayui.core.network import DnsState, Interface
from xrayui.core.profiles import Profile

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
    monkeypatch.setattr(net, "detect_interface",
                        lambda: Interface("eth0", "192.0.2.2", "192.0.2.1"))
    monkeypatch.setattr(net, "foreign_tunnel", lambda _a: None)
    monkeypatch.setattr(net, "backup_dns", lambda _a: DnsState())
    monkeypatch.setattr(connection, "_resolve", lambda host: "192.0.2.9")
    for name in ("remove_routes", "add_host_route", "add_default_routes",
                 "set_dns_loopback", "restore_dns"):
        monkeypatch.setattr(net, name, lambda *a, _name=name, **k: calls.append((_name, *a)))
    monkeypatch.setattr(net, "release_stranded_dns", lambda **k: [])
    monkeypatch.setattr(net, "wait_for_tun", lambda **k: 7)
    monkeypatch.setattr(net, "configure_tun", lambda _t: True)
    # macOS path: stub the device/route calls so nothing touches the host.
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
    monkeypatch.setattr(conn.xray, "start", lambda p: calls.append(("start",)))
    monkeypatch.setattr(conn.xray, "stop", lambda: calls.append(("stop",)))
    monkeypatch.setattr(conn.xray, "is_running", lambda: True)
    monkeypatch.setattr(conn.tun2socks, "stop", lambda: None)
    profile = Profile(uid="p1", address="192.0.2.9", id="password")
    return conn, calls, cfg, profile


def _track(monkeypatch, calls):
    # Stub the firewall module so the real _install/_remove_firewall logic runs
    # (including the enabled guard) but no OS command is issued.
    import xrayui.core.firewall as fw
    monkeypatch.setattr(fw, "supported", lambda: True)
    monkeypatch.setattr(fw, "install", lambda *a, **k: calls.append(("fw_install",)))

    def _removed():
        calls.append(("fw_remove",))
        return []

    monkeypatch.setattr(fw, "remove", _removed)
    monkeypatch.setattr(fw, "recover_stale", _removed)


def test_no_firewall_commands_when_disabled(rig, monkeypatch):
    conn, calls, _cfg, profile = rig
    monkeypatch.setattr(connection, "IS_MAC", False)
    monkeypatch.setattr(connection, "IS_WIN", False)
    _track(monkeypatch, calls)
    conn.connect(profile)
    # Disabled by default: the firewall is never touched.
    assert ("fw_install",) not in calls and ("fw_remove",) not in calls


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_firewall_installed_after_routes_when_enabled(rig, monkeypatch, platform):
    conn, calls, cfg, profile = rig
    cfg["firewall"]["enabled"] = True
    monkeypatch.setattr(connection, "IS_MAC", platform == "darwin")
    monkeypatch.setattr(connection, "IS_WIN", platform == "win32")
    _track(monkeypatch, calls)
    conn.connect(profile)
    # The firewall goes in only after the tunnel routes are up.
    route_marker = ("split", True) if platform == "darwin" else ("add_default_routes", 7)
    assert ("fw_install",) in calls
    assert calls.index(route_marker) < calls.index(("fw_install",))


def test_firewall_removed_on_disconnect(rig, monkeypatch):
    conn, calls, cfg, profile = rig
    cfg["firewall"]["enabled"] = True
    monkeypatch.setattr(connection, "IS_MAC", False)
    monkeypatch.setattr(connection, "IS_WIN", False)
    _track(monkeypatch, calls)
    conn.connect(profile)
    conn.disconnect()
    assert calls.index(("fw_install",)) < calls.index(("fw_remove",))


def test_firewall_removed_on_failed_connect(rig, monkeypatch):
    conn, calls, cfg, profile = rig
    cfg["firewall"]["enabled"] = True
    monkeypatch.setattr(connection, "IS_MAC", False)
    monkeypatch.setattr(connection, "IS_WIN", False)
    _track(monkeypatch, calls)
    # Force a failure after the firewall would have been installed.
    monkeypatch.setattr(connection.network, "set_dns_loopback",
                        lambda _a: (_ for _ in ()).throw(OSError("no dns")))
    with pytest.raises(connection.ConnectError):
        conn.connect(profile)
    # The teardown path removed the firewall.
    assert ("fw_remove",) in calls


def test_install_firewall_warns_and_continues_when_unsupported(rig, monkeypatch):
    conn, _calls, cfg, _profile = rig
    cfg["firewall"]["enabled"] = True
    import xrayui.core.firewall as fw
    monkeypatch.setattr(fw, "supported", lambda: False)
    messages = []
    monkeypatch.setattr(conn, "_log", messages.append)
    conn._install_firewall("192.0.2.9", [], {})
    assert any("not supported" in m for m in messages)


def test_install_firewall_warns_and_continues_on_error(rig, monkeypatch):
    conn, _calls, cfg, _profile = rig
    cfg["firewall"]["enabled"] = True
    import xrayui.core.firewall as fw
    from xrayui.core._firewall_common import FirewallError
    monkeypatch.setattr(fw, "supported", lambda: True)
    monkeypatch.setattr(fw, "install",
                        lambda *a, **k: (_ for _ in ()).throw(FirewallError("nope")))
    messages = []
    monkeypatch.setattr(conn, "_log", messages.append)
    conn._install_firewall("192.0.2.9", [], {})
    assert any("could not be enabled" in m for m in messages)


def test_server_ips_include_multi_exit_servers(rig):
    conn, _calls, _cfg, _profile = rig
    from xrayui.core.exits import Exit
    exit_profile = Profile(uid="e1", address="198.51.100.7", id="password")
    exits = [Exit(user="work", profile=exit_profile)]
    assert conn._firewall_server_ips("192.0.2.9", exits, {}) == \
        ["192.0.2.9", "198.51.100.7"]
    assert conn._firewall_server_ips("", exits, {}) == ["198.51.100.7"]


def test_server_ips_include_dns_resolvers(rig):
    # The dns-out outbound dials resolvers directly out the uplink, so the
    # firewall must allow them or it would break DNS and the whole connection.
    conn, _calls, _cfg, _profile = rig
    dns_cfg = {"servers": ["https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"]}
    ips = conn._firewall_server_ips("192.0.2.9", [], dns_cfg)
    assert "1.1.1.1" in ips and "8.8.8.8" in ips and "192.0.2.9" in ips
    # A hostname resolver is resolved through the tunnel (loopback), not the
    # uplink, so it is not needed in the allowlist.
    assert conn._firewall_server_ips("192.0.2.9", [],
                                     {"servers": ["https://dns.example/dns-query"]}) \
        == ["192.0.2.9"]
