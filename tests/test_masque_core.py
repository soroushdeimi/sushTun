"""MASQUE core: Profile fields/validation, outbound builder, JSON import and
masque:// share format.

Portable unit suite: no Xray binary dependency. Native `xray run -test`
checks live in tools/verify_masque_config.py (opt-in). Only dummy generic
credentials are used; no real WARP keys, no live network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from xrayui.core import importer, outbounds, render, share
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


def _generic(**over) -> Profile:
    base = dict(name="m", protocol="masque", address="1.2.3.4", port=443,
                network="masque", security="tls", sni="example.com")
    base.update(over)
    return Profile(**base)


def _warp(**over) -> Profile:
    base = dict(name="w", protocol="masque", address="162.159.198.2", port=443,
                network="masque", security="tls",
                sni="consumer-masque.cloudflareclient.com",
                masque_private_key="MHcCAQEEAAAA",
                masque_public_key="MFkwEwYHAAAA",
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
    assert not _generic(masque_private_key="MHcCAQEEAAAA").is_valid()


def test_warp_identity_rejects_basic_auth():
    assert not _warp(username="user", id="pass").is_valid()


def test_masque_requires_masque_network():
    assert not _generic(network="tcp").is_valid()
    assert not _generic(network="").is_valid()


def test_masque_rejects_flow():
    assert not _generic(flow="xtls-rprx-vision").is_valid()


def test_masque_rejects_non_literal_remote_dns():
    assert not _generic(masque_remote_dns="1.1.1.1, dns.example.com").is_valid()
    assert _generic(masque_remote_dns="1.1.1.1, 2606:4700:4700::1111").is_valid()


def test_masque_rejects_colon_in_basic_username():
    assert not _generic(username="user:extra", id="pass").is_valid()


def test_masque_rejects_bad_pcs_and_bad_path():
    assert not _generic(pcs="garbage").is_valid()
    assert not _generic(path="no-slash").is_valid()
    assert _generic(path="/x").is_valid()


def test_warp_identity_rejects_whitespace_only_keys():
    assert not _warp(masque_private_key="   ").is_valid()
    assert not _warp(masque_public_key="\n").is_valid()


def test_warp_identity_rejects_bad_base64_keys():
    assert not _warp(masque_private_key="not base64!!").is_valid()
    assert not _warp(masque_public_key="!!!").is_valid()


def test_warp_identity_rejects_bad_address_prefixes():
    assert not _warp(masque_addresses="172.16.0.2/24").is_valid()
    assert not _warp(masque_addresses="172.16.0.2").is_valid()
    assert not _warp(masque_addresses="not-an-ip/32").is_valid()
    assert not _warp(masque_addresses="172.16.0.2/32, 172.16.0.3/32").is_valid()
    assert not _warp(masque_addresses="172.16.0.2/32, 2606:4700::1/128, 10.0.0.1/32").is_valid()


def test_warp_identity_rejects_malformed_pem():
    assert not _warp(masque_private_key="-----BEGIN EC PRIVATE KEY-----\nnot-base64!!\n-----END EC PRIVATE KEY-----").is_valid()


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


def test_masque_builder_rejects_partial_warp_identity():
    # A partial WARP identity must not silently become anonymous generic MASQUE.
    with pytest.raises(ValueError):
        outbounds.build(_warp(masque_public_key=""), "proxy")
    with pytest.raises(ValueError):
        outbounds.build(_warp(masque_addresses=""), "proxy")


def test_masque_builder_rejects_one_sided_auth():
    # A one-sided credential must not silently downgrade to anonymous generic.
    with pytest.raises(ValueError):
        outbounds.build(_generic(username="user"), "proxy")
    with pytest.raises(ValueError):
        outbounds.build(_generic(id="pass"), "proxy")


def test_masque_builder_rejects_invalid_path_dns_flow():
    with pytest.raises(ValueError):
        outbounds.build(_generic(path="no-slash"), "proxy")
    with pytest.raises(ValueError):
        outbounds.build(_generic(masque_remote_dns="dns.example.com"), "proxy")
    with pytest.raises(ValueError):
        outbounds.build(_generic(flow="xtls-rprx-vision"), "proxy")
    with pytest.raises(ValueError):
        outbounds.build(_generic(security="none"), "proxy")


def test_masque_warp_renders_warp_object():
    out = outbounds.build(_warp(), "proxy")
    assert out["streamSettings"]["masqueSettings"]["warp"] == {
        "privateKey": "MHcCAQEEAAAA",
        "publicKey": "MFkwEwYHAAAA",
        "address": ["172.16.0.2/32", "2606:4700:110:8a36::2/128"],
    }


def test_masque_tls_verification_keys_render():
    out = outbounds.build(_generic(fp="chrome", pcs=":" + "AB" * 32, vcn="example.com"), "proxy")
    tls = out["streamSettings"]["tlsSettings"]
    assert tls["fingerprint"] == "chrome"
    assert tls["pinnedPeerCertSha256"] == "ab" * 32
    assert tls["verifyPeerCertByName"] == "example.com"


def test_masque_builder_rejects_invalid_pcs():
    # An invalid pin is a security downgrade; the builder rejects the profile
    # rather than silently dropping the pin.
    with pytest.raises(ValueError):
        outbounds.build(_generic(pcs="garbage"), "proxy")


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
    assert got.masque_private_key == "MHcCAQEEAAAA"
    assert got.masque_public_key == "MFkwEwYHAAAA"
    assert "172.16.0.2/32" in got.masque_addresses
    assert "2606:4700:110:8a36::2/128" in got.masque_addresses


def _masque_proxy(alpn=None, port=443, network="masque", security="tls"):
    tls: dict = {}
    if alpn is not None:
        tls["alpn"] = alpn
    return {
        "tag": "proxy", "protocol": "masque",
        "settings": {"address": "1.2.3.4", "port": port},
        "streamSettings": {"network": network, "security": security,
                           "masqueSettings": {}, "tlsSettings": tls},
    }


def test_import_alpn_mixed_h2_h3_selects_h3():
    # Xray rule: h2 only when h2 present AND h3 absent.
    p = importer._profile_from_masque_outbound(_masque_proxy(alpn=["h2", "h3"]))
    assert p.masque_http_version == "h3"


def test_import_alpn_h2_only_selects_h2():
    p = importer._profile_from_masque_outbound(_masque_proxy(alpn=["h2"]))
    assert p.masque_http_version == "h2"


def test_import_alpn_h3_only_selects_h3():
    p = importer._profile_from_masque_outbound(_masque_proxy(alpn=["h3"]))
    assert p.masque_http_version == "h3"


def test_import_alpn_omitted_defaults_to_h3():
    p = importer._profile_from_masque_outbound(_masque_proxy())
    assert p.masque_http_version == "h3"


def test_import_alpn_empty_list_defaults_to_h3():
    p = importer._profile_from_masque_outbound(_masque_proxy(alpn=[]))
    assert p.masque_http_version == "h3"


def test_import_alpn_wrong_types_rejected():
    for bad in ("h2", ["h2", 3], [None]):
        with pytest.raises(ValueError):
            importer._profile_from_masque_outbound(_masque_proxy(alpn=bad))


def test_import_port_bool_or_non_integer_rejected():
    for bad in (True, "443", 443.0, 0, 70000):
        with pytest.raises(ValueError):
            importer._profile_from_masque_outbound(_masque_proxy(port=bad))


def test_import_incompatible_network_or_security_rejected():
    with pytest.raises(ValueError):
        importer._profile_from_masque_outbound(_masque_proxy(network="tcp"))
    with pytest.raises(ValueError):
        importer._profile_from_masque_outbound(_masque_proxy(security="none"))


def test_import_method_alias_accepted_when_network_absent():
    proxy = _masque_proxy(alpn=["h2"])
    del proxy["streamSettings"]["network"]
    proxy["streamSettings"]["method"] = "masque"
    p = importer._profile_from_masque_outbound(proxy)
    assert p.protocol == "masque"
    assert p.masque_http_version == "h2"


def test_import_conflicting_network_method_rejected():
    proxy = _masque_proxy()
    proxy["streamSettings"]["method"] = "tcp"
    with pytest.raises(ValueError):
        importer._profile_from_masque_outbound(proxy)


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


def _masque_json(warp=None, **stream_over):
    masque = {}
    if warp is not None:
        masque["warp"] = warp
    stream = {"network": "masque", "security": "tls",
              "masqueSettings": masque, "tlsSettings": {"alpn": ["h2"]}}
    stream.update(stream_over)
    return json.dumps({"outbounds": [
        {"tag": "proxy", "protocol": "masque",
         "settings": {"address": "1.2.3.4", "port": 443},
         "streamSettings": stream},
        {"tag": "direct", "protocol": "freedom"},
    ]})


@pytest.mark.parametrize("warp", [
    {"privateKey": 123, "publicKey": "AQID", "address": ["172.16.0.2/32"]},
    {"privateKey": "AQID", "publicKey": 7, "address": ["172.16.0.2/32"]},
    {"privateKey": "AQID", "publicKey": "AQID", "address": "172.16.0.2/32"},
    {"privateKey": "AQID", "publicKey": "AQID", "address": [123]},
    {"privateKey": "AQID", "publicKey": "AQID", "address": []},
    {"privateKey": "AQID", "publicKey": "AQID"},
    "not-a-dict",
])
def test_json_masque_malformed_warp_rejected(warp):
    # A wrong-typed or incomplete warp must raise ValueError, never crash with
    # an AttributeError and never silently become anonymous generic MASQUE.
    with pytest.raises(ValueError):
        importer.parse_json(_masque_json(warp=warp))


@pytest.mark.parametrize("field, bad", [
    ("user", 5), ("pass", 5), ("host", 5), ("path", 5),
    ("serverName", 5), ("fingerprint", 5),
    ("pinnedPeerCertSha256", 5), ("verifyPeerCertByName", 5),
])
def test_json_masque_malformed_string_field_rejected(field, bad):
    if field in ("user", "pass", "host", "path"):
        cfg = _masque_json()
        data = json.loads(cfg)
        data["outbounds"][0]["streamSettings"]["masqueSettings"][field] = bad
    else:
        cfg = _masque_json()
        data = json.loads(cfg)
        data["outbounds"][0]["streamSettings"]["tlsSettings"][field] = bad
    with pytest.raises(ValueError):
        importer.parse_json(json.dumps(data))


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
    assert got.masque_private_key == "MHcCAQEEAAAA"
    assert got.masque_public_key == "MFkwEwYHAAAA"
    assert "172.16.0.2/32" in got.masque_addresses


def test_share_masque_escapes_special_characters():
    # base64 keys carry + / = and must survive a URL round-trip intact.
    p = _warp(masque_private_key="a+b/AA==", masque_public_key="x/y=")
    link = share.share_link(p)
    got = importer.parse_share_text(link)[0]
    assert got.masque_private_key == "a+b/AA=="
    assert got.masque_public_key == "x/y="


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


def test_share_masque_port_zero_rejected():
    # An explicit :0 must not silently become the 443 default.
    with pytest.raises(ValueError):
        importer.parse_masque("masque://1.2.3.4:0")


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


# Native `xray run -test` checks are opt-in and live in
# tools/verify_masque_config.py so the default unit suite stays portable and
# needs no Xray binary.
