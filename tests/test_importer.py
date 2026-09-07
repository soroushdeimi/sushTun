import base64
import json

from xrayui.core import importer

SAMPLE = (
    "vless://11111111-1111-1111-1111-111111111111@203.0.113.10:443"
    "?encryption=mlkem768x25519plus.native.0rtt.EXAMPLE_KEY&type=tcp&security=none#Sample"
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


WG_LINK = (
    "wireguard://cCWrsuGEXF6jGYh13IXrgA2lh7eJFRGX3h1VOZrNkmE="
    "@engage.cloudflareclient.com:2408"
    "?publickey=bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
    "&address=172.16.0.2/32&reserved=1,2,3&mtu=1280&keepalive=25#WARP"
)

WG_CONF = """
[Interface]
PrivateKey = cCWrsuGEXF6jGYh13IXrgA2lh7eJFRGX3h1VOZrNkmE=
Address = 172.16.0.2/32
MTU = 1280

[Peer]
PublicKey = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=
Endpoint = engage.cloudflareclient.com:2408
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""


def test_parse_wireguard_link():
    p = importer.parse_wireguard(WG_LINK)
    assert p.protocol == "wireguard"
    assert p.address == "engage.cloudflareclient.com"
    assert p.port == 2408
    assert p.id.endswith("=")
    assert p.pbk == "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
    assert p.wg_local_address == "172.16.0.2/32"
    assert p.wg_reserved == "1,2,3"
    assert p.wg_mtu == 1280
    assert p.wg_keepalive == 25
    assert p.name == "WARP"


def test_parse_wg_conf():
    p = importer.parse_wg_conf(WG_CONF)
    assert p.protocol == "wireguard"
    assert p.address == "engage.cloudflareclient.com"
    assert p.port == 2408
    assert p.wg_local_address == "172.16.0.2/32"
    assert p.wg_mtu == 1280
    assert p.wg_keepalive == 25


def test_share_text_accepts_wireguard_and_vless():
    profiles = importer.parse_share_text(f"{SAMPLE}\n{WG_LINK}\n")
    assert [p.protocol for p in profiles] == ["vless", "wireguard"]


def test_share_text_accepts_conf():
    profiles = importer.parse_share_text(WG_CONF)
    assert len(profiles) == 1 and profiles[0].protocol == "wireguard"


def test_parse_json_wireguard_outbound():
    cfg = {
        "outbounds": [{
            "tag": "proxy",
            "protocol": "wireguard",
            "settings": {
                "secretKey": "SECRET",
                "address": ["10.0.0.2/32"],
                "peers": [{"endpoint": "1.2.3.4:51820", "publicKey": "PEER"}],
            },
        }]
    }
    p = importer.parse_json(json.dumps(cfg))
    assert p.protocol == "wireguard"
    assert p.address == "1.2.3.4" and p.port == 51820
    assert p.id == "SECRET" and p.pbk == "PEER"
    assert p.wg_local_address == "10.0.0.2/32"
