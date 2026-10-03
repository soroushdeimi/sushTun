"""Every launch failure must unpin the server and delete the runtime config."""
from types import SimpleNamespace

import pytest

from xrayui import paths
from xrayui.core import connection
from xrayui.core.network import DnsState


@pytest.mark.parametrize("entry", ["generic", "native", "bridge", "retry"])
def test_launch_oserror_cleans_up_each_call_site(monkeypatch, tmp_path, entry):
    from test_tun_routing import _iface, _stub_connect

    conn, calls = _stub_connect(monkeypatch, tmp_path)
    monkeypatch.setattr(conn.tun2socks, "stop", lambda: calls.append("bridge_stop"))
    monkeypatch.setattr(connection.t2s, "kill_stale", lambda: None)
    monkeypatch.setattr(connection.network, "mac_other_vpn", lambda *a: None, raising=False)
    monkeypatch.setattr(connection.network, "mac_ensure_scoped_default",
                        lambda *a: False, raising=False)
    runtime = paths.runtime_config()
    runtime.write_text("secret")
    removed = []
    monkeypatch.setattr(connection.network, "remove_routes", lambda ip: removed.append(ip))

    def start(cfg):
        raise OSError(13, "Permission denied")

    conn.xray.start = start
    server = "203.0.113.10"
    with pytest.raises(connection.ConnectError, match="Could not start Xray"):
        if entry == "generic":
            conn._connect_generic(SimpleNamespace(uid="p1"), _iface(), server, DnsState())
        elif entry == "native":
            conn._connect_macos(SimpleNamespace(uid="p1"), _iface(), server, DnsState())
        elif entry == "bridge":
            conn._start_macos_bridge(lambda *a: runtime, [], [], {}, server)
        else:
            monkeypatch.setattr(conn, "_exits", lambda *a: [object()])
            attempts = []

            def retry_start(cfg):
                attempts.append(cfg)
                if len(attempts) == 2:
                    raise OSError(13, "Permission denied")

            conn.xray.start = retry_start
            conn.xray.is_running = lambda: False
            monkeypatch.setattr(connection, "_last_log_line", lambda: "address already in use")
            conn._connect_generic(SimpleNamespace(uid="p1"), _iface(), server, DnsState())
    assert removed[-1] == server
    assert len(removed) == (1 if entry == "bridge" else 2)
    assert "xray_stop" in calls and "bridge_stop" in calls
    assert "wait_for_tun" not in calls and "add_default_routes" not in calls
    assert not runtime.exists()
    assert not conn.state.is_connected()
