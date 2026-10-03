import json
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core.chains import Chain, resolve
from xrayui.core.chains import validate as validate_chain
from xrayui.core.importer import parse_share_text
from xrayui.core.outbounds import build
from xrayui.core.profiles import Profile
from xrayui.core.render import build_text
from xrayui.core.share import share_link
from xrayui.core.speedtest import build_test_config
from xrayui.core.subscription import subscription_url
from xrayui.core.xraycheck import check_config

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


def test_profile_validity():
    p = Profile(protocol="http", address="a.com", port=80)
    assert p.is_valid()

    p2 = Profile(protocol="socks", address="b.com", port=1080)
    assert p2.is_valid()

    p3 = Profile(protocol="socks", address="c.com", port=1080, security="tls")
    assert not p3.is_valid()

    p4 = Profile(protocol="http", address="d.com", port=443, security="tls")
    assert p4.is_valid()


def test_profile_username_field():
    p = Profile(protocol="http", address="a", port=80, username="user", id="pass")
    assert p.username == "user"
    assert p.id == "pass"


def test_profile_from_dict_without_username():
    d = {"protocol": "http", "address": "a.com", "port": 80, "id": "pass"}
    p = Profile.from_dict(d)
    assert p.username == ""


def test_outbounds_build_http_no_auth():
    p = Profile(protocol="http", address="a.com", port=80)
    out = build(p, "proxy")
    assert out["protocol"] == "http"
    assert out["settings"] == {"address": "a.com", "port": 80}


def test_outbounds_build_http_auth():
    p = Profile(protocol="http", address="a.com", port=80, username="usr", id="pwd")
    out = build(p, "proxy")
    assert out["protocol"] == "http"
    assert out["settings"] == {"address": "a.com", "port": 80, "user": "usr", "pass": "pwd"}


def test_outbounds_build_http_tls():
    p = Profile(protocol="http", address="a.com", port=443, security="tls", sni="sni.com")
    out = build(p, "proxy")
    assert out["protocol"] == "http"
    assert out["settings"] == {"address": "a.com", "port": 443}
    assert out["streamSettings"]["network"] == "tcp"
    assert out["streamSettings"]["security"] == "tls"
    assert out["streamSettings"]["tlsSettings"]["serverName"] == "sni.com"


def test_outbounds_build_socks_no_auth():
    p = Profile(protocol="socks", address="a.com", port=1080)
    out = build(p, "proxy")
    assert out["protocol"] == "socks"
    assert out["settings"] == {"address": "a.com", "port": 1080}


def test_outbounds_build_socks_auth():
    p = Profile(protocol="socks", address="a.com", port=1080, username="u", id="p")
    out = build(p, "proxy")
    assert out["protocol"] == "socks"
    assert out["settings"] == {"address": "a.com", "port": 1080, "user": "u", "pass": "p"}


def test_importer_http_link():
    res = parse_share_text("http://a.com:80#test")
    assert len(res) == 1
    assert res[0].protocol == "http"
    assert res[0].address == "a.com"
    assert res[0].port == 80
    assert res[0].name == "test"
    assert res[0].username == ""
    assert res[0].id == ""


def test_importer_http_auth_link():
    res = parse_share_text("http://u%20ser:p%40ss@a.com:80#test")
    assert len(res) == 1
    assert res[0].protocol == "http"
    assert res[0].address == "a.com"
    assert res[0].port == 80
    assert res[0].username == "u ser"
    assert res[0].id == "p@ss"


def test_importer_https_link():
    res = parse_share_text("https://domain.com:443#test2")
    assert len(res) == 1
    assert res[0].protocol == "http"
    assert res[0].security == "tls"
    assert res[0].sni == "domain.com"
    assert res[0].address == "domain.com"
    assert res[0].port == 443
    assert res[0].name == "test2"


def test_importer_socks_links():
    for prefix in ("socks://", "socks5://", "socks5h://"):
        res = parse_share_text(f"{prefix}1.2.3.4:1080#s")
        assert len(res) == 1
        assert res[0].protocol == "socks"
        assert res[0].address == "1.2.3.4"
        assert res[0].port == 1080
        assert res[0].name == "s"


def test_importer_v2rayn_base64_auth():
    # dXNlcjpwYXNz -> user:pass
    res = parse_share_text("socks://dXNlcjpwYXNz@1.2.3.4:1080#n")
    assert len(res) == 1
    assert res[0].protocol == "socks"
    assert res[0].username == "user"
    assert res[0].id == "pass"

    res2 = parse_share_text("http://dXNlcjpwYXNz@1.2.3.4:8080#n")
    assert len(res2) == 1
    assert res2[0].protocol == "http"
    assert res2[0].username == "user"
    assert res2[0].id == "pass"


def test_importer_ipv6():
    res = parse_share_text("http://[2001:db8::1]:1080")
    assert len(res) == 1
    assert res[0].address == "2001:db8::1"
    assert res[0].port == 1080


