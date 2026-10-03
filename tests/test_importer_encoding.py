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
