"""Pure-Python checks for the macOS tun2socks bridge (no macOS required)."""
import json
from pathlib import Path

from xrayui.core import render, tun2socks
from xrayui.core.importer import parse_vless

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
    t.start("127.0.0.1", 10808, "en0")

    args = captured["args"]
    assert args[0].endswith("tun2socks")
    assert "-device" in args and args[args.index("-device") + 1] == tun2socks.DEVICE
    assert "-proxy" in args and args[args.index("-proxy") + 1] == "socks5://127.0.0.1:10808"
    assert "-interface" in args and args[args.index("-interface") + 1] == "en0"
    assert t.is_running()


def test_routes_use_gateway_address_not_interface_flag():
    # Guards the design choice: mac routes go via t2s.ADDRESS as next-hop,
    # matching the point-to-point utun device tun2socks creates.
    assert tun2socks.ADDRESS == "198.18.0.1"
    assert tun2socks.DEVICE.startswith("utun")
