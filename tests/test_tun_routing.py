"""Tunnel capture: the TUN adapter must be addressed and must win the route.

Regression cover for the failure where xray0 came up on APIPA (169.254.x.x).
Windows then preferred the physical adapter's global source address for global
destinations, so nothing but interface-bound probe traffic ever entered the
tunnel and every app that was not explicitly proxy-configured timed out.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import connection, network
from xrayui.core.network import DnsState, Interface

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows route/netsh backend")


def _record_proc(monkeypatch, ps_out: list[str] | None = None):
    """Capture argv of every proc.run, stubbing PowerShell output."""
    ran: list[list[str]] = []

    def fake_run(args, **_kw):
        ran.append(list(args))
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(network.proc, "run", fake_run)
    monkeypatch.setattr(network.proc, "ps_lines", lambda *a, **k: list(ps_out or []))
    return ran


def _route_adds(ran):
    return [a for a in ran if a[:2] == ["route", "add"]]


# -- routes ----------------------------------------------------------------
@WINDOWS_ONLY
def test_default_routes_are_split_halves_not_a_bare_default(monkeypatch):
    ran = _record_proc(monkeypatch)
    network.add_default_routes(42)

    dests = [(a[2], a[4]) for a in _route_adds(ran)]
    assert dests == [("0.0.0.0", "128.0.0.0"), ("128.0.0.0", "128.0.0.0")]
    # A /0 ties with the physical default and loses on interface metric.
    assert not any(a[4] == "0.0.0.0" for a in _route_adds(ran))
    for a in _route_adds(ran):
        assert a[-3:] == ["42", "metric", "1"]


@WINDOWS_ONLY
def test_host_route_is_pinned_to_the_physical_gateway(monkeypatch):
    ran = _record_proc(monkeypatch)
    network.add_host_route("185.229.204.23", "172.21.1.1")
    assert _route_adds(ran) == [[
        "route", "add", "185.229.204.23", "mask", "255.255.255.255",
        "172.21.1.1", "metric", "1",
    ]]


@WINDOWS_ONLY
def test_remove_routes_clears_both_halves_the_legacy_default_and_the_host(monkeypatch):
    ran = _record_proc(monkeypatch)
    network.remove_routes("185.229.204.23")

    deleted = [(a[2], a[4]) for a in ran if a[:2] == ["route", "delete"]]
    assert ("0.0.0.0", "0.0.0.0") in deleted          # left by older releases
    assert ("0.0.0.0", "128.0.0.0") in deleted
    assert ("128.0.0.0", "128.0.0.0") in deleted
    assert ("185.229.204.23", "255.255.255.255") in deleted


@WINDOWS_ONLY
def test_remove_routes_without_a_server_leaves_no_host_delete(monkeypatch):
    ran = _record_proc(monkeypatch)
    network.remove_routes()
    assert all(a[4] != "255.255.255.255" for a in ran if a[:2] == ["route", "delete"])


# -- adapter addressing ----------------------------------------------------
@WINDOWS_ONLY
def test_configure_tun_assigns_address_and_metric(monkeypatch):
    ran = _record_proc(monkeypatch, ps_out=[network.TUN_ADDRESS])
    assert network.configure_tun(42) is True

    assert ["netsh", "interface", "ipv4", "set", "address", "name=42", "static",
            network.TUN_ADDRESS, network.TUN_NETMASK] in ran
    assert ["netsh", "interface", "ipv4", "set", "interface", "interface=42",
            f"metric={network.TUN_METRIC}"] in ran


@WINDOWS_ONLY
def test_configure_tun_reports_failure_when_adapter_stays_on_apipa(monkeypatch):
    _record_proc(monkeypatch, ps_out=["169.254.57.70"])
    assert network.configure_tun(42) is False


@WINDOWS_ONLY
def test_configure_tun_retries_by_adapter_name_when_the_index_is_refused(monkeypatch):
    ran: list[list[str]] = []
    seen = {"n": 0}

    def fake_run(args, **_kw):
        ran.append(list(args))
        return types.SimpleNamespace(returncode=0, stdout="")

    def fake_ps_lines(*_a, **_k):
        # Nothing took on the first pass; the name-based pass lands.
        seen["n"] += 1
        return ["169.254.57.70"] if seen["n"] == 1 else [network.TUN_ADDRESS]

    monkeypatch.setattr(network.proc, "run", fake_run)
    monkeypatch.setattr(network.proc, "ps_lines", fake_ps_lines)

    assert network.configure_tun(42) is True
    assert any(f"name={network.TUN_NAME}" in a for a in ran)


@WINDOWS_ONLY
def test_tun_ipv4_ignores_apipa_and_returns_the_routable_address(monkeypatch):
    _record_proc(monkeypatch, ps_out=["169.254.57.70", "172.19.0.2"])
    assert network.tun_ipv4(42) == "172.19.0.2"

    _record_proc(monkeypatch, ps_out=["169.254.57.70"])
    assert network.tun_ipv4(42) == ""


# -- connect ordering ------------------------------------------------------
def _stub_connect(monkeypatch, tmp_path, *, tun=42, tun_addressed=True):
    """Drive _connect_generic with every side effect recorded, none performed."""
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "config.runtime.json")
    calls: list[str] = []

    monkeypatch.setattr(connection.render, "build", lambda *a, **k: tmp_path / "cfg.json")
    monkeypatch.setattr(connection.bootrestore, "install", lambda: None)
    monkeypatch.setattr(connection.network, "remove_routes",
                        lambda ip=None: calls.append("remove_routes"))
    monkeypatch.setattr(connection.network, "add_host_route",
                        lambda ip, gw: calls.append("add_host_route"))
    monkeypatch.setattr(connection.network, "add_default_routes",
                        lambda idx: calls.append("add_default_routes"))
    monkeypatch.setattr(connection.network, "wait_for_tun",
                        lambda *a, **k: calls.append("wait_for_tun") or tun)
    monkeypatch.setattr(connection.network, "configure_tun",
                        lambda idx: calls.append("configure_tun") or tun_addressed)
    monkeypatch.setattr(connection.network, "set_dns_loopback",
                        lambda alias: calls.append("set_dns_loopback"))

    conn = connection.Connection()
    conn.xray.start = lambda cfg: calls.append("xray_start")
    conn.xray.stop = lambda: calls.append("xray_stop")
    monkeypatch.setattr(conn, "_setup_gateway", lambda: None)
    return conn, calls


def _iface():
    return Interface("Ethernet 3", "172.21.1.24", "172.21.1.1", 28)


def test_server_route_is_pinned_before_xray_dials(monkeypatch, tmp_path):
    conn, calls = _stub_connect(monkeypatch, tmp_path)
    conn._connect_generic(types.SimpleNamespace(), _iface(), "185.229.204.23",
                          DnsState(mode="DHCP", servers=[]))

    assert calls.index("add_host_route") < calls.index("xray_start")
    # And the tunnel is addressed before anything is routed into it.
    assert calls.index("configure_tun") < calls.index("add_default_routes")
    assert conn.state.is_connected()


def test_connect_fails_and_cleans_up_when_the_tun_has_no_address(monkeypatch, tmp_path):
    conn, calls = _stub_connect(monkeypatch, tmp_path, tun_addressed=False)

    with pytest.raises(connection.ConnectError, match="carry no traffic"):
        conn._connect_generic(types.SimpleNamespace(), _iface(), "185.229.204.23",
                              DnsState(mode="DHCP", servers=[]))

    assert "xray_stop" in calls
    assert calls.count("remove_routes") == 2  # pre-connect, then the rollback
    assert "add_default_routes" not in calls
    assert "set_dns_loopback" not in calls    # DNS never hijacked on a failed connect
    assert not conn.state.is_connected()


def test_connect_fails_and_cleans_up_when_the_tun_never_appears(monkeypatch, tmp_path):
    conn, calls = _stub_connect(monkeypatch, tmp_path, tun=None)

    with pytest.raises(connection.ConnectError, match="did not appear"):
        conn._connect_generic(types.SimpleNamespace(), _iface(), "185.229.204.23",
                              DnsState(mode="DHCP", servers=[]))

    assert "configure_tun" not in calls
    assert calls.count("remove_routes") == 2


# -- template --------------------------------------------------------------
def _template():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_tun_mtu_leaves_headroom_for_encapsulation():
    tun = next(i for i in _template()["inbounds"] if i["tag"] == "tun-in")
    assert tun["settings"]["mtu"] <= 1420


def test_dns_arriving_over_the_tun_is_hijacked_not_forwarded_raw():
    rules = _template()["routing"]["rules"]
    hijack = next(r for r in rules if r.get("inboundTag") == ["tun-in"])
    assert hijack["port"] == 53
    assert hijack["outboundTag"] == "dns-out"
