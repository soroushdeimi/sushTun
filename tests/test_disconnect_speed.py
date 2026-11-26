"""Disconnect must feel instant: immediate UI feedback, concurrent teardown.

The button used to leave the window looking connected for seconds while a
dozen `route`/`networksetup` calls ran one by one. These tests fail on that
behaviour: the click handler must acknowledge at once, the independent
teardown steps must overlap, and a hung bridge must not burn the old full
grace period.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import connection as connection_mod  # noqa: E402
from xrayui.core import tun2socks as t2s_mod  # noqa: E402
from xrayui.core._net_common import DnsState, Interface  # noqa: E402
from xrayui.i18n import tr  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _connected_conn(monkeypatch, tmp_path, **kwargs):
    """A Connection with saved connected state and a stubbed environment."""
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "cfg.json")
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(connection_mod.bootrestore, "uninstall", lambda: None)
    conn = connection_mod.Connection(on_step=lambda _m: None)
    conn.state.save(Interface("en0", "192.168.1.5", "192.168.1.1"),
                    "203.0.113.10", 0,
                    DnsState(mode="DHCP", servers=[]), **kwargs)
    return conn


def _sleepy(name, seconds, intervals, lock):
    def fn(*a, **k):
        start = time.monotonic()
        with lock:
            intervals[name] = [start, None]
        time.sleep(seconds)
        with lock:
            intervals[name][1] = time.monotonic()
    return fn


def test_teardown_actions_run_concurrently(monkeypatch, tmp_path):
    # Three 0.4 s steps back to back are 1.2 s; side by side ~0.4 s.
    monkeypatch.setattr(connection_mod, "IS_MAC", True)
    conn = _connected_conn(monkeypatch, tmp_path)
    intervals: dict[str, list] = {}
    lock = threading.Lock()
    monkeypatch.setattr(conn.tun2socks, "stop", _sleepy("t2s", 0.4, intervals, lock))
    monkeypatch.setattr(conn.xray, "stop", _sleepy("xray", 0.4, intervals, lock))
    monkeypatch.setattr(connection_mod.network, "remove_routes",
                        _sleepy("routes", 0.4, intervals, lock))
    monkeypatch.setattr(connection_mod.network, "restore_dns", lambda *a, **k: True)
    monkeypatch.setattr(connection_mod.network, "release_stranded_dns",
                        lambda exclude=None: [])

    started = time.monotonic()
    assert conn._restore() is True
    wall = time.monotonic() - started

    assert wall < 1.0, f"teardown took {wall:.2f}s: steps ran sequentially"
    spans = list(intervals.values())
    assert len(spans) == 3
    assert any(a[0] < b[1] and b[0] < a[1] for i, a in enumerate(spans)
               for b in spans[i + 1:]), "no two teardown steps ever overlapped"


def test_failing_step_does_not_skip_the_rest(monkeypatch, tmp_path):
    # Parallelism must keep the old guarantee: every step is attempted even
    # when another one blows up, and the state is still cleared.
    monkeypatch.setattr(connection_mod, "IS_MAC", True)
    conn = _connected_conn(monkeypatch, tmp_path)
    ran = []

    def boom(*a, **k):
        ran.append("xray")
        raise RuntimeError("cannot kill xray")

    monkeypatch.setattr(conn.xray, "stop", boom)
    monkeypatch.setattr(conn.tun2socks, "stop", lambda: ran.append("t2s"))
    monkeypatch.setattr(connection_mod.network, "remove_routes",
                        lambda *a, **k: ran.append("routes"))
    monkeypatch.setattr(connection_mod.network, "restore_dns", lambda *a, **k: True)
    monkeypatch.setattr(connection_mod.network, "release_stranded_dns",
                        lambda exclude=None: [])

    assert conn._restore() is False
    assert sorted(ran) == ["routes", "t2s", "xray"]
    assert not conn.state.is_connected()


def test_second_disconnect_is_a_noop(monkeypatch, tmp_path):
    # Double-clicking Disconnect must not run the teardown twice.
    monkeypatch.setattr(connection_mod, "IS_MAC", False)
    monkeypatch.setattr(connection_mod.xray_mod, "is_xray_running", lambda: False)
    conn = _connected_conn(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(conn.xray, "stop", lambda: calls.append("xray"))
    monkeypatch.setattr(connection_mod.network, "remove_routes",
                        lambda *a, **k: calls.append("routes"))
    monkeypatch.setattr(connection_mod.network, "restore_dns",
                        lambda *a, **k: calls.append("dns") or True)
    monkeypatch.setattr(connection_mod.network, "release_stranded_dns",
                        lambda exclude=None: [])

    conn.disconnect()
    conn.disconnect()

    assert calls.count("routes") == 1
    assert calls.count("dns") == 1
    assert not conn.state.is_connected()


class _HungChild:
    """A child that ignores SIGTERM and survives SIGKILL for its grace."""

    def __init__(self):
        self.waits: list = []
        self.killed = 0

    def terminate(self):
        pass

    def kill(self):
        self.killed += 1

    def wait(self, timeout=None):
        self.waits.append(timeout)
        raise subprocess.TimeoutExpired("tun2socks", timeout)

    def poll(self):
        return None


def test_hung_bridge_gives_up_after_a_short_grace(monkeypatch):
    # The old code waited the full 3 s grace, then SIGKILLed and returned as
    # if everything was fine. A hung bridge must surface quickly instead.
    monkeypatch.setattr(t2s_mod, "kill_stale", lambda: None)
    bridge = t2s_mod.Tun2socks()
    bridge._proc = _HungChild()

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        bridge.stop()
    wall = time.monotonic() - started

    assert bridge._proc is None
    assert wall < 2.9, f"hung bridge stalled stop for {wall:.2f}s"


def test_hung_bridge_uses_a_short_grace_then_kill(monkeypatch):
    # Deterministic half of the above: terminate, a short poll, then kill.
    monkeypatch.setattr(t2s_mod, "kill_stale", lambda: None)
    bridge = t2s_mod.Tun2socks()
    child = _HungChild()
    bridge._proc = child

    with pytest.raises(subprocess.TimeoutExpired):
        bridge.stop()

    assert child.waits == [1, 1]
    assert child.killed == 1


def test_exited_bridge_is_not_killed(monkeypatch):
    # A process that already exited must return at once, without touching
    # kill and without waiting out any grace period.
    monkeypatch.setattr(t2s_mod, "kill_stale", lambda: None)
    bridge = t2s_mod.Tun2socks()

    class _Exited:
        killed = 0

        def terminate(self):
            pass

        def kill(self):
            type(self).killed += 1

        def wait(self, timeout=None):
            return 0

    child = _Exited()
    bridge._proc = child
    started = time.monotonic()
    bridge.stop()
    assert time.monotonic() - started < 1.0
    assert child.killed == 0
    assert bridge._proc is None


def test_macos_route_deletes_stay_complete_but_parallel(monkeypatch):
    # Seventeen deletes (six nets x two modes + two v4 kill switch blackholes
    # + two v6 kill switch blackholes + host), one networksetup-style latency
    # each: sequential that is 17x, parallel a fraction of it.
    from xrayui.core import _net_posix as posix

    monkeypatch.setattr(posix, "IS_MAC", True)
    seen = []
    lock = threading.Lock()

    def fake_run(cmd, **kw):
        with lock:
            seen.append(cmd)
        time.sleep(0.05)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(posix.proc, "run", fake_run)
    started = time.monotonic()
    posix.remove_routes("1.2.3.4")
    wall = time.monotonic() - started

    assert len(seen) == 17
    assert ["route", "-n", "delete", "-host", "1.2.3.4"] in seen
    # The tunnel /2s and the old /1s are each deleted in both native and
    # bridge form. (The old /1s share their prefixes with the kill switch
    # blackholes, so the blackhole deletes are counted separately below.)
    for dest in (*posix.MAC_SPLIT, *posix._MAC_OLD_SPLIT):
        assert sum(1 for c in seen if dest in c) >= 2, dest
    # The kill switch blackholes are deleted too, so a disconnect never leaves
    # one behind to keep the internet blocked.
    for dest in posix.KILLSWITCH_SPLIT:
        assert ["route", "-n", "delete", "-net", dest] in seen, dest
    # The v6 blackholes are deleted too, so no v6 leak is left behind.
    for dest in posix.KILLSWITCH_V6_SPLIT:
        assert ["route", "-n", "delete", "-inet6", "-net", dest] in seen, dest
    assert wall < 0.5, f"route sweep took {wall:.2f}s: deletes ran sequentially"


def test_stranded_sweep_resets_only_loopback(monkeypatch):
    # One service stranded by an older session is repaired, the untouched
    # ones are left alone, and the excluded active service is never probed
    # for a reset.
    from xrayui.core import _net_posix as posix

    monkeypatch.setattr(posix, "IS_MAC", True)
    dns_of = {"Wi-Fi": "127.0.0.1", "Ethernet": "empty", "USB LAN": "8.8.8.8",
              "Thunderbolt": "127.0.0.1"}
    order = "\n".join(
        ["(1) header"]
        + [ln for svc, dev in
            [("Wi-Fi", "en0"), ("Ethernet", "en1"), ("USB LAN", "en5"),
             ("Thunderbolt", "bridge0")]
            for ln in (f"(x) {svc}", f"(Hardware Port: P, Device: {dev})")])
    sets = []
    probes: list[list] = []
    lock = threading.Lock()

    def fake_run(cmd, **kw):
        if cmd[1] == "-getdnsservers":
            start = time.monotonic()
            time.sleep(0.1)
            with lock:
                probes.append([start, time.monotonic()])
            val = dns_of[cmd[2]]
            out = ("There aren't any DNS Servers set on this service."
                   if val == "empty" else val)
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if cmd[1] == "-setdnsservers":
            sets.append(cmd[2])
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[1] == "-listnetworkserviceorder":
            return SimpleNamespace(returncode=0, stdout=order, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(posix.proc, "run", fake_run)
    reset = posix.release_stranded_dns(exclude="en0")

    assert reset == ["bridge0"]
    assert sets == ["Thunderbolt"]
    # Three probes (Wi-Fi is excluded) at 0.1 s each: sequential they never
    # overlap; side by side at least two are in flight together.
    assert len(probes) == 3
    assert any(a[0] < b[1] and b[0] < a[1] for i, a in enumerate(probes)
               for b in probes[i + 1:]), "services probed one by one"


def _pump(condition, timeout=5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def _window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    return MainWindow(elevated=False)


def test_disconnect_click_reports_at_once(qapp, tmp_path, monkeypatch):
    # Clicking Disconnect must acknowledge immediately (button off plus a
    # "Disconnecting..." state), not when the worker gets scheduled.
    win = _window(qapp, tmp_path, monkeypatch)
    try:
        win.conn.state.save(Interface("en0", "192.168.1.5", "192.168.1.1"),
                            "203.0.113.10", 0, DnsState(mode="DHCP", servers=[]))
        win.show()
        win._refresh_status()
        assert win.btn_disconnect.isEnabled()

        def slow_disconnect():
            time.sleep(0.5)
            win.conn.state.clear()

        monkeypatch.setattr(win.conn, "disconnect", slow_disconnect)
        started = time.monotonic()
        win._disconnect()
        returned = time.monotonic() - started

        assert returned < 0.3, f"click handler blocked for {returned:.2f}s"
        assert not win.btn_disconnect.isEnabled()
        assert win.step_label.text() == tr("Disconnecting...")
        _pump(lambda: not win._busy)
        assert not win._busy
    finally:
        win.tailer.stop()
        win.close()


def test_disconnect_while_busy_is_ignored(qapp, tmp_path, monkeypatch):
    # A second click (or Disconnect racing a connect) must be a safe no-op,
    # never a second teardown.
    win = _window(qapp, tmp_path, monkeypatch)
    try:
        win._busy = True
        monkeypatch.setattr(win.conn, "disconnect",
                            lambda: pytest.fail("teardown started twice"))
        before = win.step_label.text()
        win._disconnect()
        assert win.step_label.text() == before
    finally:
        win._busy = False
        win.tailer.stop()
        win.close()