def test_importer_invalid_ports():
    assert len(parse_share_text("http://1.2.3.4:65536")) == 0
    assert len(parse_share_text("http://1.2.3.4:0")) == 0
    assert len(parse_share_text("http://1.2.3.4:-1")) == 0
    assert len(parse_share_text("http://1.2.3.4:abc")) == 0
    assert len(parse_share_text("http://1.2.3.4:")) == 0
    assert len(parse_share_text("http://1.2.3.4")) == 0


def test_importer_subscription_vs_proxy():
    assert len(parse_share_text("https://sub.example.com/sub/abc")) == 0
    assert len(parse_share_text("https://example.com")) == 0
    assert len(parse_share_text("http://1.2.3.4:8080/x")) == 0

    res = parse_share_text("http://1.2.3.4:8080")
    assert len(res) == 1
    assert res[0].address == "1.2.3.4"
    assert res[0].port == 8080


def test_subscription_url():
    assert subscription_url("http://1.2.3.4:8080") == ""
    assert subscription_url("https://1.2.3.4:443#name") == ""
    assert subscription_url("socks://1.2.3.4:1080") == ""

    assert subscription_url("https://sub.example.com/sub/abc") == "https://sub.example.com/sub/abc"
    assert subscription_url("https://example.com") == "https://example.com"
    assert subscription_url("http://1.2.3.4:8080/x") == "http://1.2.3.4:8080/x"


def test_share_link():
    p_http = Profile(
        protocol="http", address="a.com", port=80, name="n", username="u ser", id="p@ss"
    )
    assert share_link(p_http) == "http://u%20ser:p%40ss@a.com:80#n"

    p_http_notls = Profile(protocol="http", address="a.com", port=80, name="n", username="", id="")
    assert share_link(p_http_notls) == "http://a.com:80#n"

    p_https = Profile(
        protocol="http", address="a.com", port=443, security="tls", name="n", username="u", id="p"
    )
    assert share_link(p_https) == "https://u:p@a.com:443#n"

    p_socks = Profile(
        protocol="socks", address="a.com", port=1080, name="n", username="user", id="pass"
    )
    assert share_link(p_socks) == "socks://dXNlcjpwYXNz@a.com:1080#n"

    p_socks_noauth = Profile(
        protocol="socks", address="a.com", port=1080, name="n", username="", id=""
    )
    assert share_link(p_socks_noauth) == "socks://a.com:1080#n"


def test_render_udp_block():
    p_http = Profile(protocol="http", address="a.com", port=80)
    cfg_http = json.loads(build_text(p_http, "Wi-Fi", TEMPLATE))
    last_rule = cfg_http["routing"]["rules"][-1]
    assert last_rule["type"] == "field"
    assert last_rule["network"] == "udp"
    assert last_rule["outboundTag"] == "block"

    p_socks = Profile(protocol="socks", address="a.com", port=1080)
    cfg_socks = json.loads(build_text(p_socks, "Wi-Fi", TEMPLATE))
    last_rule_socks = cfg_socks["routing"]["rules"][-1]
    assert last_rule_socks.get("network") != "udp" or last_rule_socks.get("outboundTag") != "block"


def test_chains_validate():
    p_http = Profile(protocol="http", address="a.com", port=80, uid="uid-1")
    p_socks = Profile(protocol="socks", address="b.com", port=1080, uid="uid-2")
    chain = Chain(uid="chain-1", name="c", hops=["uid-1", "uid-2"])
    assert validate_chain(chain, [p_http, p_socks]) == []


