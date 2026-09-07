from xrayui import paths
from xrayui.core.state import WgState


def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)


def test_wg_state_round_trip(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    state = WgState()
    state.save("sushTun", "uid-123", 7, "203.0.113.10", ["192.168.1.0/24", "10.0.0.0/8"])

    assert state.is_connected()
    assert state.device == "sushTun"
    assert state.profile_uid == "uid-123"
    assert state.tun_index == 7
    assert state.endpoint_ip == "203.0.113.10"
    assert state.routes() == ["192.168.1.0/24", "10.0.0.0/8"]


def test_wg_state_clear_removes_only_its_own_files(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    state = WgState()
    state.save("sushTun", "uid-123", 7, "203.0.113.10", ["192.168.1.0/24"])
    state.clear()

    assert not state.is_connected()
    assert state.device is None
    assert state.routes() == []


def test_wg_state_handles_missing_tun_index(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    state = WgState()
    state.save("sushTun", "uid-123", None, None, [])
    assert state.tun_index is None
    assert state.endpoint_ip is None
    assert state.routes() == []


def test_wg_state_is_independent_of_proxy_state_files(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    from xrayui.core.network import DnsState, Interface
    from xrayui.core.state import State

    proxy = State()
    proxy.save(Interface("Wi-Fi", "192.168.1.50", "192.168.1.1", 12),
               "203.0.113.10", 23, DnsState(mode="DHCP", servers=[]))
    wg = WgState()
    wg.save("sushTun", "uid-123", 7, "198.51.100.5", ["192.168.1.0/24"])

    proxy.clear()

    assert not proxy.is_connected()
    assert wg.is_connected()
    assert wg.routes() == ["192.168.1.0/24"]
