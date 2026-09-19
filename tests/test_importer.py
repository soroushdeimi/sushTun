import base64
import json

import pytest

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


def test_parse_json_keeps_ws_path_and_host():
    cfg = {
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {"vnext": [{"address": "1.2.3.4", "port": 443,
                                        "users": [{"id": "u", "encryption": "none"}]}]},
                "streamSettings": {
                    "network": "ws", "security": "tls",
                    "tlsSettings": {"serverName": "a.com"},
                    "wsSettings": {"path": "/ws-path", "headers": {"Host": "a.com"}},
                },
            }
        ]
    }
    p = importer.parse_json(json.dumps(cfg))
    assert p.path == "/ws-path"
    assert p.host == "a.com"


def test_parse_json_keeps_grpc_service_name():
    cfg = {
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {"vnext": [{"address": "1.2.3.4", "port": 443,
                                        "users": [{"id": "u", "encryption": "none"}]}]},
                "streamSettings": {
                    "network": "grpc", "security": "tls",
                    "tlsSettings": {"serverName": "a.com"},
                    "grpcSettings": {"serviceName": "my-grpc-svc"},
                },
            }
        ]
    }
    p = importer.parse_json(json.dumps(cfg))
    assert p.service_name == "my-grpc-svc"


def test_parse_json_keeps_h2_path_and_hosts():
    cfg = {
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {"vnext": [{"address": "1.2.3.4", "port": 443,
                                        "users": [{"id": "u", "encryption": "none"}]}]},
                "streamSettings": {
                    "network": "h2", "security": "tls",
                    "tlsSettings": {"serverName": "a.com"},
                    "httpSettings": {"path": "/h2", "host": ["a.com", "b.com"]},
                },
            }
        ]
    }
    p = importer.parse_json(json.dumps(cfg))
    assert p.path == "/h2"
    assert p.host == "a.com,b.com"


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


def test_parse_std_vmess_link():
    link = ("vmess://11111111-1111-1111-1111-111111111111@a.example.com:443"
           "?type=ws&security=tls&sni=a.example.com&host=cdn.a.example.com"
           "&path=%2Fws&scy=none#My%20VMess")
    p = importer.parse_vmess(link)
    assert p.protocol == "vmess"
    assert p.address == "a.example.com"
    assert p.port == 443
    assert p.id == "11111111-1111-1111-1111-111111111111"
    assert p.network == "ws" and p.security == "tls"
    assert p.sni == "a.example.com" and p.host == "cdn.a.example.com" and p.path == "/ws"
    assert p.name == "My VMess"


def test_parse_base64_json_vmess_link():
    data = {"v": "2", "ps": "JsonVMess", "add": "b.example.com", "port": 443,
            "id": "uid-vmess", "scy": "auto", "net": "tcp", "tls": "", "aid": "0"}
    link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    p = importer.parse_vmess(link)
    assert p.protocol == "vmess"
    assert p.address == "b.example.com"
    assert p.id == "uid-vmess"
    assert p.vmess_security == "auto"
    assert p.network == "tcp"
    assert p.name == "JsonVMess"


def test_parse_base64_json_vmess_ignores_alterid():
    data = {"ps": "X", "add": "c.example.com", "port": 443, "id": "u",
            "net": "tcp", "aid": "64"}
    link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    p = importer.parse_vmess(link)
    assert not hasattr(p, "alter_id")
    assert "alterId" not in json.dumps(p.to_dict())


def test_parse_base64_json_vmess_grpc_maps_host_and_path():
    data = {"ps": "G", "add": "d.example.com", "port": 443, "id": "u",
            "net": "grpc", "host": "authority.d.example.com", "path": "my-svc", "tls": "tls"}
    link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    p = importer.parse_vmess(link)
    assert p.host == "authority.d.example.com"
    assert p.service_name == "my-svc"
    assert p.path == ""


