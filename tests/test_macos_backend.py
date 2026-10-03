"""Pure-Python checks for the macOS tun2socks bridge (no macOS required)."""
import json
import re
import shlex
import sys
import types
from pathlib import Path

from xrayui import elevate, paths
from xrayui.core import render, tun2socks
from xrayui.core.importer import parse_vless
from xrayui.core.network import DnsState, Interface
from xrayui.core.state import State

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"

SAMPLE = (
    "vless://11111111-1111-1111-1111-111111111111@203.0.113.10:443"
    "?encryption=mlkem768x25519plus.native.0rtt.EXAMPLE_KEY"
    "&type=tcp&security=none#Sample"
)


def test_include_tun_false_drops_only_tun_inbound():
    out = json.loads(render.build_text(parse_vless(SAMPLE), "en0", TEMPLATE, include_tun=False))
    tags = [i["tag"] for i in out["inbounds"]]
    assert "tun-in" not in tags
    assert "socks-in" in tags and "dns-in" in tags


def test_macos_socks_bridge_uses_the_configured_socks_port():
    # _connect_macos waits on and bridges from coreopts.valid_socks_port's
    # result, which must be the exact port render.build_text put on
    # socks-in -- otherwise the bridge waits on a port Xray never opened.
    from xrayui.core import coreopts
    core_cfg = {"socks_port": 12345}
    out = json.loads(render.build_text(parse_vless(SAMPLE), "en0", TEMPLATE,
                                       include_tun=False, core_cfg=core_cfg))
    socks = next(i for i in out["inbounds"] if i["tag"] == "socks-in")
    assert socks["port"] == 12345
    assert coreopts.valid_socks_port(core_cfg.get("socks_port")) == 12345


def test_include_tun_true_keeps_tun_inbound_by_default():
    out = json.loads(render.build_text(parse_vless(SAMPLE), "en0", TEMPLATE))
    tags = [i["tag"] for i in out["inbounds"]]
    assert "tun-in" in tags


