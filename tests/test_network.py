"""Windows network helpers: interface detection skip list, WireGuard route helpers.

The route-syntax tests target network.py's Windows implementations directly
through the module-level names, which are swapped for the POSIX backend at
import time off Windows (see network.py's bottom) — so, like the existing
DNS tests in test_stale_restore.py, they only run on Windows.
"""
import sys

import pytest

from xrayui.core import _net_posix, network


def test_detect_ps_skips_both_tunnel_adapters():
    assert "xray0" in network._DETECT_PS
    assert "sushTun" in network._DETECT_PS
    assert network.WG_TUN_NAME == "sushTun"


def test_linux_detect_skips_both_tunnel_adapters(monkeypatch):
    def fake_run(args, **kwargs):
        if args[:3] == ["ip", "-j", "route"]:
            import json as _json
            return type("R", (), {"stdout": _json.dumps([
                {"dev": "xray0", "gateway": "10.0.0.1"},
                {"dev": "sushTun", "gateway": "10.0.0.1"},
                {"dev": "eth0", "gateway": "10.0.0.1"},
            ])})()
        return type("R", (), {"stdout": "[]"})()

    monkeypatch.setattr(_net_posix.proc, "run", fake_run)
    iface = _net_posix._linux_detect()
    assert iface is not None
    assert iface.alias == "eth0"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows route syntax")
def test_add_prefix_route_ipv4_converts_to_network_and_mask(monkeypatch):
    calls = []
    monkeypatch.setattr(network.proc, "run", lambda args, **k: calls.append(args))
    network.add_prefix_route("192.168.1.0/24", 7)
    assert calls == [["route", "add", "192.168.1.0", "mask", "255.255.255.0",
                       "0.0.0.0", "if", "7", "metric", "5"]]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows route syntax")
def test_remove_prefix_route_ipv4(monkeypatch):
    calls = []
    monkeypatch.setattr(network.proc, "run", lambda args, **k: calls.append(args))
    network.remove_prefix_route("192.168.1.0/24", 7)
    assert calls == [["route", "delete", "192.168.1.0", "mask", "255.255.255.0"]]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows route syntax")
def test_add_host_route(monkeypatch):
    calls = []
    monkeypatch.setattr(network.proc, "run", lambda args, **k: calls.append(args))
    network.add_host_route("203.0.113.10", "192.168.1.1")
    assert calls == [["route", "add", "203.0.113.10", "mask", "255.255.255.255",
                       "192.168.1.1", "metric", "1"]]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows route syntax")
def test_remove_host_route(monkeypatch):
    calls = []
    monkeypatch.setattr(network.proc, "run", lambda args, **k: calls.append(args))
    network.remove_host_route("203.0.113.10")
    assert calls == [["route", "delete", "203.0.113.10", "mask", "255.255.255.255"]]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows route syntax")
def test_add_prefix_route_ipv6_uses_netsh(monkeypatch):
    calls = []
    monkeypatch.setattr(network.proc, "run", lambda args, **k: calls.append(args))
    network.add_prefix_route("fd00::/64", 7)
    assert calls == [["netsh", "interface", "ipv6", "add", "route", "fd00::/64",
                       "interface=7", "store=active"]]
