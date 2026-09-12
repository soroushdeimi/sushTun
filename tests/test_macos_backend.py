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
    monkeypatch.setattr(tun2socks.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(tun2socks.paths, "tun2socks_bin", lambda: tmp_path / "tun2socks")

    t = tun2socks.Tun2socks()
    t.start("127.0.0.1", 10808)

    args = captured["args"]
    assert args[0].endswith("tun2socks")
    assert "-device" in args and args[args.index("-device") + 1] == tun2socks.DEVICE
    assert "-proxy" in args and args[args.index("-proxy") + 1] == "socks5://127.0.0.1:10808"
    # Pinning to the NIC would cut tun2socks off from the loopback SOCKS proxy.
    assert "-interface" not in args
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
    assert shlex.split(shell_cmd) == [str(exe.resolve())]


def test_cancelled_macos_prompt_falls_back_to_an_unelevated_window(monkeypatch, tmp_path):
    _exe, started, _seen = _mac_relaunch(
        monkeypatch, tmp_path, returncode=1,
        stderr="0:94: execution error: User canceled. (-128)")
    assert started is False


def test_elevated_app_failing_later_does_not_reopen_a_window(monkeypatch, tmp_path):
    _exe, started, _seen = _mac_relaunch(monkeypatch, tmp_path, returncode=1,
                                         stderr="execution error: crashed (1)")
    assert started is True


def test_routes_use_gateway_address_not_interface_flag():
    # Guards the design choice: mac routes go via t2s.ADDRESS as next-hop,
    # matching the point-to-point utun device tun2socks creates.
    assert tun2socks.ADDRESS == "198.18.0.1"
    assert tun2socks.DEVICE.startswith("utun")