def test_parse_base64_json_vmess_xhttp_type_is_mode():
    data = {"ps": "X", "add": "e.example.com", "port": 443, "id": "u",
            "net": "xhttp", "type": "packet-up", "host": "e.example.com", "path": "/xh"}
    link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    p = importer.parse_vmess(link)
    assert p.network == "xhttp"
    assert p.xhttp_mode == "packet-up"


def test_parse_vmess_rejects_non_vmess_link():
    with pytest.raises(ValueError):
        importer.parse_vmess("vless://u@a.com:443")


def test_parse_trojan_link():
    link = ("trojan://troj-pass@f.example.com:443?security=tls&sni=f.example.com"
           "&type=grpc&serviceName=trojan-svc&allowInsecure=1#Trojan1")
    p = importer.parse_trojan(link)
    assert p.protocol == "trojan"
    assert p.address == "f.example.com"
    assert p.id == "troj-pass"
    assert p.security == "tls" and p.network == "grpc"
    assert p.service_name == "trojan-svc"
    assert p.allow_insecure is True
    assert p.name == "Trojan1"


def test_parse_trojan_xhttp():
    link = ("trojan://troj-pass@g.example.com:443?security=tls&sni=g.example.com"
           "&type=xhttp&mode=stream-up&host=g.example.com&path=%2Fxh#T")
    p = importer.parse_trojan(link)
    assert p.network == "xhttp"
    assert p.xhttp_mode == "stream-up"
    assert p.host == "g.example.com" and p.path == "/xh"


def test_parse_shadowsocks_sip002():
    userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:sspass").decode().rstrip("=")
    p = importer.parse_shadowsocks(f"ss://{userinfo}@h.example.com:8388#SS1")
    assert p.protocol == "shadowsocks"
    assert p.address == "h.example.com" and p.port == 8388
    assert p.ss_method == "aes-256-gcm" and p.id == "sspass"
    assert p.name == "SS1"


def test_parse_shadowsocks_plain_2022_blake3():
    p = importer.parse_shadowsocks(
        "ss://2022-blake3-aes-256-gcm:YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=@i.example.com:8388#SS2022"
    )
    assert p.ss_method == "2022-blake3-aes-256-gcm"
    assert p.id == "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="


def test_parse_shadowsocks_legacy():
    body = base64.b64encode(b"aes-256-gcm:sspass@j.example.com:8388").decode()
    p = importer.parse_shadowsocks(f"ss://{body}#SSLegacy")
    assert p.protocol == "shadowsocks"
    assert p.address == "j.example.com" and p.port == 8388
    assert p.ss_method == "aes-256-gcm" and p.id == "sspass"
    assert p.name == "SSLegacy"


def test_parse_shadowsocks_obfs_local_http():
    userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:sspass").decode().rstrip("=")
    link = (f"ss://{userinfo}@k.example.com:8388"
           "?plugin=obfs-local%3Bobfs%3Dhttp%3Bobfs-host%3Dcdn.k.example.com#SSObfs")
    p = importer.parse_shadowsocks(link)
    assert p.network == "tcp"
    assert p.header_type == "http"
    assert p.host == "cdn.k.example.com"


def test_parse_shadowsocks_simple_obfs_typo_is_treated_as_obfs_local():
    userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:sspass").decode().rstrip("=")
    link = (f"ss://{userinfo}@k.example.com:8388"
           "?plugin=simple-obfs%3Bobfs%3Dhttp%3Bobfs-host%3Dcdn.k.example.com")
    p = importer.parse_shadowsocks(link)
    assert p.header_type == "http"


def test_parse_shadowsocks_v2ray_plugin_websocket_tls():
    userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:sspass").decode().rstrip("=")
    link = (f"ss://{userinfo}@l.example.com:8388"
           "?plugin=v2ray-plugin%3Bmode%3Dwebsocket%3Bhost%3Dcdn.l.example.com"
           "%3Bpath%3D%2Fssws%3Btls#SSv2ray")
    p = importer.parse_shadowsocks(link)
    assert p.network == "ws"
    assert p.host == "cdn.l.example.com"
    assert p.path == "/ssws"
    assert p.security == "tls"


