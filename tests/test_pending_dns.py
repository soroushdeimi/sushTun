"""Pending recovery must preserve DNS without retaining a dead connection."""
import json
from types import SimpleNamespace

import pytest

from xrayui import paths
from xrayui.core import connection
from xrayui.core.network import DnsState, Interface
from xrayui.core.profiles import Profile
from xrayui.core.state import State

DNS = DnsState("STATIC", ["1.1.1.1"])
IFACE = Interface("Wi-Fi", "192.0.2.2", "192.0.2.1", 4)


@pytest.fixture
def recovery(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "runtime.json")
    calls = []
    monkeypatch.setattr(connection, "IS_MAC", True)
    monkeypatch.setattr(connection.xray_mod, "is_xray_running", lambda: False)
    monkeypatch.setattr(connection.network, "remove_routes", lambda *a: calls.append("routes"))
    monkeypatch.setattr(connection.network, "release_stranded_dns",
                        lambda exclude=None: calls.append(("release", exclude)) or [])
    monkeypatch.setattr(connection.network, "dns_target_exists", lambda *a: True, raising=False)
    monkeypatch.setattr(connection.network, "restore_dns", lambda *a, **k: False)
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: calls.append("uninstall"))
    monkeypatch.setattr(connection.network, "detect_interface", lambda: IFACE)
    monkeypatch.setattr(connection.network, "foreign_tunnel", lambda *a: None)
    monkeypatch.setattr(connection.network, "backup_dns", lambda *a: DnsState())
    monkeypatch.setattr(connection, "_resolve", lambda host: "203.0.113.1")
    conn = connection.Connection(on_step=calls.append)
    conn.xray = SimpleNamespace(stop=lambda: calls.append("xray"))
    conn.tun2socks = SimpleNamespace(stop=lambda: calls.append("bridge"))
    monkeypatch.setattr(conn, "_connect_generic", lambda *a: calls.append(("connect", a[-1])))
    monkeypatch.setattr(conn, "_connect_macos", lambda *a: calls.append(("connect", a[-1])))
    return conn, calls


def test_lockout_probe_and_backup_survival(recovery):
    conn, calls = recovery
    conn.state.save(IFACE, "203.0.113.1", 42, DNS)
    conn._owned = True
    paths.runtime_config().touch()
    assert conn._restore() is False
    assert not conn.state.is_connected()
    assert not conn._owned
    assert not paths.runtime_config().exists()
    assert {"bridge", "xray", "routes"} <= set(c for c in calls if isinstance(c, str))
    assert ("release", None) in calls
    assert "uninstall" not in calls
    assert "Network restored." not in calls
    assert conn.state.pending()[IFACE.alias].dns == DNS
    conn.connect(Profile(id="u", address="vpn.example"))
    assert ("connect", DNS) in calls


def test_two_aliases_survive_clear_and_reload(recovery):
    conn, _ = recovery
    conn.state.save_pending("Wi-Fi", DNS)
    other = DnsState("MACOS", ["شبکه خانه", "9.9.9.9"])
    conn.state.save_pending("en5", other)
    conn.state.clear()
    assert State().pending()["Wi-Fi"].dns == DNS
    assert State().pending()["en5"].dns == other
    assert set(json.loads((conn.state.dir / "dns-pending.json").read_text())) == {"Wi-Fi", "en5"}


@pytest.mark.parametrize("success", [True, False])
def test_hostname_connect_drains_before_resolve_and_reuses_backup(recovery, monkeypatch, success):
    conn, calls = recovery
    conn.state.save_pending(IFACE.alias, DNS)
    def restore(*a, **k):
        calls.append("drained")
        return success
    def resolve(host):
        assert "drained" in calls
        return "203.0.113.1"
    monkeypatch.setattr(connection.network, "restore_dns", restore)
    monkeypatch.setattr(connection, "_resolve", resolve)
    conn.connect(Profile(id="u", address="vpn.example"))
    assert ("connect", DnsState() if success else DNS) in calls
    assert bool(conn.state.pending()) is not success  # no state.save in fake connect


def test_boot_recovery_retries_every_alias(recovery, monkeypatch):
    conn, calls = recovery
    for alias in ("Wi-Fi", "Ethernet"):
        conn.state.save_pending(alias, DNS)
    applied = []
    monkeypatch.setattr(connection.network, "restore_dns",
                        lambda alias, dns, retries: applied.append((alias, retries)) or True)
    assert conn.recover_if_stale(dns_retries=8) is True
    assert applied == [("Wi-Fi", 8), ("Ethernet", 8)]
    assert not conn.state.pending()
    assert calls.count("uninstall") == 1


def test_gone_adapter_is_dropped_after_restore_retries(recovery, monkeypatch):
    conn, calls = recovery
    conn.state.save_pending(IFACE.alias, DNS)
    monkeypatch.setattr(connection.network, "dns_target_exists", lambda *a: False)
    assert conn.recover_if_stale() is False
    assert not conn.state.pending()
    assert "uninstall" in calls


def test_pending_expires_after_twenty_failed_recovery_calls(recovery):
    conn, calls = recovery
    conn.state.save_pending(IFACE.alias, DNS)
    for _ in range(19):
        assert conn.recover_if_stale(dns_retries=8) is False
    assert conn.state.pending()[IFACE.alias].attempts == 19
    assert "uninstall" not in calls
    assert conn.recover_if_stale() is False
    assert not conn.state.pending()
    assert "uninstall" in calls


def test_live_xray_leaves_pending_untouched(recovery, monkeypatch):
    conn, calls = recovery
    conn.state.save_pending(IFACE.alias, DNS)
    monkeypatch.setattr(connection.xray_mod, "is_xray_running", lambda: True)
    assert conn.recover_if_stale() is False
    assert conn.state.pending()[IFACE.alias].attempts == 0
    assert not calls


@pytest.mark.parametrize("operation", ["restore", "release", "routes"])
def test_teardown_errors_do_not_keep_connected_state(recovery, monkeypatch, operation):
    conn, calls = recovery
    conn.state.save(IFACE, "203.0.113.1", 42, DNS)
    conn._owned = True
    paths.runtime_config().touch()
    def fail(*a, **k):
        raise OSError("unavailable")
    name = {"restore": "restore_dns", "release": "release_stranded_dns",
            "routes": "remove_routes"}[operation]
    monkeypatch.setattr(connection.network, name, fail)
    assert conn._restore() is False
    assert not conn.state.is_connected()
    assert not conn._owned
    assert not paths.runtime_config().exists()
    assert conn.state.pending()[IFACE.alias].dns == DNS


def test_one_pending_error_does_not_prevent_other_alias_recovery(recovery, monkeypatch):
    conn, calls = recovery
    conn.state.save_pending("Wi-Fi", DNS)
    conn.state.save_pending("Ethernet", DNS)
    def restore(alias, dns, retries):
        if alias == "Wi-Fi":
            raise OSError("network command unavailable")
        return True
    monkeypatch.setattr(connection.network, "restore_dns", restore)
    assert conn.recover_if_stale() is False
    assert set(conn.state.pending()) == {"Wi-Fi"}
    assert ("release", None) in calls
    assert "uninstall" not in calls
