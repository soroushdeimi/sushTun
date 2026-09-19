"""VMess/Trojan/Shadowsocks outbound builders, and xray -test on the
rendered configs for every transport/TLS combination Phase 4a adds.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import outbounds, render, xraycheck
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


def _skip_if_no_binary():
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")


# -- builder shape -----------------------------------------------------------
def test_vmess_outbound_shape():
    p = Profile(protocol="vmess", address="a.com", port=443, id="uid-1",
                vmess_security="chacha20-poly1305")
    out = outbounds.build(p, "proxy")
    assert out["protocol"] == "vmess"
    assert out["settings"] == {
        "vnext": [{"address": "a.com", "port": 443,
                   "users": [{"id": "uid-1", "security": "chacha20-poly1305"}]}]
    }
    assert "alterId" not in json.dumps(out)  # AEAD-only: never emitted


def test_vmess_default_security_is_auto():
    p = Profile(protocol="vmess", address="a.com", port=443, id="uid-1")
    out = outbounds.build(p, "proxy")
    assert out["settings"]["vnext"][0]["users"][0]["security"] == "auto"


def test_trojan_outbound_shape():
    p = Profile(protocol="trojan", address="b.com", port=443, id="pw1")
    out = outbounds.build(p, "proxy")
    assert out["protocol"] == "trojan"
    assert out["settings"] == {"servers": [{"address": "b.com", "port": 443, "password": "pw1"}]}


def test_shadowsocks_outbound_shape():
    p = Profile(protocol="shadowsocks", address="c.com", port=8388, id="pw2",
                ss_method="aes-256-gcm")
    out = outbounds.build(p, "proxy")
    assert out["protocol"] == "shadowsocks"
    assert out["settings"] == {
        "servers": [{"address": "c.com", "port": 8388, "method": "aes-256-gcm", "password": "pw2"}]
    }


# -- transport / TLS extensions ----------------------------------------------
def test_xhttp_settings_only_set_keys_present():
    p = Profile(protocol="vless", address="a.com", port=443, id="u", network="xhttp")
    stream = outbounds.build(p, "proxy")["streamSettings"]
    assert stream["xhttpSettings"] == {}
    p2 = Profile(protocol="vless", address="a.com", port=443, id="u", network="xhttp",
                path="/x", host="a.com", xhttp_mode="packet-up",
                xhttp_extra='{"headers": {"X-Test": "1"}}')
    stream2 = outbounds.build(p2, "proxy")["streamSettings"]
    assert stream2["xhttpSettings"] == {
        "path": "/x", "host": "a.com", "mode": "packet-up",
        "extra": {"headers": {"X-Test": "1"}},
    }


def test_xhttp_extra_invalid_json_is_dropped_not_raised():
    p = Profile(protocol="vless", address="a.com", port=443, id="u", network="xhttp",
                xhttp_extra="not json")
    stream = outbounds.build(p, "proxy")["streamSettings"]
    assert "extra" not in stream["xhttpSettings"]


def test_httpupgrade_settings():
    p = Profile(protocol="vless", address="a.com", port=443, id="u", network="httpupgrade",
                path="/hu", host="a.com")
    stream = outbounds.build(p, "proxy")["streamSettings"]
    assert stream["httpupgradeSettings"] == {"path": "/hu", "host": "a.com"}


def test_tcp_http_header_settings():
    p = Profile(protocol="vless", address="a.com", port=443, id="u", network="tcp",
                header_type="http", path="/p", host="a.com,b.com")
    stream = outbounds.build(p, "proxy")["streamSettings"]
    assert stream["tcpSettings"] == {
        "header": {"type": "http", "request": {"path": ["/p"], "headers": {"Host": ["a.com", "b.com"]}}}
    }


def test_plain_tcp_unchanged_without_header_type():
    p = Profile(protocol="vless", address="a.com", port=443, id="u", network="tcp")
    stream = outbounds.build(p, "proxy")["streamSettings"]
    assert "tcpSettings" not in stream


def test_new_tls_keys_only_set_when_present():
    p = Profile(protocol="vless", address="a.com", port=443, id="u", security="tls",
                ech="ECHCONFIG", pcs="ab" * 32, vcn="a.com")
    tls = outbounds.build(p, "proxy")["streamSettings"]["tlsSettings"]
    assert tls["echConfigList"] == "ECHCONFIG"
    assert tls["pinnedPeerCertSha256"] == "ab" * 32
    assert tls["verifyPeerCertByName"] == "a.com"


def test_allow_insecure_is_never_rendered():
    # The bundled Xray binary hard-refuses "allowInsecure" (feature sunset
    # past 2026-06-01); rendering it would make Xray refuse to start.
    p = Profile(protocol="vless", address="a.com", port=443, id="u", security="tls",
                allow_insecure=True)
    tls = outbounds.build(p, "proxy")["streamSettings"]["tlsSettings"]
    assert "allowInsecure" not in tls


def test_render_snapshot_untouched_by_new_fields():
    # Defaults for every new Profile field must render byte-identical to a
    # profile that never set them -- Phase 4a's fields are additive.
    plain = Profile(protocol="vless", address="a.com", port=443, id="u",
                    network="tcp", security="none")
    extended = Profile(protocol="vless", address="a.com", port=443, id="u",
                       network="tcp", security="none", vmess_security="auto",
                       ss_method="", header_type="", xhttp_mode="", xhttp_extra="",
                       allow_insecure=False, ech="", pcs="", vcn="")
    assert (render.build_text(plain, "Wi-Fi", TEMPLATE)
            == render.build_text(extended, "Wi-Fi", TEMPLATE))


# -- xray -test on rendered configs ------------------------------------------
def _profile(protocol: str, network: str, tls: bool) -> Profile:
    base: dict = dict(name="t", protocol=protocol, address="example.com", port=443, network=network)
    if protocol == "shadowsocks":
        base.update(id="pass123", ss_method="aes-256-gcm")
    else:
        base["id"] = ("11111111-1111-1111-1111-111111111111" if protocol == "vmess"
                      else "pass123")
    if tls:
        base.update(security="tls", sni="example.com")
    if network == "ws":
        base.update(path="/ws", host="example.com")
    elif network == "grpc":
        base.update(service_name="svc")
    elif network == "xhttp":
        base.update(path="/xh", host="example.com", xhttp_mode="packet-up")
    elif network == "httpupgrade":
        base.update(path="/hu", host="example.com")
    return Profile(**base)


@pytest.mark.parametrize("protocol", ["vmess", "trojan", "shadowsocks"])
@pytest.mark.parametrize("network", ["tcp", "ws", "grpc", "xhttp", "httpupgrade"])
@pytest.mark.parametrize("tls", [False, True])
def test_xray_test_accepts_every_transport(tmp_path, monkeypatch, protocol, network, tls):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    p = _profile(protocol, network, tls)
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False)
    assert xraycheck.check_config(text) is None, f"{protocol}/{network}/tls={tls}"


@pytest.mark.parametrize("protocol", ["vmess", "trojan", "shadowsocks"])
def test_xray_test_accepts_tcp_http_header(tmp_path, monkeypatch, protocol):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    id_ = "11111111-1111-1111-1111-111111111111" if protocol == "vmess" else "pass123"
    kwargs = {"ss_method": "aes-256-gcm"} if protocol == "shadowsocks" else {}
    p = Profile(name="t", protocol=protocol, address="example.com", port=443, id=id_,
               network="tcp", header_type="http", path="/", host="example.com", **kwargs)
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False)
    assert xraycheck.check_config(text) is None


@pytest.mark.parametrize("protocol", ["vmess", "trojan", "shadowsocks"])
def test_xray_test_accepts_new_tls_keys(tmp_path, monkeypatch, protocol):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    id_ = "11111111-1111-1111-1111-111111111111" if protocol == "vmess" else "pass123"
    kwargs = {"ss_method": "aes-256-gcm"} if protocol == "shadowsocks" else {}
    p = Profile(name="t", protocol=protocol, address="example.com", port=443, id=id_,
               network="tcp", security="tls", sni="example.com",
               pcs="ab" * 32, vcn="example.com", **kwargs)
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False)
    assert xraycheck.check_config(text) is None


# -- Hysteria2 ----------------------------------------------------------------
def _hy2(**over) -> Profile:
    base = dict(name="hy", protocol="hysteria2", address="a.example.com", port=443,
               id="hy2-auth", sni="a.example.com")
    base.update(over)
    return Profile(**base)


def test_hysteria2_outbound_shape():
    out = outbounds.build(_hy2(), "proxy")
    assert out["protocol"] == "hysteria"
    assert out["settings"] == {"address": "a.example.com", "port": 443, "version": 2}
    stream = out["streamSettings"]
    assert stream["network"] == "hysteria"
    assert stream["security"] == "tls"
    assert stream["hysteriaSettings"] == {"version": 2, "auth": "hy2-auth"}
    assert stream["tlsSettings"] == {"serverName": "a.example.com"}
    assert stream["finalmask"] == {"quicParams": {"congestion": "bbr"}}


def test_hysteria2_security_is_always_tls_regardless_of_profile_security():
    out = outbounds.build(_hy2(security="none"), "proxy")
    assert out["streamSettings"]["security"] == "tls"


def test_hysteria2_salamander_obfuscation():
    out = outbounds.build(_hy2(hy2_obfs_password="obfspass"), "proxy")
    assert out["streamSettings"]["finalmask"]["udp"] == [
        {"type": "salamander", "settings": {"password": "obfspass"}}
    ]


def test_hysteria2_port_hopping():
    out = outbounds.build(_hy2(hy2_ports="20000-30000", hy2_hop_interval="45"), "proxy")
    assert out["streamSettings"]["finalmask"]["quicParams"]["udpHop"] == {
        "ports": "20000-30000", "interval": "45"
    }


def test_hysteria2_port_hopping_without_interval_omits_it():
    # No interval typed: omit the key entirely and let Xray use its own
    # default, rather than us guessing one.
    out = outbounds.build(_hy2(hy2_ports="20000-30000"), "proxy")
    assert "interval" not in out["streamSettings"]["finalmask"]["quicParams"]["udpHop"]


def test_hysteria2_brutal_up_down():
    out = outbounds.build(_hy2(hy2_up_mbps=100, hy2_down_mbps=50), "proxy")
    quic = out["streamSettings"]["finalmask"]["quicParams"]
    assert quic["congestion"] == "brutal"
    assert quic["brutalUp"] == "100mbps"
    assert quic["brutalDown"] == "50mbps"


def test_hysteria2_no_up_down_uses_bbr():
    out = outbounds.build(_hy2(), "proxy")
    assert out["streamSettings"]["finalmask"]["quicParams"]["congestion"] == "bbr"


def test_hysteria2_allow_insecure_is_never_rendered():
    out = outbounds.build(_hy2(allow_insecure=True), "proxy")
    assert "allowInsecure" not in out["streamSettings"]["tlsSettings"]


def test_hysteria2_new_tls_keys():
    out = outbounds.build(_hy2(alpn="h3", pcs="ab" * 32, vcn="a.example.com"), "proxy")
    tls = out["streamSettings"]["tlsSettings"]
    assert tls["alpn"] == ["h3"]
    assert tls["pinnedPeerCertSha256"] == "ab" * 32
    assert tls["verifyPeerCertByName"] == "a.example.com"


# -- hop interval / port range / pcs hardening (review fix round) -----------
def test_hysteria2_hop_interval_accepts_bare_seconds_and_trailing_s():
    from xrayui.core.outbounds.hysteria2 import normalize_hop_interval
    assert normalize_hop_interval("30") == "30"
    assert normalize_hop_interval("30s") == "30"
    assert normalize_hop_interval("10-30") == "10-30"


def test_hysteria2_hop_interval_rejects_junk_without_raising():
    from xrayui.core.outbounds.hysteria2 import normalize_hop_interval
    assert normalize_hop_interval("abc") is None
    assert normalize_hop_interval("") is None
    assert normalize_hop_interval("30x") is None


@pytest.mark.parametrize("interval,expect_key", [
    ("30s", True), ("abc", False), ("10-30", True),
])
def test_hysteria2_xray_test_accepts_or_omits_hop_interval(
    tmp_path, monkeypatch, interval, expect_key,
):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    p = _hy2(hy2_ports="20000-30000", hy2_hop_interval=interval)
    out = outbounds.build(p, "proxy")
    has_key = "interval" in out["streamSettings"]["finalmask"]["quicParams"]["udpHop"]
    assert has_key == expect_key
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False)
    assert xraycheck.check_config(text) is None, interval


def test_hysteria2_ports_accepts_colon_and_comma_forms():
    from xrayui.core.outbounds.hysteria2 import normalize_ports
    assert normalize_ports("20000-30000") == "20000-30000"
    assert normalize_ports("20000:30000") == "20000-30000"
    assert normalize_ports("20000, 30000-31000") == "20000,30000-31000"


def test_hysteria2_ports_rejects_junk_and_out_of_range_without_raising():
    from xrayui.core.outbounds.hysteria2 import normalize_ports
    assert normalize_ports("garbage") is None
    assert normalize_ports("") is None
    assert normalize_ports("0-70000") is None
    assert normalize_ports("99999") is None


def test_hysteria2_garbage_ports_omits_udphop_but_still_validates(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    p = _hy2(hy2_ports="not-a-port-range")
    out = outbounds.build(p, "proxy")
    assert "udpHop" not in out["streamSettings"]["finalmask"]["quicParams"]
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False)
    assert xraycheck.check_config(text) is None


def test_hysteria2_pcs_is_normalized_from_colon_uppercase_form():
    colon_form = ":".join(["AB"] * 32)
    out = outbounds.build(_hy2(pcs=colon_form), "proxy")
    assert out["streamSettings"]["tlsSettings"]["pinnedPeerCertSha256"] == "ab" * 32


def test_hysteria2_invalid_pcs_is_dropped_not_rendered():
    out = outbounds.build(_hy2(pcs="not-a-valid-pin"), "proxy")
    assert "pinnedPeerCertSha256" not in out["streamSettings"]["tlsSettings"]


@pytest.mark.parametrize("protocol", ["vless", "vmess", "trojan", "shadowsocks"])
def test_pcs_is_normalized_for_every_stream_protocol(protocol):
    id_ = "11111111-1111-1111-1111-111111111111" if protocol == "vmess" else "pw"
    kwargs = {"ss_method": "aes-256-gcm"} if protocol == "shadowsocks" else {}
    colon_form = ":".join(["CD"] * 32)
    p = Profile(protocol=protocol, address="a.example.com", port=443, id=id_,
               security="tls", sni="a.example.com", pcs=colon_form, **kwargs)
    out = outbounds.build(p, "proxy")
    assert out["streamSettings"]["tlsSettings"]["pinnedPeerCertSha256"] == "cd" * 32


@pytest.mark.parametrize("protocol", ["vless", "vmess", "trojan", "shadowsocks"])
def test_invalid_pcs_is_dropped_for_every_stream_protocol(protocol):
    id_ = "11111111-1111-1111-1111-111111111111" if protocol == "vmess" else "pw"
    kwargs = {"ss_method": "aes-256-gcm"} if protocol == "shadowsocks" else {}
    p = Profile(protocol=protocol, address="a.example.com", port=443, id=id_,
               security="tls", sni="a.example.com", pcs="garbage", **kwargs)
    out = outbounds.build(p, "proxy")
    assert "pinnedPeerCertSha256" not in out["streamSettings"]["tlsSettings"]


@pytest.mark.parametrize("variant,kwargs", [
    ("plain", {}),
    ("salamander", {"hy2_obfs_password": "obfspass"}),
    ("port_hopping", {"hy2_ports": "20000-30000", "hy2_hop_interval": "30"}),
    ("brutal_up_down", {"hy2_up_mbps": 100, "hy2_down_mbps": 50}),
    ("bbr_no_up_down", {}),
])
def test_hysteria2_xray_test_accepts_every_variant(tmp_path, monkeypatch, variant, kwargs):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    p = _hy2(**kwargs)
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False)
    assert xraycheck.check_config(text) is None, variant


def test_hysteria2_build_test_config_validates(tmp_path, monkeypatch):
    from xrayui.core import speedtest
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    cfg = speedtest.build_test_config([_hy2()], [11500], "lo")
    cfg.pop("routing", None)
    assert xraycheck.check_config(json.dumps(cfg)) is None


def _pqv_key() -> str:
    import base64
    return base64.urlsafe_b64encode(bytes(1952)).rstrip(b"=").decode()


def _reality(**kw) -> Profile:
    return Profile(protocol="vless", address="a.com", port=443, id="u", network="tcp",
                   security="reality", sni="a.com", fp="chrome",
                   pbk="Z84J2IelR9ch3k8VtlVhhs5ycBUlXA7wHBWcBrjqnAw", sid="ab", **kw)


def test_reality_pqv_is_rendered_only_when_valid():
    reality = outbounds.build(_reality(pqv=_pqv_key()), "proxy")["streamSettings"][
        "realitySettings"]
    assert reality["mldsa65Verify"] == _pqv_key()
    for pqv in ("", "not-a-key", _pqv_key() + "="):
        reality = outbounds.build(_reality(pqv=pqv), "proxy")["streamSettings"][
            "realitySettings"]
        # Xray refuses to start on a malformed key, so a bad one is dropped.
        assert "mldsa65Verify" not in reality, pqv


def test_xray_test_accepts_a_reality_pqv(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    text = render.build_text(_reality(pqv=_pqv_key()), "lo", TEMPLATE, include_tun=False)
    assert "mldsa65Verify" in text
    assert xraycheck.check_config(text) is None


_DOWNLOAD = {"address": "cdn.example.com", "port": 443, "network": "xhttp",
             "security": "tls", "tlsSettings": {"serverName": "cdn.example.com"},
             "xhttpSettings": {"path": "/down"}}


def _xhttp_split(**download) -> Profile:
    extra = {"downloadSettings": {**_DOWNLOAD, **download}}
    return Profile(protocol="vless", address="a.com", port=443, id="u", network="xhttp",
                   security="tls", sni="a.com", path="/up", xhttp_extra=json.dumps(extra))


def test_xhttp_download_settings_are_bound_to_the_physical_interface():
    out = json.loads(render.build_text(_xhttp_split(), "eth0", TEMPLATE, include_tun=False))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    download = proxy["streamSettings"]["xhttpSettings"]["extra"]["downloadSettings"]
    assert download["sockopt"]["interface"] == "eth0"
    assert download["address"] == "cdn.example.com"  # the rest is untouched


def test_xhttp_download_keeps_a_user_chosen_sockopt():
    p = _xhttp_split(sockopt={"interface": "wg0", "tcpFastOpen": True})
    download = outbounds.build(p, "proxy")["streamSettings"]["xhttpSettings"]["extra"][
        "downloadSettings"]
    assert download["sockopt"] == {"interface": "wg0", "tcpFastOpen": True}


def test_xray_test_accepts_a_bound_xhttp_download(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    text = render.build_text(_xhttp_split(), "lo", TEMPLATE, include_tun=False)
    assert xraycheck.check_config(text) is None