def test_parse_shadowsocks_unknown_plugin_raises():
    userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:sspass").decode().rstrip("=")
    with pytest.raises(ValueError):
        importer.parse_shadowsocks(f"ss://{userinfo}@m.example.com:8388?plugin=mystery-plugin")


def test_share_text_skips_a_link_with_an_unknown_plugin():
    userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:sspass").decode().rstrip("=")
    bad = f"ss://{userinfo}@m.example.com:8388?plugin=mystery-plugin"
    good = f"ss://{userinfo}@n.example.com:8388#Good"
    profiles = importer.parse_share_text(f"{bad}\n{good}\n")
    assert len(profiles) == 1
    assert profiles[0].address == "n.example.com"


def test_parse_json_vmess_outbound():
    cfg = {"outbounds": [{
        "tag": "proxy", "protocol": "vmess",
        "settings": {"vnext": [{"address": "1.2.3.4", "port": 443,
                                "users": [{"id": "u", "security": "zero"}]}]},
        "streamSettings": {"network": "tcp"},
    }]}
    p = importer.parse_json(json.dumps(cfg))
    assert p.protocol == "vmess" and p.address == "1.2.3.4" and p.id == "u"
    assert p.vmess_security == "zero"


def test_parse_json_trojan_outbound():
    cfg = {"outbounds": [{
        "tag": "proxy", "protocol": "trojan",
        "settings": {"servers": [{"address": "1.2.3.4", "port": 443, "password": "pw"}]},
        "streamSettings": {"network": "ws", "security": "tls",
                           "tlsSettings": {"serverName": "a.com"},
                           "wsSettings": {"path": "/ws", "headers": {"Host": "a.com"}}},
    }]}
    p = importer.parse_json(json.dumps(cfg))
    assert p.protocol == "trojan" and p.address == "1.2.3.4" and p.id == "pw"
    assert p.network == "ws" and p.path == "/ws" and p.host == "a.com"


def test_parse_json_shadowsocks_outbound():
    cfg = {"outbounds": [{
        "tag": "proxy", "protocol": "shadowsocks",
        "settings": {"servers": [{"address": "1.2.3.4", "port": 8388,
                                  "method": "aes-256-gcm", "password": "pw"}]},
        "streamSettings": {"network": "tcp"},
    }]}
    p = importer.parse_json(json.dumps(cfg))
    assert p.protocol == "shadowsocks" and p.address == "1.2.3.4"
    assert p.ss_method == "aes-256-gcm" and p.id == "pw"


def test_parse_json_xhttp_and_new_tls_keys():
    cfg = {"outbounds": [{
        "tag": "proxy", "protocol": "vless",
        "settings": {"vnext": [{"address": "1.2.3.4", "port": 443,
                                "users": [{"id": "u", "encryption": "none"}]}]},
        "streamSettings": {
            "network": "xhttp", "security": "tls",
            "tlsSettings": {"serverName": "a.com", "echConfigList": "ECH",
                            "pinnedPeerCertSha256": "ab" * 32,
                            "verifyPeerCertByName": "a.com"},
            "xhttpSettings": {"path": "/xh", "host": "a.com", "mode": "packet-up",
                              "extra": {"headers": {"X-A": "1"}}},
        },
    }]}
    p = importer.parse_json(json.dumps(cfg))
    assert p.network == "xhttp" and p.xhttp_mode == "packet-up"
    assert p.xhttp_extra == '{"headers": {"X-A": "1"}}'
    assert p.ech == "ECH" and p.pcs == "ab" * 32 and p.vcn == "a.com"


def test_parse_json_pcs_colon_uppercase_is_normalized():
    cfg = {"outbounds": [{
        "tag": "proxy", "protocol": "vless",
        "settings": {"vnext": [{"address": "1.2.3.4", "port": 443,
                                "users": [{"id": "u", "encryption": "none"}]}]},
        "streamSettings": {
            "network": "tcp", "security": "tls",
            "tlsSettings": {"serverName": "a.com",
                            "pinnedPeerCertSha256": ":".join(["AB"] * 32)},
        },
    }]}
    p = importer.parse_json(json.dumps(cfg))
    assert p.pcs == "ab" * 32