def test_tun2socks_process_builds_expected_command(monkeypatch, tmp_path):
    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def poll(self):
            return None

    monkeypatch.setattr(tun2socks.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(tun2socks, "kill_stale", lambda: None)
    monkeypatch.setattr(tun2socks.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(tun2socks.paths, "tun2socks_bin", lambda: tmp_path / "tun2socks")

    t = tun2socks.Tun2socks()
    t.start("127.0.0.1", 10808)

    args = captured["args"]
    assert args[0].endswith("tun2socks")
    # pflag: a single dash is a shorthand, so "-device" was -d "evice" and
    # "-mtu" made tun2socks exit with a usage error before creating anything.
    assert all(not (a.startswith("-") and not a.startswith("--")) for a in args[1:])
    assert "--device" in args and args[args.index("--device") + 1] == tun2socks.DEVICE
    assert "--proxy" in args and args[args.index("--proxy") + 1] == "socks5://127.0.0.1:10808"
    # Pinning to the NIC would cut tun2socks off from the loopback SOCKS proxy.
    assert "--interface" not in args
    assert t.is_running()


def test_macos_service_names_with_spaces_survive_the_state_round_trip(monkeypatch, tmp_path):
    # Split on whitespace, "USB 10/100/1000 LAN" came back as four names and
    # disconnect restored DNS on a service that does not exist, leaving the
    # real one stuck on 127.0.0.1: no internet after disconnecting.
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    State().save(Interface("en5", "192.168.1.5", "192.168.1.1"), "1.2.3.4", 0,
                 DnsState(mode="MACOS", servers=["USB 10/100/1000 LAN", "1.1.1.1"]))
    assert State().dns_state().servers == ["USB 10/100/1000 LAN", "1.1.1.1"]


def _mac_relaunch(monkeypatch, tmp_path, *, returncode, stderr=""):
    exe = tmp_path / "My Apps" / 'Xray "Portable"'
    exe.parent.mkdir(exist_ok=True)
    exe.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "argv", ["sushtun"])
    seen = {}

    def fake_run(args, **_k):
        seen["script"] = args[2]
        return types.SimpleNamespace(returncode=returncode, stderr=stderr)

    monkeypatch.setattr(elevate.subprocess, "run", fake_run)
    return exe, elevate._relaunch_macos(), seen


def test_macos_relaunch_survives_spaces_and_quotes_in_the_path(monkeypatch, tmp_path):
    exe, started, seen = _mac_relaunch(monkeypatch, tmp_path, returncode=0)
    assert started

    literal = re.fullmatch(r'do shell script "(.*)" with administrator privileges',
                           seen["script"]).group(1)
    shell_cmd = re.sub(r"\\(.)", r"\1", literal)  # undo AppleScript escaping
    argv = shlex.split(shell_cmd)
    assert argv[0] == str(exe.resolve())
    assert all(a.startswith("--session-env=") for a in argv[1:])


def test_macos_relaunch_carries_the_session_language(monkeypatch, tmp_path):
    # `do shell script` starts from a bare environment.
    monkeypatch.setenv("LANG", "fa_IR.UTF-8")
    _exe, _started, seen = _mac_relaunch(monkeypatch, tmp_path, returncode=0)
    literal = re.fullmatch(r'do shell script "(.*)" with administrator privileges',
                           seen["script"]).group(1)
    argv = shlex.split(re.sub(r"\\(.)", r"\1", literal))
    assert "--session-env=LANG=fa_IR.UTF-8" in argv


def test_cancelled_macos_prompt_falls_back_to_an_unelevated_window(monkeypatch, tmp_path):
    _exe, started, _seen = _mac_relaunch(
        monkeypatch, tmp_path, returncode=1,
        stderr="0:94: execution error: User canceled. (-128)")
    assert started is False


def test_privacy_protected_folder_falls_back_to_a_window_that_says_why(monkeypatch, tmp_path):
    # The password was accepted, but root was refused the app's own files in
    # ~/Desktop: the elevated copy died before any window, so nothing appeared.
    monkeypatch.setattr(elevate, "mac_privacy_blocked", False)
    _exe, started, _seen = _mac_relaunch(
        monkeypatch, tmp_path, returncode=1,
        stderr="0:402: execution error: PermissionError: [Errno 1] Operation not "
               "permitted: '/Users/me/Desktop/sushTun/.venv/pyvenv.cfg' (1)")
    assert started is False
    assert elevate.mac_privacy_blocked is True


def test_elevated_app_failing_later_does_not_reopen_a_window(monkeypatch, tmp_path):
    _exe, started, _seen = _mac_relaunch(monkeypatch, tmp_path, returncode=1,
                                         stderr="execution error: crashed (1)")
    assert started is True


def test_routes_use_gateway_address_not_interface_flag():
    # Guards the design choice: mac routes go via t2s.ADDRESS as next-hop,
    # matching the point-to-point utun device tun2socks creates.
    assert tun2socks.ADDRESS == "198.18.0.1"
    assert tun2socks.DEVICE.startswith("utun")


# -- macOS network backend (commands faked; runs anywhere) -------------------
def _fake_mac(monkeypatch, outputs):
    """Route _net_posix's commands to canned (returncode, stdout) replies."""
    from xrayui.core import _net_posix

    calls = []

    def fake_run(args, **_k):
        calls.append(list(args))
        rc, out = outputs.get(tuple(args), (0, ""))
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")

    monkeypatch.setattr(_net_posix, "IS_MAC", True)
    monkeypatch.setattr(_net_posix.proc, "run", fake_run)
    return _net_posix, calls


_ROUTE_GET = "   route to: 1.1.1.1\ndestination: 0.0.0.0\n  interface: {}\n      flags: <UP>\n"


def test_another_vpn_is_named_but_never_refused(monkeypatch):
    # Like Windows: sushTun runs alongside it instead of refusing to connect.
    net, _ = _fake_mac(monkeypatch, {
        ("route", "-n", "get", "1.1.1.1"): (0, _ROUTE_GET.format("utun4"))})
    assert net.mac_other_vpn("en0") == "utun4"
    assert net.foreign_tunnel("en0") is None


def test_the_physical_link_or_our_own_tunnel_is_not_another_vpn(monkeypatch):
    for dev in ("en0", tun2socks.DEVICE):
        net, _ = _fake_mac(monkeypatch, {
            ("route", "-n", "get", "1.1.1.1"): (0, _ROUTE_GET.format(dev))})
        assert net.mac_other_vpn("en0") is None


def test_macos_routes_outrank_another_vpns_half_routes(monkeypatch):
    # OpenVPN & co. hold 0/1 + 128/1; adding the same prefixes failed with
    # "File exists". Four /2s are more specific, so ours win.
    net, calls = _fake_mac(monkeypatch, {})
    net.add_default_routes(None)
    added = [c[4] for c in calls if c[:3] == ["route", "-n", "add"]]
    assert added == ["0.0.0.0/2", "64.0.0.0/2", "128.0.0.0/2", "192.0.0.0/2"]
    assert all(c[-1] == tun2socks.ADDRESS for c in calls)


def test_macos_teardown_also_removes_the_old_half_routes(monkeypatch):
    net, calls = _fake_mac(monkeypatch, {})
    net.remove_routes("203.0.113.10")
    deleted = {c[4] for c in calls if c[:4] == ["route", "-n", "delete", "-net"]}
    assert {"0.0.0.0/1", "128.0.0.0/1", "0.0.0.0/2", "192.0.0.0/2"} <= deleted
    assert ["route", "-n", "delete", "-host", "203.0.113.10"] in calls


def test_offline_is_not_another_vpn(monkeypatch):
    net, _ = _fake_mac(monkeypatch, {("route", "-n", "get", "1.1.1.1"): (1, "")})
    assert net.mac_other_vpn("en0") is None


def test_gateway_repair_changes_the_pinned_route_in_place(monkeypatch):
    net, calls = _fake_mac(monkeypatch, {})
    net.replace_host_route("203.0.113.10", "192.168.1.1")
    assert calls == [["route", "-n", "change", "-host", "203.0.113.10", "192.168.1.1"]]


def test_gateway_repair_re_adds_a_route_that_is_gone(monkeypatch):
    net, calls = _fake_mac(monkeypatch, {
        ("route", "-n", "change", "-host", "203.0.113.10", "192.168.1.1"): (1, "")})
    net.replace_host_route("203.0.113.10", "192.168.1.1")
    assert calls[-1] == ["route", "-n", "add", "-host", "203.0.113.10", "192.168.1.1"]


def test_a_refused_dns_change_is_reported(monkeypatch):
    net, _ = _fake_mac(monkeypatch, {
        ("networksetup", "-listnetworkserviceorder"):
            (0, "(1) Wi-Fi\n(Hardware Port: Wi-Fi, Device: en0)\n"),
        ("networksetup", "-setdnsservers", "Wi-Fi", "127.0.0.1"): (4, "")})
    assert net.set_dns_loopback("en0") is False


def test_macos_boot_restore_is_a_root_launch_daemon(monkeypatch, tmp_path):
    # networksetup's DNS survives a reboot; without this a Mac that died while
    # connected came back with DNS on 127.0.0.1 and no internet.
    import plistlib

    from xrayui.core import bootrestore

    plist = tmp_path / "com.soroushdeimi.sushtun.bootrestore.plist"
    monkeypatch.setattr(bootrestore, "IS_MAC", True)
    monkeypatch.setattr(bootrestore, "MAC_PLIST", plist)
    bootrestore.install()
    data = plistlib.loads(plist.read_bytes())
    assert data["Label"] == bootrestore.MAC_LABEL
    assert data["RunAtLoad"] is True
    assert data["ProgramArguments"][-1] == "--restore-stale"
    assert plist.stat().st_mode & 0o777 == 0o644  # launchd skips a writable one
    bootrestore.uninstall()
    assert not plist.exists()


def test_macos_boot_restore_refuses_a_symlink(monkeypatch, tmp_path):
    import pytest

    from xrayui.core import bootrestore

    target = tmp_path / "elsewhere"
    target.write_text("x")
    plist = tmp_path / "daemon.plist"
    plist.symlink_to(target)
    monkeypatch.setattr(bootrestore, "IS_MAC", True)
    monkeypatch.setattr(bootrestore, "MAC_PLIST", plist)
    with pytest.raises(RuntimeError):
        bootrestore.install()
    assert target.read_text() == "x"


def test_a_crashed_sessions_tun2socks_is_stopped_before_starting(monkeypatch):
    # It keeps the utun device, so the next start could not create it.
    seen = []
    monkeypatch.setattr(tun2socks.proc, "run", lambda args, **_k: seen.append(args))
    tun2socks.Tun2socks().stop()
    assert seen == [["pkill", "-f", f"tun2socks --device {tun2socks.DEVICE} "]]


def _mac_connection(monkeypatch, tmp_path, *, device_ok=True, routed="utun233"):
    """A Connection whose macOS connect runs with every system call faked."""
    from xrayui.core import connection

    seen = {"builds": [], "routes": [], "bridge": False}
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")

    def build(*_a, **k):
        seen["builds"].append((k["include_tun"], k["tun_name"]))
        return tmp_path / "cfg.json"
    monkeypatch.setattr(connection.render, "build", build)
    monkeypatch.setattr(connection, "_wait_port", lambda *a, **k: True)
    monkeypatch.setattr(connection.t2s, "bring_up_device", lambda **k: True)
    monkeypatch.setattr(connection.t2s, "kill_stale", lambda: None)
    monkeypatch.setattr(connection.bootrestore, "install", lambda: None)
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: None)
    for name in ("remove_routes", "add_host_route", "add_default_routes", "restore_dns"):
        monkeypatch.setattr(connection.network, name, lambda *a, **k: None)
    monkeypatch.setattr(connection.network, "set_dns_loopback", lambda *a: True)
    monkeypatch.setattr(connection.network, "release_stranded_dns", lambda **k: [])
    fakes = {
        "mac_route_device": lambda _d: routed,
        "mac_ensure_scoped_default": lambda *a: False,
        "mac_other_vpn": lambda _i: None,
        "mac_wait_for_device": lambda **k: device_ok,
        "mac_add_split_routes": lambda native: seen["routes"].append(native),
    }
    for name, fake in fakes.items():
        monkeypatch.setattr(connection.network, name, fake, raising=False)
    conn = connection.Connection()
    monkeypatch.setattr(conn.xray, "start", lambda _cfg: None)
    monkeypatch.setattr(conn.xray, "stop", lambda: None)
    monkeypatch.setattr(conn.xray, "is_running", lambda: True)
    monkeypatch.setattr(conn.tun2socks, "start",
                        lambda *a: seen.__setitem__("bridge", True))
    monkeypatch.setattr(conn.tun2socks, "stop", lambda: None)
    return connection, conn, seen


