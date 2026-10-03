"""Windows route failures must abort connecting instead of leaving traffic behind."""
from types import SimpleNamespace

import pytest

from xrayui.core import connection
from xrayui.core.network import DnsState


@pytest.mark.parametrize("failed_destination", ["203.0.113.10", "0.0.0.0", "128.0.0.0"])
def test_refused_route_fails_connect_before_dns(win_net, monkeypatch, tmp_path, failed_destination):
    from test_tun_routing import _iface, _stub_connect

    conn, calls = _stub_connect(monkeypatch, tmp_path)
    monkeypatch.setattr(conn.tun2socks, "stop", lambda: None)
    monkeypatch.setattr(connection.network, "add_host_route", win_net.add_host_route)
    monkeypatch.setattr(connection.network, "add_default_routes", win_net.add_default_routes)
    added = []

    def run(args, **kwargs):
        added.append(args[2])
        return SimpleNamespace(returncode=int(args[2] == failed_destination),
                               stdout="Zugriff verweigert", stderr="")

    monkeypatch.setattr(win_net.proc, "run", run)
    with pytest.raises(connection.ConnectError, match="route"):
        conn._connect_generic(SimpleNamespace(uid="p1"), _iface(), "203.0.113.10", DnsState())
    assert failed_destination in added
    assert "xray_stop" in calls
    assert calls.count("remove_routes") == 2
    assert "set_dns_loopback" not in calls
    assert not conn.state.is_connected()
