import base64
import json

from xrayui.core import importer

SAMPLE = (
    "vless://11111111-1111-1111-1111-111111111111@203.0.113.10:443"
    "?encryption=mlkem768x25519plus.native.0rtt.KEY&type=tcp&security=none#Sample"
)


def test_parse_vless_fields():
    p = importer.parse_vless(SAMPLE)
    assert p.address == "203.0.113.10"
    assert p.port == 443
    assert p.id == "11111111-1111-1111-1111-111111111111"
    assert p.encryption.startswith("mlkem768x25519plus")
    assert p.network == "tcp"
    assert p.security == "none"
    assert p.name == "Sample"


def test_parse_base64_subscription():
    blob = base64.b64encode(f"{SAMPLE}\n{SAMPLE}".encode()).decode()
    profiles = importer.parse_subscription(blob)
    assert len(profiles) == 2


def test_parse_plain_subscription():
    profiles = importer.parse_subscription(f"{SAMPLE}\n# comment\n")
    assert len(profiles) == 1


def test_parse_reality_params():
    link = (
        "vless://uid@example.com:443?security=reality&pbk=PUB&sid=ab&sni=www.test.com"
        "&fp=chrome&type=tcp&flow=xtls-rprx-vision#R"
    )
    p = importer.parse_vless(link)
    assert p.security == "reality"
    assert p.pbk == "PUB" and p.sid == "ab"
    assert p.sni == "www.test.com" and p.fp == "chrome"
    assert p.flow == "xtls-rprx-vision"


def test_parse_json_full_config():
    cfg = {
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {"vnext": [{"address": "1.2.3.4", "port": 443,
                                        "users": [{"id": "u", "encryption": "none"}]}]},
                "streamSettings": {"network": "ws", "security": "tls",
                                   "tlsSettings": {"serverName": "a.com"}},
            }
        ]
    }
    p = importer.parse_json(json.dumps(cfg))
    assert p.address == "1.2.3.4" and p.id == "u"
    assert p.network == "ws" and p.security == "tls" and p.sni == "a.com"