def _connect(conn):
    conn._connect_macos(parse_vless(SAMPLE), Interface("en0", "192.168.1.5", "192.168.1.1"),
                        "203.0.113.10", DnsState(mode="MACOS"))


def test_macos_connect_uses_xrays_own_tun(monkeypatch, tmp_path):
    # One process instead of two, ~24% less CPU for the same traffic.
    _connection, conn, seen = _mac_connection(monkeypatch, tmp_path)
    _connect(conn)
    assert seen["builds"] == [(True, tun2socks.DEVICE)]
    assert seen["routes"] == [True] and seen["bridge"] is False
    assert conn.state.is_connected()


def test_macos_connect_falls_back_to_the_bridge_without_a_native_tun(monkeypatch, tmp_path):
    _connection, conn, seen = _mac_connection(monkeypatch, tmp_path, device_ok=False)
    _connect(conn)
    assert [b[0] for b in seen["builds"]] == [True, False]  # retried without tun-in
    assert seen["routes"] == [False] and seen["bridge"] is True
    assert conn.state.is_connected()


def test_macos_connect_fails_when_traffic_does_not_enter_the_tunnel(monkeypatch, tmp_path):
    import pytest

    connection, conn, _seen = _mac_connection(monkeypatch, tmp_path, routed="utun4")
    with pytest.raises(connection.ConnectError, match="utun4"):
        _connect(conn)
    assert not conn.state.is_connected()  # torn down, DNS put back


