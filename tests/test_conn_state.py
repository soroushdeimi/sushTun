"""The connection state remembers which profile the running tunnel came from."""
from __future__ import annotations

from xrayui import paths
from xrayui.core.network import DnsState, Interface
from xrayui.core.state import State

IFACE = Interface("eth0", "192.0.2.2", "192.0.2.1")


def _state(monkeypatch, tmp_path) -> State:
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    return State()


def test_the_connected_profile_is_recorded(monkeypatch, tmp_path):
    st = _state(monkeypatch, tmp_path)
    st.save(IFACE, "203.0.113.10", 7, DnsState(), profile_uid="abc123")
    assert st.profile_uid == "abc123"


def test_a_connect_without_a_profile_leaves_no_stale_one_behind(monkeypatch, tmp_path):
    st = _state(monkeypatch, tmp_path)
    st.save(IFACE, "203.0.113.10", 7, DnsState(), profile_uid="old")
    st.save(IFACE, "203.0.113.10", 7, DnsState())
    assert st.profile_uid is None


def test_disconnecting_forgets_it(monkeypatch, tmp_path):
    st = _state(monkeypatch, tmp_path)
    st.save(IFACE, "203.0.113.10", 7, DnsState(), profile_uid="abc123")
    st.clear()
    assert st.profile_uid is None
