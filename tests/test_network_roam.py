"""A move to another network adapter must rebuild the tunnel, not strand it.

Xray is pinned to the adapter it was started on. When the default route moves
to another one (hotspot to Wi-Fi, a new router), the old repair gave up in
silence and the VPN stayed dead until the user reconnected by hand.
"""
from __future__ import annotations

import types

import pytest

from xrayui.core import connection
from xrayui.core.network import Interface


def _conn(monkeypatch, current_alias, alias="en0"):
    conn = object.__new__(connection.Connection)
    conn.roamed_to = None
    conn._roam_candidate = None
    conn.logs = []
    conn._log = conn.logs.append
    conn.state = types.SimpleNamespace(
        is_connected=lambda: True, alias=alias, gateway="192.0.2.1",
        server_ip="203.0.113.10")
    conn.current = current_alias
    monkeypatch.setattr(connection.network, "detect_interface",
                        lambda: Interface(conn.current, "192.0.2.5", "192.0.2.1")
                        if conn.current else None)
    monkeypatch.setattr(connection.network, "repair_tun_routes", lambda: None)
    return conn


def test_a_new_physical_adapter_is_flagged_on_the_second_look(monkeypatch):
    conn = _conn(monkeypatch, "en1")
    assert conn.repair_route_if_needed() is None      # first look: maybe a flap
    assert conn.roamed_to is None
    assert "en1" in conn.repair_route_if_needed()     # still there: it moved
    assert conn.roamed_to == "en1"
    assert conn.repair_route_if_needed() is None      # said once, not every tick


def test_a_flap_back_to_the_original_adapter_is_not_a_roam(monkeypatch):
    conn = _conn(monkeypatch, "en1")
    conn.repair_route_if_needed()
    conn.current = "en0"
    conn.repair_route_if_needed()
    conn.current = "en1"
    conn.repair_route_if_needed()
    assert conn.roamed_to is None


@pytest.mark.parametrize("device", ["utun4", "tun0", "wg0", "Wintun Userspace Tunnel",
                                    "OpenVPN TAP-Windows6", "bridge100", "docker0"])
def test_another_vpn_taking_the_default_route_is_not_a_roam(monkeypatch, device):
    conn = _conn(monkeypatch, device)
    for _ in range(4):
        assert conn.repair_route_if_needed() is None
    assert conn.roamed_to is None


def test_offline_changes_nothing(monkeypatch):
    conn = _conn(monkeypatch, None)
    assert conn.repair_route_if_needed() is None
    assert conn.roamed_to is None


def test_disconnect_clears_a_pending_roam(monkeypatch):
    conn = _conn(monkeypatch, "en1")
    conn.repair_route_if_needed()
    conn.repair_route_if_needed()
    assert conn.roamed_to == "en1"
    conn.roamed_to = conn._roam_candidate = None  # what _restore does
    assert conn.repair_route_if_needed() is None


def test_restore_resets_the_roam_flag():
    import inspect
    src = inspect.getsource(connection.Connection._restore)
    assert "self.roamed_to = self._roam_candidate = None" in src