def test_parse_json_tcp_http_header():
    cfg = {"outbounds": [{
        "tag": "proxy", "protocol": "vless",
        "settings": {"vnext": [{"address": "1.2.3.4", "port": 443,
                                "users": [{"id": "u", "encryption": "none"}]}]},
        "streamSettings": {"network": "tcp", "tcpSettings": {
            "header": {"type": "http", "request": {"path": ["/p"],
                                                    "headers": {"Host": ["a.com"]}}}}},
    }]}
    p = importer.parse_json(json.dumps(cfg))
    assert p.header_type == "http" and p.path == "/p" and p.host == "a.com"


def test_mixed_subscription_every_scheme():
    userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:sspass").decode().rstrip("=")
    vmess_data = {"ps": "V", "add": "v.example.com", "port": 443, "id": "u", "net": "tcp"}
    vmess_link = "vmess://" + base64.b64encode(json.dumps(vmess_data).encode()).decode()
    lines = [
        SAMPLE,
        vmess_link,
        "trojan://troj-pass@t.example.com:443?security=tls&sni=t.example.com#T",
        f"ss://{userinfo}@s.example.com:8388#S",
        WG_LINK,
    ]
    blob = base64.b64encode("\n".join(lines).encode()).decode()
    profiles = importer.parse_subscription(blob)
    assert [p.protocol for p in profiles] == [
        "vless", "vmess", "trojan", "shadowsocks", "wireguard",
    ]


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


# -- Profile.is_valid() filtering of junk links ------------------------------
def test_vmess_link_missing_add_is_dropped():
    data = {"ps": "X", "port": 443, "id": "u", "net": "tcp"}
    link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    assert importer.parse_share_text(link) == []
    # parse_vmess itself doesn't raise for this -- it's is_valid() that
    # catches it, at the parse_share_text/parse_json/parse_qr layer.
    assert not importer.parse_vmess(link).is_valid()


def test_vmess_link_all_null_fields_is_dropped():
    data = {"ps": None, "add": None, "port": None, "id": None, "net": None}
    link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    assert importer.parse_share_text(link) == []


def test_trojan_link_empty_password_is_dropped():
    assert importer.parse_share_text("trojan://@a.example.com:443") == []


def test_mixed_subscription_drops_junk_but_keeps_the_good_link():
    data = {"ps": "X", "port": 443, "id": "u", "net": "tcp"}  # no "add"
    bad_vmess = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
    bad_trojan = "trojan://@a.example.com:443"
    good_trojan = "trojan://pass1@b.example.com:443?security=tls&sni=b.example.com#Good"
    blob = base64.b64encode(f"{bad_vmess}\n{bad_trojan}\n{good_trojan}\n".encode()).decode()
    profiles = importer.parse_subscription(blob)
    assert len(profiles) == 1
    assert profiles[0].address == "b.example.com"


def test_parse_json_raises_for_a_config_with_no_credential():
    cfg = {"outbounds": [{
        "tag": "proxy", "protocol": "trojan",
        "settings": {"servers": [{"address": "a.example.com", "port": 443, "password": ""}]},
        "streamSettings": {"network": "tcp"},
    }]}
    with pytest.raises(ValueError):
        importer.parse_json(json.dumps(cfg))


# -- Hysteria2 ----------------------------------------------------------------
def test_parse_hysteria2_userinfo_auth():
    link = ("hysteria2://mypassword@a.example.com:443?sni=a.example.com&insecure=1"
           "&obfs=salamander&obfs-password=obfspass&mport=20000-30000&alpn=h3#HY1")
    p = importer.parse_hysteria2(link)
    assert p.protocol == "hysteria2"
    assert p.address == "a.example.com" and p.port == 443
    assert p.id == "mypassword"
    assert p.sni == "a.example.com"
    assert p.allow_insecure is True
    assert p.hy2_obfs_password == "obfspass"
    assert p.hy2_ports == "20000-30000"
    assert p.alpn == "h3"
    assert p.name == "HY1"


