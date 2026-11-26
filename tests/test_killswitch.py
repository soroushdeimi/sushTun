"""Kill switch: blackhole routes that take over when the tunnel dies.

The tunnel routes are less preferred than the physical default, so the moment
they vanish (Xray dies, the app crashes) traffic would fall back to the real
IP. The kill switch installs blackholes that are *less* preferred than the
tunnel routes, so they only win once the tunnel routes are gone.

Every command is faked; nothing here touches a real route table.
"""
from __future__ import annotations

import copy
import json
import types

import pytest

from xrayui.core import _net_posix as posix
from xrayui.core import connection
from xrayui.core import settings as app_settings
from xrayui.core.network import DnsState, Interface

TUN = posix.TUN_NAME  # "xray0"


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# -- settings ---------------------------------------------------------------

def test_default_is_off_and_untouched_install_is_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    got = app_settings.load()
    assert got["killswitch"] == {"enabled": False}
    # An untouched install must render exactly what it always has: the default
    # is off, so no kill switch routes are ever installed.
    assert app_settings.DEFAULTS["killswitch"] == {"enabled": False}


def test_killswitch_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    data = copy.deepcopy(app_settings.DEFAULTS)
    data["killswitch"]["enabled"] = True
    app_settings.save(data)
    assert app_settings.load()["killswitch"] == {"enabled": True}


def test_a_corrupt_killswitch_value_keeps_the_default(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps({"killswitch": "yes"}), encoding="utf-8")
    # A wrong-shaped container keeps the default rather than crashing connect.
    assert app_settings.load()["killswitch"] == {"enabled": False}


# -- Linux argv -------------------------------------------------------------

def _linux(monkeypatch, outputs=None):
    """Route the Linux backend's commands to canned (returncode, stdout)."""
    monkeypatch.setattr(posix, "IS_MAC", False)
    calls: list[list[str]] = []

    def fake_run(args, **_k):
        calls.append(list(args))
        rc, out = (outputs or {}).get(tuple(args), (0, ""))
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")

    monkeypatch.setattr(posix.proc, "run", fake_run)
    return calls


def test_linux_add_is_the_tunnel_prefix_with_a_worse_metric(monkeypatch):
    calls = _linux(monkeypatch)
    posix.add_killswitch_routes()
    adds = [c for c in calls if c[:3] == ["ip", "route", "add"]]
    assert adds == [
        ["ip", "route", "add", "0.0.0.0/1", "blackhole", "metric", "1000"],
        ["ip", "route", "add", "128.0.0.0/1", "blackhole", "metric", "1000"],
    ]
    # Idempotent: a stale blackhole a crashed session left is cleared first.
    dels = [c for c in calls if c[:3] == ["ip", "route", "del"]]
    assert dels == [
        ["ip", "route", "del", "0.0.0.0/1", "blackhole"],
        ["ip", "route", "del", "128.0.0.0/1", "blackhole"],
    ]
    # The delete comes before the add, so a fresh connect never hits "exists".
    assert calls.index(dels[0]) < calls.index(adds[0])


def test_linux_remove_deletes_the_blackholes(monkeypatch):
    calls = _linux(monkeypatch)
    posix.remove_killswitch_routes()
    # The deletes run in a thread pool, so compare as a multiset, not by order.
    assert sorted(map(tuple, calls)) == sorted(map(tuple, [
        ["ip", "route", "del", "0.0.0.0/1", "blackhole"],
        ["ip", "route", "del", "128.0.0.0/1", "blackhole"],
        ["ip", "-6", "route", "del", "::/1", "blackhole"],
        ["ip", "-6", "route", "del", "8000::/1", "blackhole"],
    ]))


def test_linux_remove_routes_also_deletes_the_blackholes(monkeypatch):
    calls = _linux(monkeypatch)
    posix.remove_routes("203.0.113.10")
    dels = {tuple(c) for c in calls if c[:3] == ["ip", "route", "del"]}
    assert ("ip", "route", "del", "0.0.0.0/1", "blackhole") in dels
    assert ("ip", "route", "del", "128.0.0.0/1", "blackhole") in dels
    # The v6 blackholes are deleted too, so no v6 leak is left behind.
    dels6 = {tuple(c) for c in calls if c[:4] == ["ip", "-6", "route", "del"]}
    assert ("ip", "-6", "route", "del", "::/1", "blackhole") in dels6
    assert ("ip", "-6", "route", "del", "8000::/1", "blackhole") in dels6
    # The tunnel routes and the pinned host route are still cleaned up.
    assert ("ip", "route", "del", "0.0.0.0/1", "dev", TUN) in dels
    assert ("ip", "route", "del", "128.0.0.0/1", "dev", TUN) in dels
    assert ("ip", "route", "del", "203.0.113.10") in dels