def test_macos_tun_inbound_gets_a_utun_name(monkeypatch):
    out = json.loads(render.build_text(parse_vless(SAMPLE), "en0", TEMPLATE,
                                       tun_name="utun233"))
    tun = next(i for i in out["inbounds"] if i["tag"] == "tun-in")
    assert tun["settings"]["name"] == "utun233"  # macOS refuses anything but utunN


_SCOPED = "   route to: default\n  interface: en0\n      flags: <UP,GATEWAY,DONE,STATIC,{}>\n"


def test_a_missing_scoped_default_route_is_put_back(monkeypatch):
    # Xray pins direct traffic to en0; with only the global default left (seen
    # after OpenVPN Connect), every direct site failed "network is unreachable".
    net, calls = _fake_mac(monkeypatch, {
        ("route", "-n", "get", "-ifscope", "en0", "default"): (0, _SCOPED.format("GLOBAL"))})
    assert net.mac_ensure_scoped_default("en0", "192.168.1.1") is True
    assert calls[-1] == ["route", "-n", "add", "-ifscope", "en0", "default", "192.168.1.1"]


def test_an_existing_scoped_default_route_is_left_alone(monkeypatch):
    net, calls = _fake_mac(monkeypatch, {
        ("route", "-n", "get", "-ifscope", "en0", "default"): (0, _SCOPED.format("IFSCOPE"))})
    assert net.mac_ensure_scoped_default("en0", "192.168.1.1") is False
    assert len(calls) == 1


