"""settings["core"] -> Xray config overlays: TLS fragment, mux, sniffing,
local proxy and a default TLS fingerprint.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import coreopts, render, xraycheck
from xrayui.core import settings as app_settings
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


def _skip_if_no_binary():
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")


def _core(**over) -> dict:
    d = copy.deepcopy(app_settings.DEFAULTS["core"])
    d.update(over)
    return d


def _profile(**over) -> Profile:
    base = dict(name="p", protocol="vless", address="a.example.com", port=443,
               id="11111111-1111-1111-1111-111111111111", encryption="none",
               network="tcp", security="tls", sni="a.example.com")
    base.update(over)
    return Profile(**base)


def _render(profile=None, **kw):
    return json.loads(render.build_text(profile or _profile(), "lo", TEMPLATE, **kw))


# -- rule zero ----------------------------------------------------------------
def test_defaults_render_byte_identical_with_and_without_core_cfg():
    p = _profile()
    without = render.build_text(p, "lo", TEMPLATE)
    with_defaults = render.build_text(p, "lo", TEMPLATE, core_cfg=_core())
    assert without == with_defaults


def test_defaults_leave_sniffing_and_socks_in_untouched():
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    out = _render(core_cfg=_core())
    tun = next(i for i in out["inbounds"] if i["tag"] == "tun-in")
    tmpl_tun = next(i for i in template["inbounds"] if i["tag"] == "tun-in")
    assert tun["sniffing"] == tmpl_tun["sniffing"]
    socks = next(i for i in out["inbounds"] if i["tag"] == "socks-in")
    tmpl_socks = next(i for i in template["inbounds"] if i["tag"] == "socks-in")
    assert socks == tmpl_socks


# -- fragment -------------------------------------------------------------
def test_fragment_shape_when_enabled():
    out = _render(core_cfg=_core(fragment={"enabled": True, "packets": "tlshello",
                                           "length": "100-200", "interval": "10-20",
                                           "max_split": 0}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert proxy["streamSettings"]["finalmask"] == {
        "tcp": [{"type": "fragment", "settings": {
            "packets": "tlshello", "length": "100-200", "delay": "10-20", "maxSplit": 0,
        }}]
    }


def test_fragment_keeps_sockopt_interface():
    out = _render(core_cfg=_core(fragment={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert proxy["streamSettings"]["sockopt"] == {"interface": "lo"}


def test_fragment_disabled_by_default():
    out = _render(core_cfg=_core())
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert "finalmask" not in proxy["streamSettings"]


def test_fragment_not_applied_without_tls_or_reality():
    out = _render(_profile(security="none"), core_cfg=_core(fragment={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert "finalmask" not in proxy["streamSettings"]


def test_fragment_not_applied_to_wireguard():
    p = Profile(protocol="wireguard", address="a.example.com", port=51820,
               id="SECRETKEY", pbk="PEERKEY")
    out = _render(p, core_cfg=_core(fragment={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert "streamSettings" not in proxy  # wireguard has none at all


def test_fragment_not_applied_to_hysteria2():
    p = Profile(protocol="hysteria2", address="a.example.com", port=443,
               id="hy2-auth", sni="a.example.com")
    out = _render(p, core_cfg=_core(fragment={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert proxy["streamSettings"]["finalmask"] == {"quicParams": {"congestion": "bbr"}}


@pytest.mark.parametrize("field,bad,expected_default", [
    ("packets", "not valid", "tlshello"),
    ("length", "abc", "100-200"),
    ("interval", "xyz", "10-20"),
    ("max_split", -1, 0),
    ("max_split", 20000, 0),
    ("max_split", "notanint", 0),
])
def test_fragment_invalid_fields_fall_back_to_defaults(field, bad, expected_default):
    mask = coreopts.build_fragment_mask({field: bad})
    key = {"packets": "packets", "length": "length", "interval": "delay",
          "max_split": "maxSplit"}[field]
    assert mask["settings"][key] == expected_default


def test_fragment_applied_in_build_test_config():
    from xrayui.core import speedtest
    p = _profile()
    cfg = speedtest.build_test_config([p], [11700], "lo", core_cfg=_core(fragment={"enabled": True}))
    out_tag = f"out-{p.uid}"
    outbound = next(o for o in cfg["outbounds"] if o["tag"] == out_tag)
    assert outbound["streamSettings"]["finalmask"]["tcp"][0]["type"] == "fragment"


@pytest.mark.parametrize("security", ["tls", "reality"])
def test_fragment_xray_test_accepts_it(tmp_path, monkeypatch, security):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    kwargs = {"security": "reality", "pbk": "3g3WHDGa8v18xcdb5DXWSm1p4wjM4Qzg93_VqhZC5Ck",
             "sid": ""} if security == "reality" else {"security": "tls"}
    p = _profile(**kwargs)
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False,
                             core_cfg=_core(fragment={"enabled": True}))
    assert xraycheck.check_config(text) is None


# -- mux --------------------------------------------------------------------
@pytest.mark.parametrize("protocol,flow,expected", [
    ("vless", "", True),
    ("vless", "xtls-rprx-vision", False),
    ("vmess", "", True),
    ("trojan", "", True),
    ("shadowsocks", "", True),
    ("wireguard", "", False),
    ("hysteria2", "", False),
])
def test_mux_eligibility_matrix(protocol, flow, expected):
    p = Profile(protocol=protocol, flow=flow)
    assert coreopts.mux_eligible(p) == expected


def test_mux_shape_when_enabled():
    out = _render(core_cfg=_core(mux={"enabled": True, "concurrency": 4,
                                      "xudp_concurrency": 32, "xudp_proxy_udp443": "allow"}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert proxy["mux"] == {
        "enabled": True, "concurrency": 4, "xudpConcurrency": 32, "xudpProxyUDP443": "allow",
    }


def test_mux_not_applied_to_vless_with_flow():
    out = _render(_profile(flow="xtls-rprx-vision"), core_cfg=_core(mux={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert "mux" not in proxy


def test_mux_disabled_by_default():
    out = _render(core_cfg=_core())
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert "mux" not in proxy


def test_mux_invalid_fields_fall_back_to_defaults():
    built = coreopts.build_mux({"concurrency": 9999, "xudp_concurrency": -1,
                                "xudp_proxy_udp443": "bogus"})
    assert built == {"enabled": True, "concurrency": 8, "xudpConcurrency": 16,
                     "xudpProxyUDP443": "reject"}


def test_mux_xray_test_accepts_it(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    p = _profile(flow="")
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False,
                             core_cfg=_core(mux={"enabled": True}))
    assert xraycheck.check_config(text) is None


# -- sniffing ---------------------------------------------------------------
def test_sniffing_off_removes_it_from_tun_and_socks_in():
    out = _render(core_cfg=_core(sniffing={"enabled": False, "route_only": False}))
    for tag in ("tun-in", "socks-in"):
        inbound = next(i for i in out["inbounds"] if i["tag"] == tag)
        assert "sniffing" not in inbound


def test_sniffing_route_only():
    out = _render(core_cfg=_core(sniffing={"enabled": True, "route_only": True}))
    for tag in ("tun-in", "socks-in"):
        inbound = next(i for i in out["inbounds"] if i["tag"] == tag)
        assert inbound["sniffing"]["routeOnly"] is True
        assert inbound["sniffing"]["enabled"] is True  # untouched


# -- local proxy --------------------------------------------------------------
def test_socks_port_overrides_the_template():
    out = _render(core_cfg=_core(socks_port=12345))
    socks = next(i for i in out["inbounds"] if i["tag"] == "socks-in")
    assert socks["port"] == 12345


@pytest.mark.parametrize("bad_port", [0, 80, 70000, "10808", True, 10085])
def test_invalid_socks_port_falls_back_to_default(bad_port):
    assert coreopts.valid_socks_port(bad_port) == coreopts.DEFAULT_SOCKS_PORT


def test_allow_lan_listens_on_all_interfaces():
    out = _render(core_cfg=_core(allow_lan=True))
    socks = next(i for i in out["inbounds"] if i["tag"] == "socks-in")
    assert socks["listen"] == "0.0.0.0"
    assert "auth" not in socks["settings"]  # no user/pass set


def test_allow_lan_with_credentials_adds_auth():
    out = _render(core_cfg=_core(allow_lan=True, lan_user="u1", lan_pass="p1"))
    socks = next(i for i in out["inbounds"] if i["tag"] == "socks-in")
    assert socks["settings"]["auth"] == "password"
    assert socks["settings"]["accounts"] == [{"user": "u1", "pass": "p1"}]


def test_allow_lan_without_password_does_not_add_auth():
    out = _render(core_cfg=_core(allow_lan=True, lan_user="u1"))
    socks = next(i for i in out["inbounds"] if i["tag"] == "socks-in")
    assert "auth" not in socks["settings"]


@pytest.mark.parametrize("with_auth", [False, True])
def test_allow_lan_xray_test_accepts_it(tmp_path, monkeypatch, with_auth):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    kwargs = {"allow_lan": True}
    if with_auth:
        kwargs.update(lan_user="u1", lan_pass="p1")
    text = render.build_text(_profile(), "lo", TEMPLATE, include_tun=False, core_cfg=_core(**kwargs))
    assert xraycheck.check_config(text) is None


# -- default TLS fingerprint ---------------------------------------------------
def test_default_fp_applied_when_profile_fp_empty():
    out = _render(_profile(fp=""), core_cfg=_core(default_fp="chrome"))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert proxy["streamSettings"]["tlsSettings"]["fingerprint"] == "chrome"


def test_default_fp_does_not_override_profiles_own_fp():
    out = _render(_profile(fp="firefox"), core_cfg=_core(default_fp="chrome"))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert proxy["streamSettings"]["tlsSettings"]["fingerprint"] == "firefox"


def test_default_fp_applied_for_reality():
    p = _profile(security="reality", pbk="3g3WHDGa8v18xcdb5DXWSm1p4wjM4Qzg93_VqhZC5Ck", fp="")
    out = _render(p, core_cfg=_core(default_fp="firefox"))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert proxy["streamSettings"]["realitySettings"]["fingerprint"] == "firefox"


def test_default_fp_ignored_when_not_a_known_value():
    out = _render(_profile(fp=""), core_cfg=_core(default_fp="not-a-real-fp"))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert "fingerprint" not in proxy["streamSettings"]["tlsSettings"]