def test_linux_add_failure_raises(monkeypatch):
    _linux(monkeypatch, {
        ("ip", "route", "add", "0.0.0.0/1", "blackhole", "metric", "1000"):
            (1, "RTNETLINK answers: File exists")})
    with pytest.raises(RuntimeError, match="0.0.0.0/1"):
        posix.add_killswitch_routes()


def test_linux_ipv6_blocked_reads_the_route_table(monkeypatch):
    # Both halves blackholed -> covered.
    _linux(monkeypatch, {
        ("ip", "-6", "-o", "route", "show"):
            (0, "blackhole ::/1 metric 1000\nblackhole 8000::/1 metric 1000\n")})
    assert posix.ipv6_blocked() is True
    # Only one half -> not covered (a partial install is a leak).
    _linux(monkeypatch, {
        ("ip", "-6", "-o", "route", "show"): (0, "blackhole ::/1 metric 1000\n")})
    assert posix.ipv6_blocked() is False
    # No v6 blackholes at all -> not covered.
    _linux(monkeypatch, {
        ("ip", "-6", "-o", "route", "show"): (0, "default dev eth0\n")})
    assert posix.ipv6_blocked() is False


def test_linux_v6_failure_is_quiet_and_keeps_v4(monkeypatch, caplog):
    # IPv6 is disabled/unsupported: the v6 adds are refused. That must not
    # raise, must not spam, and must not take the v4 protection down.
    calls = _linux(monkeypatch, {
        ("ip", "-6", "route", "add", "::/1", "blackhole", "metric", "1000"):
            (1, "RTNETLINK answers: Network is unreachable")})
    with caplog.at_level("DEBUG", logger="xrayui.core._net_posix"):
        posix.add_killswitch_routes()  # must not raise
    # The v4 blackholes were still installed.
    v4_adds = [c for c in calls if c[:3] == ["ip", "route", "add"]]
    assert v4_adds == [
        ["ip", "route", "add", "0.0.0.0/1", "blackhole", "metric", "1000"],
        ["ip", "route", "add", "128.0.0.0/1", "blackhole", "metric", "1000"],
    ]
    # The v6 failure is logged at debug, not warning/error.
    assert any("IPv6" in r.message for r in caplog.records)
    assert all(r.levelno < 30 for r in caplog.records)


# -- macOS argv -------------------------------------------------------------

def _mac(monkeypatch, outputs=None):
    monkeypatch.setattr(posix, "IS_MAC", True)
    calls: list[list[str]] = []

    def fake_run(args, **_k):
        calls.append(list(args))
        rc, out = (outputs or {}).get(tuple(args), (0, ""))
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")

    monkeypatch.setattr(posix.proc, "run", fake_run)
    return calls


def test_mac_add_is_a_blackhole_less_specific_than_the_tunnel(monkeypatch):
    calls = _mac(monkeypatch)
    posix.add_killswitch_routes()
    adds = [c for c in calls if c[:3] == ["route", "-n", "add"]]
    v4 = [c for c in adds if "-inet6" not in c]
    assert v4 == [
        ["route", "-n", "add", "-net", "0.0.0.0/1", "127.0.0.1", "-blackhole"],
        ["route", "-n", "add", "-net", "128.0.0.0/1", "127.0.0.1", "-blackhole"],
    ]
    # A /1 is less specific than the tunnel's /2s, so it only wins once the
    # /2s are gone. macOS wants a gateway even for a blackhole route.
    assert all("-blackhole" in c for c in adds)
    assert all(len(c) == 7 for c in v4)
    # Idempotent: a stale blackhole is cleared before the add.
    dels = [c for c in calls if c[:4] == ["route", "-n", "delete", "-net"]]
    v4_dels = [c for c in dels if "-inet6" not in c]
    assert v4_dels == [
        ["route", "-n", "delete", "-net", "0.0.0.0/1"],
        ["route", "-n", "delete", "-net", "128.0.0.0/1"],
    ]
    assert calls.index(v4_dels[0]) < calls.index(v4[0])