def test_xray_check(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")

    p_http = Profile(protocol="http", address="1.2.3.4", port=443, security="tls", sni="sni.com")
    p_socks = Profile(protocol="socks", address="1.2.3.4", port=1080)

    cfg1 = build_test_config([p_http], [1234], "lo")
    cfg2 = build_test_config([p_socks], [1234], "lo")
    errors = {"http-tls": check_config(json.dumps(cfg1)), "socks": check_config(json.dumps(cfg2))}
    assert errors["http-tls"] is None, errors
    assert errors["socks"] is None, errors


@pytest.mark.parametrize("protocol", ["http", "socks"])
@pytest.mark.parametrize(
    "port,valid", [(0, False), (-1, False), (65536, False), (1, True), (65535, True)]
)
def test_profile_port_bounds(protocol, port, valid):
    assert Profile(protocol=protocol, address="example.com", port=port).is_valid() is valid


@pytest.mark.parametrize("protocol", ["http", "socks"])
def test_profile_requires_address(protocol):
    assert not Profile(protocol=protocol, address="", port=1080).is_valid()
    assert Profile(protocol=protocol).username == ""


@pytest.mark.parametrize("protocol,port", [("http", 8080), ("socks", 1080)])
@pytest.mark.parametrize("username,password", [("", "unused"), ("user", ""), ("user", "pass")])
def test_complete_outbound(protocol, port, username, password):
    profile = Profile(
        protocol=protocol, address="example.com", port=port, username=username, id=password
    )
    settings = {"address": "example.com", "port": port}
    if username:
        settings.update(user=username, **{"pass": password})
    assert build(profile, "proxy") == {
        "tag": "proxy",
        "protocol": protocol,
        "settings": settings,
        "streamSettings": {
            "network": "tcp",
            "security": "none",
            "sockopt": {"interface": "__IFACE__"},
        },
    }


def test_complete_tls_outbound():
    profile = Profile(
        protocol="http",
        address="example.com",
        port=443,
        security="tls",
        sni="front.example.com",
        alpn="h2, http/1.1",
        fp="chrome",
        allow_insecure=True,
    )
    # Match the existing TLS helper: allow_insecure is retained but not emitted.
    assert build(profile, "proxy") == {
        "tag": "proxy",
        "protocol": "http",
        "settings": {"address": "example.com", "port": 443},
        "streamSettings": {
            "network": "tcp",
            "security": "tls",
            "sockopt": {"interface": "__IFACE__"},
            "tlsSettings": {
                "serverName": "front.example.com",
                "fingerprint": "chrome",
                "alpn": ["h2", "http/1.1"],
            },
        },
    }


@pytest.mark.parametrize("scheme", ["http", "https", "socks", "socks5", "socks5h"])
def test_link_credentials_ipv6_and_name(scheme):
    link = f"{scheme}://u%3Aser:p%40ss%3Aword@[2001:db8::1]:1080#My%20proxy"
    result = parse_share_text(link)
    assert len(result) == 1
    p = result[0]
    assert (p.protocol, p.address, p.port, p.username, p.id, p.name, p.network, p.security) == (
        "http" if scheme in ("http", "https") else "socks",
        "2001:db8::1",
        1080,
        "u:ser",
        "p@ss:word",
        "My proxy",
        "tcp",
        "tls" if scheme == "https" else "none",
    )
    assert p.sni == ""
    assert subscription_url(link) == ""


@pytest.mark.parametrize("scheme", ["http", "https", "socks", "socks5", "socks5h"])
@pytest.mark.parametrize("port", ["0", "-1", "65536", "abc", ""])
def test_invalid_link_ports(scheme, port):
    assert parse_share_text(f"{scheme}://example.com:{port}") == []


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize(
    "suffix,is_proxy",
    [("", True), ("/", True), ("/?token=abc", False), ("?token=abc", False), ("/sub/abc", False)],
)
def test_http_url_classification(scheme, suffix, is_proxy):
    url = f"{scheme}://example.com:8080{suffix}"
    assert len(parse_share_text(url)) == int(is_proxy)
    assert subscription_url(url) == ("" if is_proxy else url)


@pytest.mark.parametrize(
    "protocol,security", [("http", "none"), ("http", "tls"), ("socks", "none")]
)
@pytest.mark.parametrize("address", ["example.com", "2001:db8::1"])
@pytest.mark.parametrize("username,password", [("", ""), ("user", "pass"), ("user", "")])
def test_share_round_trip(protocol, security, address, username, password):
    original = Profile(
        protocol=protocol,
        security=security,
        address=address,
        port=1080,
        username=username,
        id=password,
        name="My proxy",
    )
    link = share_link(original)
    assert isinstance(link, str)
    result = parse_share_text(link)
    assert len(result) == 1
    for field in ("protocol", "security", "address", "port", "username", "id", "name", "network"):
        assert getattr(result[0], field) == getattr(original, field)


@pytest.mark.parametrize(
    "entry,exit_protocol",
    [("http", "socks"), ("socks", "http"), ("http", "http"), ("socks", "socks")],
)
def test_chain_exit_controls_udp_rule(entry, exit_protocol):
    profiles = [
        Profile(protocol=entry, address="entry.example", port=1080, uid="entry"),
        Profile(protocol=exit_protocol, address="exit.example", port=1080, uid="exit"),
    ]
    chain = Chain(uid="chain", hops=[p.uid for p in profiles])
    assert validate_chain(chain, profiles) == []
    cfg = json.loads(build_text(resolve(chain, profiles), "lo", TEMPLATE))
    rules = cfg["routing"]["rules"]
    baseline = json.loads(TEMPLATE.read_text())["routing"]["rules"]
    block = {"type": "field", "network": "udp", "outboundTag": "block"}
    assert rules == baseline + ([block] if exit_protocol == "http" else [])


@pytest.mark.parametrize("protocol", ["http", "socks"])
@pytest.mark.parametrize("network", ["ws", "grpc", "httpupgrade"])
def test_proxy_chain_requires_tcp(protocol, network):
    profiles = [
        Profile(
            protocol=protocol, address="entry.example", port=1080, network=network, uid="entry"
        ),
        Profile(protocol="socks", address="exit.example", port=1080, uid="exit"),
    ]
    assert validate_chain(Chain(hops=[p.uid for p in profiles]), profiles)
