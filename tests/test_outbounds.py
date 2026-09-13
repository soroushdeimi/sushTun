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