def test_mac_add_also_blackholes_ipv6(monkeypatch):
    # The tunnel is IPv4-only, so v6 must be blackholed unconditionally:
    # one /1 per half of the IPv6 space, -inet6, no gateway.
    calls = _mac(monkeypatch)
    posix.add_killswitch_routes()
    v6_adds = [c for c in calls if c[:3] == ["route", "-n", "add"] and "-inet6" in c]
    assert v6_adds == [
        ["route", "-n", "add", "-inet6", "-net", "::/1", "::1", "-blackhole"],
        ["route", "-n", "add", "-inet6", "-net", "8000::/1", "::1", "-blackhole"],
    ]
    # Idempotent: a stale v6 blackhole is cleared before the add.
    v6_dels = [c for c in calls if c[:4] == ["route", "-n", "delete", "-inet6"]]
    assert v6_dels == [
        ["route", "-n", "delete", "-inet6", "-net", "::/1"],
        ["route", "-n", "delete", "-inet6", "-net", "8000::/1"],
    ]
    assert calls.index(v6_dels[0]) < calls.index(v6_adds[0])


def test_mac_remove_deletes_the_blackholes(monkeypatch):
    calls = _mac(monkeypatch)
    posix.remove_killswitch_routes()
    # The deletes run in a thread pool, so compare as a multiset, not by order.
    assert sorted(map(tuple, calls)) == sorted(map(tuple, [
        ["route", "-n", "delete", "-net", "0.0.0.0/1"],
        ["route", "-n", "delete", "-net", "128.0.0.0/1"],
        ["route", "-n", "delete", "-inet6", "-net", "::/1"],
        ["route", "-n", "delete", "-inet6", "-net", "8000::/1"],
    ]))


def test_mac_remove_routes_also_deletes_the_blackholes(monkeypatch):
    calls = _mac(monkeypatch)
    posix.remove_routes("203.0.113.10")
    dels = {tuple(c) for c in calls if c[:4] == ["route", "-n", "delete", "-net"]}
    assert ("route", "-n", "delete", "-net", "0.0.0.0/1") in dels
    assert ("route", "-n", "delete", "-net", "128.0.0.0/1") in dels
    # The v6 blackholes are deleted too, so no v6 leak is left behind.
    dels6 = {tuple(c) for c in calls if c[:4] == ["route", "-n", "delete", "-inet6"]}
    assert ("route", "-n", "delete", "-inet6", "-net", "::/1") in dels6
    assert ("route", "-n", "delete", "-inet6", "-net", "8000::/1") in dels6
    # The tunnel /2s and the pinned host route are still cleaned up.
    assert ("route", "-n", "delete", "-host", "203.0.113.10") in {tuple(c) for c in calls}


def test_mac_add_failure_raises(monkeypatch):
    _mac(monkeypatch, {
        ("route", "-n", "add", "-net", "0.0.0.0/1", "127.0.0.1", "-blackhole"): (1, "File exists")})
    with pytest.raises(RuntimeError, match="0.0.0.0/1"):
        posix.add_killswitch_routes()


def test_mac_ipv6_blocked_reads_the_route_table(monkeypatch):
    # `route -n get <addr>` reports the route that would carry <addr>; a
    # blackhole match shows the BLACKHOLE flag. One probe per half.
    _mac(monkeypatch, {
        ("route", "-n", "get", "1::"): (0, "interface: utun5\n  ... BLACKHOLE\n"),
        ("route", "-n", "get", "8001::"): (0, "interface: utun5\n  ... BLACKHOLE\n")})
    assert posix.ipv6_blocked() is True
    # One half not blackholed -> not covered.
    _mac(monkeypatch, {
        ("route", "-n", "get", "1::"): (0, "interface: utun5\n  ... BLACKHOLE\n"),
        ("route", "-n", "get", "8001::"): (0, "interface: en0\n  ... UGSC\n")})
    assert posix.ipv6_blocked() is False


