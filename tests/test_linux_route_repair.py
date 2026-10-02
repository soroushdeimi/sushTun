"""Linux route failures must not become successful connection state."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from tests.test_tun_routing import _iface, _stub_connect
from xrayui import paths
from xrayui.core import _net_posix as posix
from xrayui.core import connection, network
from xrayui.core.network import DnsState, Interface

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux routes")
SERVER = "203.0.113.10"
GATEWAY = "192.0.2.1"
SPLIT = ("0.0.0.0/1", "128.0.0.0/1")


def _commands(monkeypatch, *, routes=None, fail=None):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        failed = fail is not None and fail(args)
        return SimpleNamespace(returncode=2 if failed else 0,
                               stdout=json.dumps(routes or []),
                               stderr="RTNETLINK: denied" if failed else "")

    monkeypatch.setattr(posix.proc, "run", run)
    return calls


def _healthy_routes():
    return [{"dst": dest, "dev": "xray0"} for dest in SPLIT]


def _connected(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    conn = connection.Connection()
    conn.state.save(Interface("eth0", "192.0.2.2", GATEWAY), SERVER, 42, DnsState())
    monkeypatch.setattr(network, "detect_interface",
                        lambda: Interface("eth0", "192.0.2.2", GATEWAY))
    return conn


def test_linux_gateway_repair_uses_atomic_ip_replace(monkeypatch):
    calls = _commands(monkeypatch)
    network.replace_host_route(SERVER, GATEWAY)
    assert calls == [["ip", "route", "replace", SERVER, "via", GATEWAY]]


def test_failed_gateway_repair_preserves_saved_gateway(monkeypatch, tmp_path):
    conn = _connected(monkeypatch, tmp_path)
    monkeypatch.setattr(network, "detect_interface",
                        lambda: Interface("eth0", "192.0.2.2", "192.0.2.254"))
    messages = []
    conn._log = messages.append
    _commands(monkeypatch, routes=_healthy_routes(), fail=lambda a: "replace" in a or "add" in a)
    with pytest.raises(RuntimeError, match="denied"):
        conn.repair_route_if_needed()
    assert conn.state.gateway == GATEWAY
    assert not any("refreshed" in message for message in messages)


@pytest.mark.parametrize("failed_dest", SPLIT)
def test_failed_split_route_rolls_back_before_dns_and_state(monkeypatch, tmp_path, failed_dest):
    conn, calls = _stub_connect(monkeypatch, tmp_path)
    monkeypatch.setattr(network, "add_default_routes", posix.add_default_routes)
    _commands(monkeypatch, fail=lambda a: "add" in a and failed_dest in a)
    messages = []
    conn._log = messages.append
    with pytest.raises(connection.ConnectError, match="denied"):
        conn._connect_generic(SimpleNamespace(), _iface(), SERVER, DnsState())
    assert calls.count("remove_routes") == 2
    assert "xray_stop" in calls
    assert "set_dns_loopback" not in calls
    assert not conn.state.is_connected()
    assert not conn._owned
    assert "Connected." not in messages


def test_failed_server_route_stops_before_xray_starts(monkeypatch, tmp_path):
    conn, calls = _stub_connect(monkeypatch, tmp_path)
    monkeypatch.setattr(network, "add_host_route", posix.add_host_route)
    _commands(monkeypatch, fail=lambda a: "add" in a)
    with pytest.raises(connection.ConnectError, match="denied"):
        conn._connect_generic(SimpleNamespace(), _iface(), SERVER, DnsState())
    assert "xray_start" not in calls
    assert not conn.state.is_connected()


def test_missing_route_repaired_even_without_gateway_change(monkeypatch, tmp_path):
    conn = _connected(monkeypatch, tmp_path)
    calls = _commands(monkeypatch, routes=_healthy_routes()[:1])
    assert "restored" in conn.repair_route_if_needed()
    assert ["ip", "route", "add", SPLIT[1], "dev", "xray0"] in calls
    assert not any("replace" in call or "delete" in call for call in calls)


def test_healthy_routes_are_not_reinstalled(monkeypatch, tmp_path):
    conn = _connected(monkeypatch, tmp_path)
    calls = _commands(monkeypatch, routes=_healthy_routes())
    assert conn.repair_route_if_needed() is None
    assert calls  # health was actually checked
    assert not any("add" in call or "replace" in call for call in calls)


def test_repair_does_not_replace_a_competing_vpn_route(monkeypatch, tmp_path):
    conn = _connected(monkeypatch, tmp_path)
    routes = [{"dst": dest, "dev": "tun0"} for dest in SPLIT]
    calls = _commands(monkeypatch, routes=routes, fail=lambda a: "add" in a)
    with pytest.raises(RuntimeError, match="denied"):
        conn.repair_route_if_needed()
    assert not any("replace" in call or "del" in call for call in calls)


def test_failed_route_query_never_installs_routes_blindly(monkeypatch, tmp_path):
    conn = _connected(monkeypatch, tmp_path)
    calls = _commands(monkeypatch, fail=lambda a: "show" in a)
    with pytest.raises(RuntimeError, match="denied"):
        conn.repair_route_if_needed()
    assert not any("add" in call for call in calls)


def test_route_health_errors_reach_ui_and_allow_retry():
    from xrayui.ui.main_window import MainWindow

    messages = []
    window = SimpleNamespace(_repairing=False,
                             conn=SimpleNamespace(is_connected=lambda: True),
                             _on_step=messages.append)
    window._run_async = lambda work, done: done(error="RTNETLINK: denied")
    MainWindow._check_route_health(window)
    assert not window._repairing
    assert any("denied" in message for message in messages)
