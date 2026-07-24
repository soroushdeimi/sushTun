import json
from pathlib import Path

from xrayui.core import render
from xrayui.core.importer import parse_vless
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"

SAMPLE = (
    "vless://11111111-1111-1111-1111-111111111111@203.0.113.10:443"
    "?encryption=mlkem768x25519plus.native.0rtt.EXAMPLE_KEY"
    "&type=tcp&security=none#Sample"
)


def _sub(obj, iface):
    if isinstance(obj, dict):
        return {k: _sub(v, iface) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sub(v, iface) for v in obj]
    if isinstance(obj, str):
        return obj.replace("__IFACE__", iface).replace("__INTERFACE__", iface)
    return obj


def _others(cfg):
    return {k: v for k, v in cfg.items() if k != "outbounds"}, \
        [o for o in cfg["outbounds"] if o.get("tag") != "proxy"]


def test_sample_reproduces_template_exactly():
    expected = _sub(json.loads(TEMPLATE.read_text(encoding="utf-8")), "Wi-Fi")
    out = json.loads(render.build_text(parse_vless(SAMPLE), "Wi-Fi", TEMPLATE))
    assert _others(out) == _others(expected)
    got_proxy = [o for o in out["outbounds"] if o.get("tag") == "proxy"][0]
    exp_proxy = [o for o in expected["outbounds"] if o.get("tag") == "proxy"][0]
    assert got_proxy == exp_proxy


def test_stats_injection():
    out = json.loads(render.build_text(parse_vless(SAMPLE), "Wi-Fi", TEMPLATE, stats=True))
    assert "stats" in out
    assert out["api"]["services"] == ["StatsService"]
    assert out["policy"]["system"]["statsInboundUplink"] is True
    assert any(i.get("tag") == "api" for i in out["inbounds"])
    assert out["routing"]["rules"][0]["inboundTag"] == ["api"]


def test_placeholder_fully_substituted():
    text = render.build_text(parse_vless(SAMPLE), "Ethernet 2", TEMPLATE)
    assert "__IFACE__" not in text and "__INTERFACE__" not in text
    assert "Ethernet 2" in text


def test_non_proxy_untouched_for_reality_profile():
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    p = Profile(name="r", address="a.com", port=443, id="u", network="ws",
                security="reality", pbk="PUB", sid="ab", sni="www.test.com", path="/ws")
    out = json.loads(render.build_text(p, "Wi-Fi", TEMPLATE))
    assert _others(out) == _others(_sub(template, "Wi-Fi"))
    proxy = [o for o in out["outbounds"] if o.get("tag") == "proxy"][0]
    stream = proxy["streamSettings"]
    assert stream["network"] == "ws"
    assert stream["realitySettings"]["publicKey"] == "PUB"
    assert stream["wsSettings"]["path"] == "/ws"
    assert stream["sockopt"]["interface"] == "Wi-Fi"