def test_mac_v6_failure_is_quiet_and_keeps_v4(monkeypatch, caplog):
    # IPv6 is disabled/unsupported: the v6 adds are refused. That must not
    # raise, must not spam, and must not take the v4 protection down.
    calls = _mac(monkeypatch, {
        ("route", "-n", "add", "-inet6", "-net", "::/1", "::1", "-blackhole"):
            (1, "route: socket: Operation not permitted")})
    with caplog.at_level("DEBUG", logger="xrayui.core._net_posix"):
        posix.add_killswitch_routes()  # must not raise
    # The v4 blackholes were still installed.
    v4_adds = [c for c in calls
               if c[:3] == ["route", "-n", "add"] and "-inet6" not in c]
    assert v4_adds == [
        ["route", "-n", "add", "-net", "0.0.0.0/1", "127.0.0.1", "-blackhole"],
        ["route", "-n", "add", "-net", "128.0.0.0/1", "127.0.0.1", "-blackhole"],
    ]
    # The v6 failure is logged at debug, not warning/error.
    assert any("IPv6" in r.message for r in caplog.records)
    assert all(r.levelno < 30 for r in caplog.records)


# -- Windows argv -----------------------------------------------------------

def _win_calls(monkeypatch, win_net):
    """Capture argv of every proc.run on the Windows backend module."""
    calls: list[list[str]] = []

    def fake_run(args, **_k):
        calls.append(list(args))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(win_net.proc, "run", fake_run)
    return calls


def test_windows_add_is_a_blackhole_with_a_worse_metric(monkeypatch, win_net):
    calls = _win_calls(monkeypatch, win_net)
    win_net.add_killswitch_routes()
    adds = [c for c in calls if c[:2] == ["route", "add"]]
    assert adds == [
        ["route", "add", "0.0.0.0", "mask", "128.0.0.0", "127.0.0.1", "metric", "1000"],
        ["route", "add", "128.0.0.0", "mask", "128.0.0.0", "127.0.0.1", "metric", "1000"],
    ]
    # Idempotent: a stale blackhole is cleared before the add.
    dels = [c for c in calls if c[:2] == ["route", "delete"]]
    assert dels == [
        ["route", "delete", "0.0.0.0", "mask", "128.0.0.0", "127.0.0.1"],
        ["route", "delete", "128.0.0.0", "mask", "128.0.0.0", "127.0.0.1"],
    ]
    assert calls.index(dels[0]) < calls.index(adds[0])


def test_windows_remove_deletes_the_blackholes(monkeypatch, win_net):
    calls = _win_calls(monkeypatch, win_net)
    win_net.remove_killswitch_routes()
    # The deletes run in a thread pool, so compare as a multiset, not by order.
    assert sorted(map(tuple, calls)) == sorted(map(tuple, [
        ["route", "delete", "0.0.0.0", "mask", "128.0.0.0", "127.0.0.1"],
        ["route", "delete", "128.0.0.0", "mask", "128.0.0.0", "127.0.0.1"],
        ["route", "-6", "delete", "::/1", "::1"],
        ["route", "-6", "delete", "8000::/1", "::1"],
    ]))


def test_windows_add_also_blackholes_ipv6(monkeypatch, win_net):
    # The tunnel is IPv4-only, so v6 must be blackholed unconditionally:
    # one /1 per half of the IPv6 space, to the loopback next hop.
    calls = _win_calls(monkeypatch, win_net)
    win_net.add_killswitch_routes()
    v6_adds = [c for c in calls if c[:2] == ["route", "-6"] and c[2] == "add"]
    assert v6_adds == [
        ["route", "-6", "add", "::/1", "::1", "metric", "1000"],
        ["route", "-6", "add", "8000::/1", "::1", "metric", "1000"],
    ]
    # Idempotent: a stale v6 blackhole is cleared before the add.
    v6_dels = [c for c in calls if c[:2] == ["route", "-6"] and c[2] == "delete"]
    assert v6_dels == [
        ["route", "-6", "delete", "::/1", "::1"],
        ["route", "-6", "delete", "8000::/1", "::1"],
    ]
    assert calls.index(v6_dels[0]) < calls.index(v6_adds[0])


