"""Percent escapes belong to the transport after one URL decoding pass."""
import json
from urllib.parse import quote, urlencode

import pytest

from xrayui.core import importer, outbounds, share

UID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize("scheme", ["vless", "trojan", "vmess"])
@pytest.mark.parametrize("network", ["ws", "xhttp"])
def test_transport_percent_escapes_survive_import_share_import(scheme, network):
    path = "/relay/%2F/%25/%E2%9C%93?token=a%26b"
    extra = json.dumps({"headers": {"X-Token": "a%2Fb%25"}})
    query = urlencode({"type": network, "path": path, "extra": extra})
    link = f"{scheme}://{UID}@[2001:db8::1]:443?{query}#" + quote("تهران 🚀")
    original = importer.parse_share_text(link)[0]
    assert original.path == path
    if network == "xhttp":
        assert original.xhttp_extra == extra
    # Standard VMess imports share as the legacy JSON form.
    restored = importer.parse_share_text(share.share_link(original))[0]
    assert restored.path == path
    assert restored.name == "تهران 🚀"
    assert restored.address == "2001:db8::1"
    assert outbounds.build(restored, "proxy")["streamSettings"][
        f"{network}Settings"]["path"] == path


def test_ss_plugin_path_is_decoded_only_once():
    plugin = "v2ray-plugin;mode=websocket;path=/relay/%2F/%25"
    link = "ss://aes-128-gcm:password@example.org:443?" + urlencode({"plugin": plugin})
    profile = importer.parse_share_text(link)[0]
    assert profile.path == "/relay/%2F/%25"


@pytest.mark.parametrize("scheme", ["vless", "trojan", "vmess"])
@pytest.mark.parametrize("network", ["ws", "xhttp", "grpc", "httpupgrade"])
@pytest.mark.parametrize("double", [False, True])
def test_panel_path_compatibility(scheme, network, double):
    path = "/ws%41?ed=2048"
    value = quote(path, safe="") if double else path
    link = f"{scheme}://{UID}@example.org:443?" + urlencode(
        {"type": network, "path": value})
    profile = importer.parse_share_text(link)[0]
    assert profile.path == path
    restored = importer.parse_share_text(share.share_link(profile))[0]
    assert restored.path == path


@pytest.mark.parametrize("scheme", ["vless", "trojan", "vmess"])
@pytest.mark.parametrize("double", [False, True])
def test_panel_extra_compatibility(scheme, double):
    extra = '{"headers":{"X-Token":"%41%3B"}}'
    value = quote(extra, safe="") if double else extra
    link = f"{scheme}://{UID}@example.org:443?" + urlencode(
        {"type": "xhttp", "extra": value})
    profile = importer.parse_share_text(link)[0]
    assert profile.xhttp_extra == extra
    restored = importer.parse_share_text(share.share_link(profile))[0]
    assert restored.xhttp_extra == extra


@pytest.mark.parametrize("double", [False, True])
@pytest.mark.parametrize("plugin", [
    "v2ray-plugin;mode=websocket;host=example.org;path=/ws%41%3B%3D;tls",
    "obfs-local;obfs=http;obfs-host=example.org",
])
def test_panel_plugin_compatibility(plugin, double):
    value = quote(plugin, safe="") if double else plugin
    link = "ss://aes-128-gcm:password@example.org:443?" + urlencode({"plugin": value})
    profile = importer.parse_shadowsocks(link)
    expected = importer.parse_shadowsocks(
        "ss://aes-128-gcm:password@example.org:443?" + urlencode({"plugin": plugin}))
    assert (profile.network, profile.path, profile.host, profile.security) == (
        expected.network, expected.path, expected.host, expected.security)
    restored = importer.parse_shadowsocks(share.share_link(profile))
    assert (restored.network, restored.path, restored.host, restored.security,
            restored.header_type) == (profile.network, profile.path, profile.host,
                                     profile.security, profile.header_type)


def test_invalid_second_decode_is_not_accepted():
    link = f"vless://{UID}@example.org:443?" + urlencode(
        {"path": "%41", "extra": "%7Binvalid"})
    profile = importer.parse_vless(link)
    assert profile.path == "%41"
    assert profile.xhttp_extra == "%7Binvalid"
    with pytest.raises(ValueError):
        importer.parse_shadowsocks(
            "ss://aes-128-gcm:password@example.org:443?" + urlencode(
                {"plugin": "unknown%3Bmode%3Dwebsocket"}))