def test_parse_hy2_scheme_and_query_auth():
    p = importer.parse_hysteria2("hy2://b.example.com:443?auth=mypass2&sni=b.example.com#HY2")
    assert p.protocol == "hysteria2"
    assert p.address == "b.example.com"
    assert p.id == "mypass2"


def test_parse_hysteria2_pinsha256_maps_to_pcs():
    p = importer.parse_hysteria2(f"hysteria2://pw@c.example.com:443?pinSHA256={'ab' * 32}#HY3")
    assert p.pcs == "ab" * 32


def test_parse_hysteria2_pinsha256_colon_uppercase_is_normalized():
    colon_form = "%3A".join(["AB"] * 32)  # ':' url-encoded so parse_qs doesn't split it
    p = importer.parse_hysteria2(f"hysteria2://pw@c.example.com:443?pinSHA256={colon_form}#HY3")
    assert p.pcs == "ab" * 32


def test_parse_hysteria2_default_port_443():
    p = importer.parse_hysteria2("hysteria2://pw@d.example.com#HY4")
    assert p.port == 443


def test_parse_hysteria2_rejects_other_schemes():
    with pytest.raises(ValueError):
        importer.parse_hysteria2("vless://u@a.com:443")


def test_parse_json_hysteria_outbound():
    cfg = {"outbounds": [{
        "tag": "proxy", "protocol": "hysteria",
        "settings": {"address": "a.example.com", "port": 443, "version": 2},
        "streamSettings": {
            "network": "hysteria", "security": "tls",
            "tlsSettings": {"serverName": "a.example.com", "alpn": ["h3"],
                            "pinnedPeerCertSha256": "ab" * 32},
            "hysteriaSettings": {"version": 2, "auth": "hy2pass"},
            "finalmask": {
                "quicParams": {"congestion": "brutal", "brutalUp": "100mbps",
                              "brutalDown": "50mbps",
                              "udpHop": {"ports": "20000-30000", "interval": "30"}},
                "udp": [{"type": "salamander", "settings": {"password": "obfspass"}}],
            },
        },
    }]}
    p = importer.parse_json(json.dumps(cfg))
    assert p.protocol == "hysteria2"
    assert p.address == "a.example.com" and p.id == "hy2pass"
    assert p.sni == "a.example.com" and p.alpn == "h3"
    assert p.pcs == "ab" * 32
    assert p.hy2_obfs_password == "obfspass"
    assert p.hy2_ports == "20000-30000" and p.hy2_hop_interval == "30"
    assert p.hy2_up_mbps == 100 and p.hy2_down_mbps == 50


def test_mixed_subscription_includes_hysteria2():
    blob = base64.b64encode(
        f"{SAMPLE}\nhysteria2://pw@h.example.com:443?sni=h.example.com#HY\n".encode()
    ).decode()
    profiles = importer.parse_subscription(blob)
    assert [p.protocol for p in profiles] == ["vless", "hysteria2"]


def test_parse_reality_pqv_from_link_and_json():
    link = ("vless://uid@example.com:443?security=reality&pbk=PUB&sid=ab&sni=a.com"
            "&pqv=PQKEY&type=tcp#R")
    assert importer.parse_vless(link).pqv == "PQKEY"
    cfg = {"outbounds": [{
        "tag": "proxy", "protocol": "vless",
        "settings": {"vnext": [{"address": "1.2.3.4", "port": 443,
                                "users": [{"id": "u", "encryption": "none"}]}]},
        "streamSettings": {"network": "tcp", "security": "reality",
                           "realitySettings": {"serverName": "a.com", "publicKey": "PUB",
                                               "mldsa65Verify": "PQKEY"}},
    }]}
    assert importer.parse_json(json.dumps(cfg)).pqv == "PQKEY"