def test_windows_remove_routes_also_deletes_the_blackholes(monkeypatch, win_net):
    calls = _win_calls(monkeypatch, win_net)
    win_net.remove_routes("203.0.113.10")
    dels = {tuple(c) for c in calls if c[:2] == ["route", "delete"]}
    assert ("route", "delete", "0.0.0.0", "mask", "128.0.0.0", "127.0.0.1") in dels
    assert ("route", "delete", "128.0.0.0", "mask", "128.0.0.0", "127.0.0.1") in dels
    # The v6 blackholes are deleted too, so no v6 leak is left behind.
    dels6 = {tuple(c) for c in calls if c[:2] == ["route", "-6"]}
    assert ("route", "-6", "delete", "::/1", "::1") in dels6
    assert ("route", "-6", "delete", "8000::/1", "::1") in dels6
    # The tunnel routes and the pinned host route are still cleaned up.
    assert ("route", "delete", "0.0.0.0", "mask", "128.0.0.0", "0.0.0.0") in dels
    assert ("route", "delete", "128.0.0.0", "mask", "128.0.0.0", "0.0.0.0") in dels
    assert ("route", "delete", "203.0.113.10", "mask", "255.255.255.255") in dels


def test_windows_add_failure_raises(monkeypatch, win_net):
    def run(args, **_k):
        # The first add (0.0.0.0) is refused; the delete before it is best
        # effort and ignored.
        return types.SimpleNamespace(
            returncode=int(args[2] == "0.0.0.0" and args[1] == "add"),
            stdout="", stderr="File exists")

    monkeypatch.setattr(win_net.proc, "run", run)
    with pytest.raises(RuntimeError, match="0.0.0.0"):
        win_net.add_killswitch_routes()


def test_windows_ipv6_blocked_reads_the_route_table(monkeypatch, win_net):
    # Both halves blackholed (next hop ::1) -> covered.
    def ps_lines(script, **_k):
        return ["1"] if "DestinationPrefix" in script else []
    monkeypatch.setattr(win_net.proc, "ps_lines", ps_lines)
    assert win_net.ipv6_blocked() is True
    # One half not blackholed -> not covered.
    def ps_lines_partial(script, **_k):
        return ["0"] if "::/1" in script else ["1"]
    monkeypatch.setattr(win_net.proc, "ps_lines", ps_lines_partial)
    assert win_net.ipv6_blocked() is False
    # No v6 blackholes at all -> not covered.
    monkeypatch.setattr(win_net.proc, "ps_lines", lambda *a, **k: ["0"])
    assert win_net.ipv6_blocked() is False


def test_windows_v6_failure_is_quiet_and_keeps_v4(monkeypatch, win_net, caplog):
    # IPv6 is disabled/unsupported: the v6 adds are refused. That must not
    # raise, must not spam, and must not take the v4 protection down.
    calls: list[list[str]] = []

    def run(args, **_k):
        calls.append(list(args))
        # Only the first v6 add (::/1) is refused; everything else succeeds.
        refused = (args[:2] == ["route", "-6"] and args[2] == "add"
                   and args[3] == "::/1")
        return types.SimpleNamespace(
            returncode=int(refused), stdout="",
            stderr="The object already exists" if refused else "")

    monkeypatch.setattr(win_net.proc, "run", run)
    with caplog.at_level("DEBUG", logger="xrayui.core._windows_test"):
        win_net.add_killswitch_routes()  # must not raise
    # The v4 blackholes were still installed.
    v4_adds = [c for c in calls if c[:2] == ["route", "add"]]
    assert v4_adds == [
        ["route", "add", "0.0.0.0", "mask", "128.0.0.0", "127.0.0.1", "metric", "1000"],
        ["route", "add", "128.0.0.0", "mask", "128.0.0.0", "127.0.0.1", "metric", "1000"],
    ]
    # The v6 failure is logged at debug, not warning/error.
    assert any("IPv6" in r.message for r in caplog.records)
    assert all(r.levelno < 30 for r in caplog.records)


# -- connect / teardown flow ------------------------------------------------

def _stub_connect(monkeypatch, tmp_path, *, killswitch=True):
    """Drive _connect_generic with every side effect recorded, none performed."""
    from tests.test_tun_routing import _stub_connect as base_stub

    conn, calls = base_stub(monkeypatch, tmp_path)
    # The kill switch calls land in `calls` too, so their order against the
    # tunnel routes can be checked.
    monkeypatch.setattr(connection.network, "add_killswitch_routes",
                        lambda: calls.append("add_killswitch"))
    monkeypatch.setattr(connection.network, "remove_killswitch_routes",
                        lambda: calls.append("remove_killswitch"))
    settings = copy.deepcopy(app_settings.DEFAULTS)
    settings["killswitch"]["enabled"] = killswitch
    monkeypatch.setattr(connection.app_settings, "load", lambda: settings)
    return conn, calls


