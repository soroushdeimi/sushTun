"""Linux backend: elevation, DNS under systemd-resolved, and coexisting clients.

Each case here was a way the Linux build failed while Windows worked: the
elevated window never opened, lookups blackholed or leaked, a disconnect left
no DNS, and connecting killed another client's xray.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import types
from pathlib import Path

import pytest

from xrayui import elevate, paths
from xrayui.core import _net_posix as posix
from xrayui.core import connection, xray
from xrayui.core.network import DnsState, Interface
from xrayui.core.state import State

LINUX_ONLY = pytest.mark.skipif(sys.platform != "linux", reason="Linux network backend")
ROOT = Path(__file__).resolve().parent.parent


def _record(monkeypatch, stdout=""):
    ran: list[list[str]] = []

    def fake_run(args, **_k):
        ran.append(list(args))
        return types.SimpleNamespace(returncode=0, stdout=stdout(args) if callable(stdout) else stdout)

    monkeypatch.setattr(posix.proc, "run", fake_run)
    return ran


# -- elevation -------------------------------------------------------------
def _relaunch(monkeypatch, rc):
    calls = []
    monkeypatch.setattr(elevate.shutil, "which",
                        lambda name: "/usr/bin/pkexec" if name == "pkexec" else None)
    monkeypatch.setattr(elevate.subprocess, "call", lambda args: calls.append(args) or rc)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XAUTHORITY", "/run/user/1000/xauth")
    return calls, elevate._relaunch_linux()


def test_pkexec_relaunch_carries_the_display_into_the_elevated_process(monkeypatch):
    calls, started = _relaunch(monkeypatch, 0)
    assert started
    args = calls[0]
    assert args[0] == "/usr/bin/pkexec"
    # pkexec runs the app itself, so a polkit policy keyed on its path matches.
    assert "/usr/bin/env" not in args
    assert "--session-env=DISPLAY=:0" in args
    assert "--session-env=WAYLAND_DISPLAY=wayland-0" in args
    assert "--session-env=XAUTHORITY=/run/user/1000/xauth" in args
    # A source run starts in root's home: launched by absolute script path,
    # carrying this interpreter's import path for --user site-packages.
    assert str(ROOT / "app_main.py") in args
    assert any(a.startswith("--session-env=PYTHONPATH=") for a in args)


@pytest.mark.parametrize("rc", [126, 127])
def test_refused_pkexec_falls_back_to_an_unelevated_window(monkeypatch, rc):
    _calls, started = _relaunch(monkeypatch, rc)
    assert started is False


def test_session_env_is_applied_and_stripped_but_only_for_known_keys(monkeypatch):
    monkeypatch.setenv("DISPLAY", "unset-by-test")
    monkeypatch.delenv("LD_PRELOAD", raising=False)

    rest = elevate.apply_session_env([
        "sushtun", "--session-env=DISPLAY=:1",
        "--session-env=LD_PRELOAD=/tmp/evil.so", "--restore-stale",
    ])

    assert rest == ["sushtun", "--restore-stale"]
    assert os.environ["DISPLAY"] == ":1"
    assert "LD_PRELOAD" not in os.environ  # runs as root: never honoured


# -- child processes of the frozen app -------------------------------------
def test_system_tools_do_not_inherit_the_bundles_libraries(monkeypatch):
    from xrayui.core import proc
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(proc, "IS_WIN", False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/sushtun/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    # Seen live: resolvectl loaded the bundle's libcrypto, died, and DNS was
    # never moved into the tunnel.
    assert "LD_LIBRARY_PATH" not in proc.child_env()

    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    env = proc.child_env({"ALIAS": "eth0"})
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env
    assert env["ALIAS"] == "eth0"


def test_source_runs_pass_the_library_path_through(monkeypatch):
    from xrayui.core import proc
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/home/u/lib")
    assert proc.child_env()["LD_LIBRARY_PATH"] == "/home/u/lib"


# -- installed (.deb) data location ----------------------------------------
def _frozen_at(monkeypatch, exe: Path):
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


@LINUX_ONLY
def test_installed_build_keeps_data_out_of_opt(monkeypatch, tmp_path):
    exe = tmp_path / "opt" / "sushtun" / "sushtun"
    _frozen_at(monkeypatch, exe)
    (exe.parent / paths.INSTALLED_MARKER).touch()

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert paths.base_dir() == paths.INSTALLED_DATA_DIR

    # A refused prompt runs unelevated: it must get a directory it can write.
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.base_dir() == tmp_path / "xdg" / "sushtun"


def test_portable_build_still_writes_next_to_itself(monkeypatch, tmp_path):
    exe = tmp_path / "Downloads" / "XrayPortable-linux"
    _frozen_at(monkeypatch, exe)
    assert paths.base_dir() == exe.parent


# -- DNS under systemd-resolved -------------------------------------------
def _resolved(monkeypatch, *, sticks_after: int = 1):
    """resolved is active; `resolvectl dns xray0` reports our server only once
    it has been set `sticks_after` times (the earlier attempts did not take)."""
    monkeypatch.setattr(posix, "_resolved_active", lambda: True)
    monkeypatch.setattr(posix.time, "sleep", lambda _s: None)
    sets = []

    def stdout(args):
        if args[:2] == ["resolvectl", "dns"] and len(args) == 4:
            sets.append(args)
        if args == ["resolvectl", "dns", posix.TUN_NAME]:
            ok = len(sets) >= sticks_after
            return f"Link 10 ({posix.TUN_NAME}): {posix.TUN_DNS if ok else ''}\n"
        return ""

    return _record(monkeypatch, stdout=stdout)


@LINUX_ONLY
def test_resolved_dns_is_claimed_on_the_tunnel_not_the_physical_link(monkeypatch):
    ran = _resolved(monkeypatch)

    assert posix.set_dns_loopback("enx0") is True

    # resolved pins a link's queries to it; 127.0.0.1 is unreachable via a NIC.
    assert not any("enx0" in cmd for cmd in ran)
    assert not any("127.0.0.1" in cmd for cmd in ran)
    assert ["resolvectl", "dns", posix.TUN_NAME, posix.TUN_DNS] in ran
    assert ["resolvectl", "domain", posix.TUN_NAME, "~."] in ran


@LINUX_ONLY
def test_networkmanager_is_asked_to_leave_the_tun_alone_before_dns_is_set(monkeypatch):
    ran = _resolved(monkeypatch)
    monkeypatch.setattr(posix.shutil, "which", lambda name: f"/usr/bin/{name}")
    posix.set_dns_loopback("enx0")

    unmanage = ran.index(["nmcli", "device", "set", posix.TUN_NAME, "managed", "no"])
    first_dns = ran.index(["resolvectl", "dns", posix.TUN_NAME, posix.TUN_DNS])
    assert unmanage < first_dns


@LINUX_ONLY
def test_cleared_tunnel_dns_is_put_back(monkeypatch):
    # Seen live: xray0's resolved settings vanished minutes after connecting.
    ran = _resolved(monkeypatch, sticks_after=1)
    monkeypatch.setattr(posix, "_tun_dns_applied", lambda: False)
    monkeypatch.setattr(posix, "_claim_tun_dns", lambda attempts=5: ran.append(["claim"]) or True)
    assert posix.repair_tun_dns() is True
    assert ["claim"] in ran


@LINUX_ONLY
def test_intact_tunnel_dns_is_left_alone(monkeypatch):
    ran = _resolved(monkeypatch)
    monkeypatch.setattr(posix, "_tun_dns_applied", lambda: True)
    assert posix.repair_tun_dns() is None
    assert not any(cmd[:2] == ["resolvectl", "dns"] and len(cmd) == 4 for cmd in ran)


def test_dns_watchdog_reports_a_restore_and_warns_only_once(monkeypatch):
    conn = connection.Connection()
    monkeypatch.setattr(conn.state, "is_connected", lambda: True)
    monkeypatch.setattr(connection, "IS_MAC", False)
    steps = []
    conn._log = steps.append

    monkeypatch.setattr(connection.network, "repair_tun_dns", lambda: None)
    assert conn.repair_dns_if_needed() is None

    monkeypatch.setattr(connection.network, "repair_tun_dns", lambda: True)
    assert "restored" in conn.repair_dns_if_needed()

    monkeypatch.setattr(connection.network, "repair_tun_dns", lambda: False)
    assert "WARNING" in conn.repair_dns_if_needed()
    assert conn.repair_dns_if_needed() is None  # not repeated every 15 seconds
    assert sum("WARNING" in s for s in steps) == 1


@LINUX_ONLY
def test_dns_that_did_not_take_is_retried(monkeypatch):
    ran = _resolved(monkeypatch, sticks_after=3)

    assert posix.set_dns_loopback("enx0") is True
    assert ran.count(["resolvectl", "dns", posix.TUN_NAME, posix.TUN_DNS]) == 3


@LINUX_ONLY
def test_dns_that_never_sticks_is_reported_not_hidden(monkeypatch):
    _resolved(monkeypatch, sticks_after=99)
    assert posix.set_dns_loopback("enx0") is False


def test_connect_warns_when_dns_stays_outside_the_tunnel(monkeypatch, tmp_path):
    from tests.test_tun_routing import _iface, _stub_connect

    conn, _calls = _stub_connect(monkeypatch, tmp_path)
    monkeypatch.setattr(connection.network, "set_dns_loopback", lambda alias: False)
    steps = []
    conn._log = steps.append

    conn._connect_generic(types.SimpleNamespace(), _iface(), "185.229.204.23",
                          DnsState(mode="RESOLVED"))
    assert any("unencrypted" in s for s in steps)


def test_tunnel_dns_address_routes_into_the_tun():
    import ipaddress
    net = ipaddress.ip_network(f"{posix.TUN_ADDRESS}/{posix.TUN_PREFIX_LEN}", strict=False)
    assert ipaddress.ip_address(posix.TUN_DNS) in net
    assert posix.TUN_DNS != posix.TUN_ADDRESS


@LINUX_ONLY
def test_restore_leaves_the_physical_links_dns_alone(monkeypatch):
    monkeypatch.setattr(posix, "_resolved_active", lambda: True)
    ran = _record(monkeypatch, stdout="Link 8 (enx0): 4.2.2.1 8.8.8.8\n")

    assert posix.restore_dns("enx0", DnsState(mode="RESOLVED")) is True
    # revert would wipe what NetworkManager pushed: no DNS until reconnect.
    assert ["resolvectl", "revert", "enx0"] not in ran
    assert ["resolvectl", "revert", posix.TUN_NAME] in ran


@LINUX_ONLY
def test_restore_still_rescues_a_link_an_older_build_pinned_to_loopback(monkeypatch):
    monkeypatch.setattr(posix, "_resolved_active", lambda: True)
    ran = _record(monkeypatch, stdout="Link 8 (enx0): 127.0.0.1\n")

    posix.restore_dns("enx0", DnsState(mode="RESOLVED"))
    assert ["resolvectl", "revert", "enx0"] in ran


def test_resolv_conf_backup_survives_the_state_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    original = ["# Generated by NetworkManager", "search lan", "nameserver 192.168.1.1"]
    State().save(Interface("eth0", "192.168.1.5", "192.168.1.1"), "1.2.3.4", 5,
                 DnsState(mode="FILE", servers=original))

    assert State().dns_state().servers == original


def test_dns_server_list_still_parses_one_per_line(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    State().save(Interface("Wi-Fi", "10.0.0.2", "10.0.0.1"), "1.2.3.4", 5,
                 DnsState(mode="STATIC", servers=["1.1.1.1", "8.8.8.8"]))
    assert State().dns_state().servers == ["1.1.1.1", "8.8.8.8"]


# -- other VPN clients -----------------------------------------------------
def test_only_our_own_xray_is_matched(monkeypatch, tmp_path):
    cfg = tmp_path / "sush.Tun" / "config.runtime.json"
    monkeypatch.setattr(paths, "runtime_config", lambda: cfg)
    pattern = re.compile(xray._own_pattern())

    assert pattern.search(f"/tmp/_MEI123/xray run -c {cfg}")
    assert not pattern.search("/home/u/.local/share/v2rayN/bin/xray/xray run -c config.json")
    # The dot in the path is literal, not "any character".
    assert not pattern.search(f"xray run -c {str(cfg).replace('sush.Tun', 'sushXTun')}")


@LINUX_ONLY
def test_foreign_tunnel_names_a_vpn_whose_policy_rules_outvote_ours(monkeypatch):
    # Real v2rayN/sing-box output: its rules send traffic to table 2022.
    _record(monkeypatch, stdout='[{"dst":"1.1.1.1","gateway":"172.18.0.2",'
                                '"dev":"singbox_tun","table":"2022"}]')
    assert posix.foreign_tunnel("enx0") == "singbox_tun"

    _record(monkeypatch, stdout='[{"dst":"1.1.1.1","gateway":"172.21.1.1","dev":"enx0"}]')
    assert posix.foreign_tunnel("enx0") is None

    _record(monkeypatch, stdout="")  # offline: `ip route get` prints nothing
    assert posix.foreign_tunnel("enx0") is None


@LINUX_ONLY
def test_openvpn_default_route_in_main_table_is_allowed_alongside(monkeypatch):
    # OpenVPN's default (metric 50) loses to our /1 routes: no reason to refuse.
    _record(monkeypatch, stdout='[{"dst":"1.1.1.1","gateway":"172.16.0.1","dev":"tun0"}]')
    assert posix.foreign_tunnel("wlp2s0") is None


def _detect_with(monkeypatch, routes: str, links: str):
    def stdout(args):
        if args[:4] == ["ip", "-j", "route", "show"]:
            return routes
        if args[:4] == ["ip", "-j", "link", "show"]:
            return links
        return '[{"addr_info":[{"family":"inet","local":"172.20.10.2"}]}]'
    _record(monkeypatch, stdout=stdout)
    return posix._linux_detect()


# Real output with two NetworkManager OpenVPN connections up over Wi-Fi.
_OPENVPN_ROUTES = ('[{"dst":"default","gateway":"172.16.0.1","dev":"tun0","metric":50},'
                   '{"dst":"default","gateway":"172.10.1.1","dev":"tun1","metric":50},'
                   '{"dst":"default","gateway":"172.20.10.1","dev":"wlp2s0","metric":600}]')
_LINKS = ('[{"ifname":"lo","link_type":"loopback"},{"ifname":"wlp2s0","link_type":"ether"},'
          '{"ifname":"tun0","link_type":"none"},{"ifname":"tun1","link_type":"none"}]')


@LINUX_ONLY
def test_uplink_is_the_physical_link_not_a_lower_metric_vpn(monkeypatch):
    iface = _detect_with(monkeypatch, _OPENVPN_ROUTES, _LINKS)
    # tun0 has the lowest metric, but binding Xray to it tunnels sushTun
    # through the office VPN and dies whenever that VPN reconnects.
    assert (iface.alias, iface.gateway) == ("wlp2s0", "172.20.10.1")


@LINUX_ONLY
def test_uplink_falls_back_to_a_tunnel_when_nothing_else_has_a_default(monkeypatch):
    routes = '[{"dst":"default","gateway":"10.8.0.1","dev":"tun0","metric":50}]'
    iface = _detect_with(monkeypatch, routes, _LINKS)
    assert iface.alias == "tun0"


def test_connect_refuses_while_another_vpn_owns_the_route(monkeypatch):
    monkeypatch.setattr(connection.network, "detect_interface",
                        lambda: Interface("enx0", "172.21.1.24", "172.21.1.1"))
    monkeypatch.setattr(connection.network, "foreign_tunnel", lambda alias: "singbox_tun")
    conn = connection.Connection()
    monkeypatch.setattr(conn.state, "is_connected", lambda: False)
    profile = types.SimpleNamespace(address="1.2.3.4", id="u", protocol="vless", pbk="")

    with pytest.raises(connection.ConnectError, match="singbox_tun"):
        conn.connect(profile)


# -- .deb packaging --------------------------------------------------------
def _build_deb():
    spec = importlib.util.spec_from_file_location("build_deb", ROOT / "scripts" / "build_deb.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@LINUX_ONLY
def test_deb_tree_installs_launcher_icon_policy_and_marker(tmp_path):
    deb = _build_deb()
    onedir = tmp_path / "dist" / "sushtun"
    onedir.mkdir(parents=True)
    (onedir / "sushtun").write_text("#!/bin/sh\n", encoding="utf-8")
    (onedir / "sushtun").chmod(0o755)

    root = deb.stage(onedir, tmp_path / "pkg", "9.9.9", "amd64")

    # The marker is what switches the app's data to /var/lib/sushtun.
    assert (root / "opt/sushtun" / paths.INSTALLED_MARKER).exists()
    assert os.readlink(root / "usr/bin/sushtun") == deb.EXE
    desktop = (root / "usr/share/applications/sushtun.desktop").read_text(encoding="utf-8")
    assert "Exec=sushtun" in desktop and "Icon=sushtun" in desktop
    # Must equal the id app.py passes to setDesktopFileName for the dock icon.
    assert "StartupWMClass=sushtun" in desktop
    assert (root / "usr/share/icons/hicolor/512x512/apps/sushtun.png").stat().st_size > 0
    policy = (root / f"usr/share/polkit-1/actions/{deb.POLICY_ID}.policy").read_text(encoding="utf-8")
    assert f'exec.path">{deb.EXE}<' in policy
    control = (root / "DEBIAN/control").read_text(encoding="utf-8")
    assert "Version: 9.9.9" in control and "Architecture: amd64" in control
    assert (root / "DEBIAN/postinst").stat().st_mode & 0o777 == 0o755