def test_macos_throughput_reads_the_utun_byte_counters(monkeypatch):
    from xrayui.core import metrics

    table = iter([
        "Name  Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll\n"
        "utun233 1500 <Link#23> 10 0 1000000 5 0 200000 0\n",
        "Name  Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll\n"
        "utun233 1500 <Link#23> 20 0 3097152 9 0 462144 0\n",
    ])
    monkeypatch.setattr(metrics, "IS_MAC", True)
    monkeypatch.setattr(metrics.proc, "run",
                        lambda *_a, **_k: types.SimpleNamespace(stdout=next(table)))
    monkeypatch.setattr(metrics.time, "sleep", lambda _s: None)
    s = metrics.throughput_sample(0, 2)
    assert (s["rx"], s["tx"]) == (2097152, 262144)
    assert (s["rx_mbps"], s["tx_mbps"]) == (8.0, 1.0)


def test_macos_dns_restore_reports_failure_and_retries(monkeypatch):
    net, calls = _fake_mac(monkeypatch, {
        ("networksetup", "-setdnsservers", "Wi-Fi", "1.1.1.1"): (1, "")})
    monkeypatch.setattr(net.time, "sleep", lambda _s: None)
    assert net.restore_dns("en0", DnsState(mode="MACOS", servers=["Wi-Fi", "1.1.1.1"]),
                           retries=3) is False
    assert calls.count(["networksetup", "-setdnsservers", "Wi-Fi", "1.1.1.1"]) == 3


def test_macos_failed_restore_keeps_backup_for_next_recovery(monkeypatch, tmp_path):
    connection, conn, _seen = _mac_connection(monkeypatch, tmp_path)
    monkeypatch.setattr(connection, "IS_MAC", True)
    monkeypatch.setattr(connection.xray_mod, "is_xray_running", lambda: False)
    conn.state.save(Interface("en0", "192.168.1.5", "192.168.1.1"), "203.0.113.10", 0,
                    DnsState(mode="MACOS", servers=["Wi-Fi", "1.1.1.1"]))
    outcomes = iter([False, True])
    monkeypatch.setattr(connection.network, "restore_dns", lambda *a, **k: next(outcomes))
    uninstalled = []
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: uninstalled.append(True))

    assert conn.recover_if_stale() is False
    assert conn.state.dns_state().servers == ["Wi-Fi", "1.1.1.1"]
    assert conn.state.is_connected()
    assert uninstalled == []
    assert conn.recover_if_stale() is True
    assert not conn.state.is_connected()
    assert uninstalled == [True]