def _iface():
    return Interface("Ethernet 3", "172.21.1.24", "172.21.1.1", 28)


def test_connect_with_killswitch_on_installs_the_blackholes(monkeypatch, tmp_path):
    conn, calls = _stub_connect(monkeypatch, tmp_path, killswitch=True)
    conn._connect_generic(types.SimpleNamespace(uid="p1"), _iface(),
                          "185.229.204.23", DnsState(mode="DHCP", servers=[]))
    assert calls.count("add_killswitch") == 1
    assert conn.killswitch_active is True
    # The blackholes go in after the tunnel routes, so they only win once
    # those are gone.
    assert calls.index("add_default_routes") < calls.index("add_killswitch")


def test_connect_with_killswitch_off_installs_nothing(monkeypatch, tmp_path):
    conn, calls = _stub_connect(monkeypatch, tmp_path, killswitch=False)
    conn._connect_generic(types.SimpleNamespace(uid="p1"), _iface(),
                          "185.229.204.23", DnsState(mode="DHCP", servers=[]))
    assert "add_killswitch" not in calls
    assert conn.killswitch_active is False
    assert conn.state.is_connected()


def test_a_failed_killswitch_keeps_the_connection_and_says_not_active(
        monkeypatch, tmp_path):
    conn, _calls = _stub_connect(monkeypatch, tmp_path, killswitch=True)

    def boom():
        raise RuntimeError("route add failed")

    monkeypatch.setattr(connection.network, "add_killswitch_routes", boom)
    steps: list[str] = []
    conn._log = steps.append

    conn._connect_generic(types.SimpleNamespace(uid="p1"), _iface(),
                          "185.229.204.23", DnsState(mode="DHCP", servers=[]))
    # The optional feature must never break the main connection.
    assert conn.state.is_connected()
    assert conn.killswitch_active is False
    assert any("kill switch" in s and "WARNING" in s for s in steps)


def test_disconnect_leaves_no_blackhole(monkeypatch, tmp_path):
    conn, calls = _stub_connect(monkeypatch, tmp_path, killswitch=True)
    conn._connect_generic(types.SimpleNamespace(uid="p1"), _iface(),
                          "185.229.204.23", DnsState(mode="DHCP", servers=[]))
    assert conn.killswitch_active is True

    # remove_routes (called by _restore) is what deletes the blackholes; the
    # argv tests above prove it does. Here: disconnect calls it and clears the
    # flag, so the UI stops claiming the internet is blocked.
    # Stub the bridge stop: the real one runs pkill, which would hit a live
    # tun2socks tunnel on the developer's machine.
    monkeypatch.setattr(conn.tun2socks, "stop", lambda: None)
    monkeypatch.setattr(connection.network, "restore_dns", lambda *a, **k: True)
    monkeypatch.setattr(connection.network, "release_stranded_dns", lambda **k: [])
    conn._restore()
    assert "remove_routes" in calls
    assert conn.killswitch_active is False
    assert not conn.state.is_connected()


def test_failed_connect_leaves_no_blackhole(monkeypatch, tmp_path):
    from tests.test_tun_routing import _stub_connect as base_stub

    conn, calls = base_stub(monkeypatch, tmp_path, tun=None)  # TUN never appears
    ks: list[str] = []
    monkeypatch.setattr(connection.network, "add_killswitch_routes",
                        lambda: ks.append("add_killswitch"))
    settings = copy.deepcopy(app_settings.DEFAULTS)
    settings["killswitch"]["enabled"] = True
    monkeypatch.setattr(connection.app_settings, "load", lambda: settings)
    monkeypatch.setattr(conn.tun2socks, "stop", lambda: None)

    with pytest.raises(connection.ConnectError, match="did not appear"):
        conn._connect_generic(types.SimpleNamespace(uid="p1"), _iface(),
                              "185.229.204.23", DnsState(mode="DHCP", servers=[]))
    # The rollback remove_routes runs, so no blackhole is left behind.
    assert "remove_routes" in calls
    assert conn.killswitch_active is False
    assert not conn.state.is_connected()


