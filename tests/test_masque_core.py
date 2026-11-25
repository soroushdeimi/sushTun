"""MASQUE core: Profile fields/validation, outbound builder, JSON import,
masque:// share format, and xray -test on rendered configs.

Wire shape verified against the bundled Xray 26.10.31 binary (see DONE.md).
Only dummy generic credentials are used; no real WARP keys, no live network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import importer, outbounds, render, share, xraycheck
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


_BASELINE_XRAY = Path(
    "/Users/soroushdeimi/Desktop/myprojects/SUSHTUN/sushTun/xray"
)


def _skip_if_no_binary(monkeypatch):
    if not paths.xray_exe().exists():
        if _BASELINE_XRAY.exists():
            monkeypatch.setattr(paths, "xray_exe", lambda: _BASELINE_XRAY)
        else:
            pytest.skip("bundled xray binary not present")


def _generic(**over) -> Profile:
    base = dict(name="m", protocol="masque", address="1.2.3.4", port=443,
                network="masque", security="tls", sni="example.com")
    base.update(over)
    return Profile(**base)


def _warp(**over) -> Profile:
    base = dict(name="w", protocol="masque", address="162.159.198.2", port=443,
                network="masque", security="tls",
                sni="consumer-masque.cloudflareclient.com",
                masque_private_key="MHcCAQEE-dummy",
                masque_public_key="MFkwEwYH-dummy",
                masque_addresses="172.16.0.2/32, 2606:4700:110:8a36::2/128")
    base.update(over)
    return Profile(**base)


# -- Profile fields / round-trip ---------------------------------------------
def test_masque_fields_have_backwards_compatible_defaults():
    p = Profile()
    assert p.masque_http_version == "h2"
    assert p.masque_private_key == ""
    assert p.masque_public_key == ""
    assert p.masque_addresses == ""
    assert p.masque_remote_dns == ""


def test_masque_fields_round_trip_through_dict():
    p = _generic(masque_http_version="h3", masque_remote_dns="1.1.1.1, 2606:4700:4700::1111")
    data = p.to_dict()
    assert data["masque_http_version"] == "h3"
    assert data["masque_remote_dns"] == "1.1.1.1, 2606:4700:4700::1111"
    p2 = Profile.from_dict(data)
    assert p2.to_dict() == data


def test_existing_profile_round_trip_unchanged_by_masque_fields():
    # A profile that never set the masque fields must render byte-identical
    # to one that explicitly set them to their defaults.
    plain = Profile(protocol="vless", address="a.com", port=443, id="u",
                    network="tcp", security="none")
    extended = Profile(protocol="vless", address="a.com", port=443, id="u",
                       network="tcp", security="none",
                       masque_http_version="h2", masque_private_key="",
                       masque_public_key="", masque_addresses="",
                       masque_remote_dns="")
    assert (render.build_text(plain, "Wi-Fi", TEMPLATE)
            == render.build_text(extended, "Wi-Fi", TEMPLATE))


# -- validation ---------------------------------------------------------------
def test_generic_masque_is_valid_without_auth():
    assert _generic().is_valid()


def test_generic_masque_is_valid_with_both_credentials():
    assert _generic(username="user", id="pass").is_valid()


def test_generic_masque_rejects_one_sided_auth():
    assert not _generic(username="user").is_valid()
    assert not _generic(id="pass").is_valid()


def test_masque_requires_tls_no_plaintext():
    assert not _generic(security="none").is_valid()
    assert not _generic(security="reality").is_valid()


def test_masque_requires_h2_or_h3():
    assert _generic(masque_http_version="h2").is_valid()
    assert _generic(masque_http_version="h3").is_valid()
    assert not _generic(masque_http_version="h1").is_valid()
    assert not _generic(masque_http_version="").is_valid()


def test_masque_requires_an_address():
    assert not _generic(address="").is_valid()


def test_masque_rejects_malformed_port():
    assert not _generic(port=0).is_valid()
    assert not _generic(port=70000).is_valid()


def test_complete_warp_identity_is_valid():
    assert _warp().is_valid()


def test_incomplete_warp_identity_is_rejected():
    assert not _warp(masque_private_key="").is_valid()
    assert not _warp(masque_public_key="").is_valid()
    assert not _warp(masque_addresses="").is_valid()
    # only one of the three set
    assert not _generic(masque_private_key="MHcCAQEE-dummy").is_valid()


def test_warp_identity_rejects_basic_auth():
    assert not _warp(username="user", id="pass").is_valid()


# -- builder shape ------------------------------------------------------------
def test_masque_outbound_shape_generic():
    out = outbounds.build(_generic(), "proxy")
    assert out["protocol"] == "masque"
    assert out["settings"] == {"address": "1.2.3.4", "port": 443}
    stream = out["streamSettings"]
    assert stream["network"] == "masque"
    assert stream["security"] == "tls"
    assert stream["masqueSettings"] == {}
    assert stream["tlsSettings"] == {"serverName": "example.com", "alpn": ["h2"]}
    assert "sockopt" in stream


def test_masque_builder_is_registered_not_vless_fallback():
    # A masque profile must dispatch to the masque builder, not fall through
    # to the vless builder (which would emit a vnext/vless protocol).
    out = outbounds.build(_generic(), "proxy")
    assert out["protocol"] == "masque"
    assert "vnext" not in json.dumps(out)


def test_masque_single_carrier_alpn_is_http_version():
    out = outbounds.build(_generic(masque_http_version="h3"), "proxy")
    assert out["streamSettings"]["tlsSettings"]["alpn"] == ["h3"]


def test_masque_basic_auth_renders_user_pass():
    out = outbounds.build(_generic(username="user", id="pass"), "proxy")
    assert out["streamSettings"]["masqueSettings"] == {"user": "user", "pass": "pass"}


def test_masque_host_path_render():
    out = outbounds.build(_generic(host="example.com", path="/x"), "proxy")
    assert out["streamSettings"]["masqueSettings"] == {"host": "example.com", "path": "/x"}


def test_masque_remote_dns_rendered_as_list():
    out = outbounds.build(_generic(masque_remote_dns="1.1.1.1, 2606:4700:4700::1111"), "proxy")
    assert out["settings"]["remoteDNS"] == ["1.1.1.1", "2606:4700:4700::1111"]


def test_masque_no_remote_dns_omits_key():
    out = outbounds.build(_generic(), "proxy")
    assert "remoteDNS" not in out["settings"]


def test_masque_warp_renders_warp_object():
    out = outbounds.build(_warp(), "proxy")
    assert out["streamSettings"]["masqueSettings"]["warp"] == {
        "privateKey": "MHcCAQEE-dummy",
        "publicKey": "MFkwEwYH-dummy",
        "address": ["172.16.0.2/32", "2606:4700:110:8a36::2/128"],
    }


def test_masque_tls_verification_keys_render():
    out = outbounds.build(_generic(fp="chrome", pcs=":" + "AB" * 32, vcn="example.com"), "proxy")
    tls = out["streamSettings"]["tlsSettings"]
    assert tls["fingerprint"] == "chrome"
    assert tls["pinnedPeerCertSha256"] == "ab" * 32
    assert tls["verifyPeerCertByName"] == "example.com"


def test_masque_invalid_pcs_is_dropped():
    out = outbounds.build(_generic(pcs="garbage"), "proxy")
    assert "pinnedPeerCertSha256" not in out["streamSettings"]["tlsSettings"]


def test_masque_never_renders_allow_insecure_or_reality():
    out = outbounds.build(_generic(allow_insecure=True), "proxy")
    assert "allowInsecure" not in json.dumps(out)
    assert "realitySettings" not in out["streamSettings"]


# -- JSON outbound import -----------------------------------------------------
def _masque_config(p: Profile) -> str:
    proxy = outbounds.build(p, "proxy")
    return json.dumps({"outbounds": [proxy, {"tag": "direct", "protocol": "freedom"}]})


def test_json_masque_outbound_import_generic():
    p = _generic(username="user", id="pass", host="example.com", path="/x",
                 masque_http_version="h3", masque_remote_dns="1.1.1.1")
    got = importer.parse_json(_masque_config(p))
    assert got.protocol == "masque"
    assert got.address == "1.2.3.4"
    assert got.port == 443
    assert got.username == "user"
    assert got.id == "pass"
    assert got.host == "example.com"
    assert got.path == "/x"
    assert got.masque_http_version == "h3"
    assert got.masque_remote_dns == "1.1.1.1"
    assert got.security == "tls"


def test_json_masque_outbound_import_warp():
    p = _warp()
    got = importer.parse_json(_masque_config(p))
    assert got.protocol == "masque"
    assert got.masque_private_key == "MHcCAQEE-dummy"
    assert got.masque_public_key == "MFkwEwYH-dummy"
    assert "172.16.0.2/32" in got.masque_addresses
    assert "2606:4700:110:8a36::2/128" in got.masque_addresses


def test_json_masque_missing_keys_still_imports():
    cfg = {"outbounds": [
        {"tag": "proxy", "protocol": "masque",
         "settings": {"address": "1.2.3.4", "port": 443},
         "streamSettings": {"network": "masque", "security": "tls",
                            "masqueSettings": {},
                            "tlsSettings": {"alpn": ["h2"]}}},
        {"tag": "direct", "protocol": "freedom"},
    ]}
    got = importer.parse_json(json.dumps(cfg))
    assert got.protocol == "masque"
    assert got.masque_http_version == "h2"
    assert got.masque_private_key == ""


# -- masque:// share format ---------------------------------------------------
def test_share_masque_generic_round_trip():
    p = _generic(username="user", id="pass", host="example.com", path="/x",
                 masque_http_version="h3", masque_remote_dns="1.1.1.1, 2606:4700:4700::1111")
    link = share.share_link(p)
    assert link.startswith("masque://")
    got = importer.parse_share_text(link)
    assert len(got) == 1
    g = got[0]
    assert g.protocol == "masque"
    assert g.address == "1.2.3.4"
    assert g.port == 443
    assert g.username == "user"
    assert g.id == "pass"
    assert g.host == "example.com"
    assert g.path == "/x"
    assert g.masque_http_version == "h3"
    assert g.masque_remote_dns == "1.1.1.1, 2606:4700:4700::1111"


def test_share_masque_warp_round_trip():
    p = _warp()
    link = share.share_link(p)
    assert link.startswith("masque://")
    got = importer.parse_share_text(link)[0]
    assert got.masque_private_key == "MHcCAQEE-dummy"
    assert got.masque_public_key == "MFkwEwYH-dummy"
    assert "172.16.0.2/32" in got.masque_addresses


def test_share_masque_escapes_special_characters():
    # base64 keys carry + / = and must survive a URL round-trip intact.
    p = _warp(masque_private_key="a+b/c=d+", masque_public_key="x/y=z")
    link = share.share_link(p)
    got = importer.parse_share_text(link)[0]
    assert got.masque_private_key == "a+b/c=d+"
    assert got.masque_public_key == "x/y=z"


def test_share_masque_ipv6_address():
    p = _generic(address="2606:4700:103::2")
    link = share.share_link(p)
    assert "[2606:4700:103::2]:443" in link
    got = importer.parse_share_text(link)[0]
    assert got.address == "2606:4700:103::2"


def test_share_masque_rejects_bad_http_version():
    with pytest.raises(ValueError):
        importer.parse_masque("masque://1.2.3.4:443?hv=h1")


def test_share_masque_missing_hostname_rejected():
    with pytest.raises(ValueError):
        importer.parse_masque("masque://:443")


def test_share_masque_empty_auth_is_generic():
    p = _generic()
    link = share.share_link(p)
    assert "@" not in link.split("?")[0]
    got = importer.parse_share_text(link)[0]
    assert got.username == ""
    assert got.id == ""


# -- subscription dispatch reaches the parser ---------------------------------
def test_subscription_dispatch_reaches_masque_parser():
    p = _generic(username="user", id="pass")
    link = share.share_link(p)
    got = importer.parse_subscription(link)
    assert len(got) == 1
    assert got[0].protocol == "masque"


# -- xray -test on rendered configs -------------------------------------------
def test_xray_test_accepts_generic_masque(tmp_path, monkeypatch):
    _skip_if_no_binary(monkeypatch)
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    p = _generic(username="user", id="pass")
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False)
    assert xraycheck.check_config(text) is None


def test_xray_test_accepts_h3_masque(tmp_path, monkeypatch):
    _skip_if_no_binary(monkeypatch)
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    p = _generic(masque_http_version="h3", masque_remote_dns="1.1.1.1, 2606:4700:4700::1111")
    text = render.build_text(p, "lo", TEMPLATE, include_tun=False)
    assert xraycheck.check_config(text) is None