def test_stale_recovery_leaves_no_blackhole(monkeypatch, tmp_path):
    # A previous run crashed with the kill switch on: the next launch's
    # recover_if_stale must restore the network, deleting the blackholes.
    from tests.test_tun_routing import _stub_connect as base_stub

    conn, calls = base_stub(monkeypatch, tmp_path)
    monkeypatch.setattr(connection, "IS_MAC", False)
    monkeypatch.setattr(connection.xray_mod, "is_xray_running", lambda: False)
    conn.state.save(_iface(), "185.229.204.23", 42, DnsState(mode="DHCP", servers=[]))
    monkeypatch.setattr(connection.network, "restore_dns", lambda *a, **k: True)
    monkeypatch.setattr(connection.network, "release_stranded_dns", lambda **k: [])

    assert conn.recover_if_stale() is True
    assert "remove_routes" in calls
    assert not conn.state.is_connected()


# -- UI ---------------------------------------------------------------------

def test_ui_checkbox_saves(qapp, monkeypatch):
    from xrayui.ui.settings_window import SettingsWindow

    settings = copy.deepcopy(app_settings.DEFAULTS)
    win = SettingsWindow(settings)
    page = win._pages["general"]
    assert page.killswitch.isChecked() is False
    page.killswitch.setChecked(True)
    assert win.values()["killswitch"] == {"enabled": True}
    # A saved-on setting is read back into the checkbox.
    settings["killswitch"]["enabled"] = True
    assert SettingsWindow(settings)._pages["general"].killswitch.isChecked() is True


def test_status_line_only_when_enabled_connected_and_xray_stopped(qapp):
    from xrayui.ui import main_window as ui

    class _Label:
        def __init__(self):
            self._text = ""
            self.style = ""

        def text(self):
            return self._text

        def setText(self, t):
            self._text = t

        def setStyleSheet(self, s):
            self.style = s

    def window(*, connected, killswitch, running):
        return types.SimpleNamespace(
            conn=types.SimpleNamespace(
                is_connected=lambda: connected,
                killswitch_active=killswitch,
                state=types.SimpleNamespace(chain_uid=None)),
            _connected_profile=lambda: types.SimpleNamespace(name="S", uid="p1"),
            _connected_chain=None,
            profiles=types.SimpleNamespace(model=types.SimpleNamespace(
                country_of=lambda _uid: None)),
            toolbar=types.SimpleNamespace(subtitle=_Label()),
            _subtitle_pix=None, _subtitle_dropped=False, _xray_running=running,
        )

    # enabled + connected + xray stopped -> the red line
    w = window(connected=True, killswitch=True, running=False)
    ui.MainWindow._refresh_status_subtitle(w)
    assert "VPN dropped" in w.toolbar.subtitle.text()

    # xray running -> the normal connected line, not the drop notice
    w = window(connected=True, killswitch=True, running=True)
    ui.MainWindow._refresh_status_subtitle(w)
    assert "VPN dropped" not in w.toolbar.subtitle.text()

    # kill switch off -> never the drop notice
    w = window(connected=True, killswitch=False, running=False)
    ui.MainWindow._refresh_status_subtitle(w)
    assert "VPN dropped" not in w.toolbar.subtitle.text()

    # disconnected -> never the drop notice
    w = window(connected=False, killswitch=True, running=False)
    ui.MainWindow._refresh_status_subtitle(w)
    assert "VPN dropped" not in w.toolbar.subtitle.text()


def test_fa_keys_present():
    from xrayui.i18n_fa import TRANSLATIONS_FA

    for key in (
        "Block the internet if the VPN drops (kill switch)",
        "Applies from the next connect.",
        "VPN dropped: internet is blocked. Reconnect, or press "
        "Disconnect to restore normal internet.",
    ):
        assert key in TRANSLATIONS_FA, key


def test_mac_blackhole_always_names_a_gateway(monkeypatch):
    # `route add -net X -blackhole` with no gateway is "Invalid argument" on a
    # real macOS (checked live as root), so the kill switch was never
    # installed. Every add must carry the loopback gateway.
    calls = _mac(monkeypatch)
    posix.add_killswitch_routes()
    adds = [c for c in calls if c[:3] == ["route", "-n", "add"]]
    assert adds
    for c in adds:
        gateway = c[c.index("-blackhole") - 1]
        assert gateway in ("127.0.0.1", "::1"), c
