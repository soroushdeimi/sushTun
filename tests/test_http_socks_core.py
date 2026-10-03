import json

import pytest

from xrayui.core import chains, connection, outbounds, render, speedtest, xraycheck
from xrayui.core.chains import Chain, resolve
from xrayui.core.profiles import Profile


def test_profile_is_valid_http_socks():
    p = Profile(protocol="http", address="1.2.3.4", port=8080, security="none")
    assert p.is_valid()

    p.security = "tls"
    assert p.is_valid()

    p.security = ""
    assert p.is_valid()

    p.security = "reality"
    assert not p.is_valid()

    p = Profile(protocol="socks", address="1.2.3.4", port=1080, security="none")
    assert p.is_valid()

    p.security = ""
    assert p.is_valid()

    p.security = "tls"
    assert not p.is_valid()

    p = Profile(protocol="http", address="", port=8080)
    assert not p.is_valid()

    p = Profile(protocol="http", address="1.2.3.4", port=0)
    assert not p.is_valid()

    p = Profile(protocol="http", address="1.2.3.4", port=65536)
    assert not p.is_valid()

    # bool is rejected for port
    p = Profile(protocol="http", address="1.2.3.4", port=True)
    assert not p.is_valid()

def test_profile_from_dict_username():
    # old profile dict without username
    old_data = {"protocol": "http", "address": "1.2.3.4", "port": 8080, "id": "pass"}
    p = Profile.from_dict(old_data)
    assert p.username == ""
    assert p.id == "pass"

    # new profile dict with username
    new_data = {"protocol": "http", "address": "1.2.3.4", "port": 8080, "username": "user", "id": "pass"}
    p = Profile.from_dict(new_data)
    assert p.username == "user"
    assert p.id == "pass"

    # round trip
    p_dict = p.to_dict()
    assert p_dict["username"] == "user"
    assert p_dict["id"] == "pass"

def test_builders_http_socks():
    p = Profile(protocol="http", address="1.1.1.1", port=8080)
    b = outbounds.build(p, "test")
    assert b["protocol"] == "http"
    assert b["settings"] == {"address": "1.1.1.1", "port": 8080}
    assert b["streamSettings"] == {
        "network": "tcp", "security": "none", "sockopt": {"interface": "__IFACE__"}
    }

    p = Profile(protocol="http", address="1.1.1.1", port=8080, username="user", id="pass")
    b = outbounds.build(p, "test")
    assert b["settings"] == {"address": "1.1.1.1", "port": 8080, "user": "user", "pass": "pass"}

    p = Profile(protocol="http", address="1.1.1.1", port=443, security="tls", sni="example.com", alpn="h2,http/1.1", fp="chrome", allow_insecure=True)
    b = outbounds.build(p, "test")
    assert b["streamSettings"] == {
        "network": "tcp",
        "security": "tls",
        "sockopt": {"interface": "__IFACE__"},
        "tlsSettings": {"serverName": "example.com", "alpn": ["h2", "http/1.1"], "fingerprint": "chrome"}
    }

    p = Profile(protocol="socks", address="1.1.1.1", port=1080)
    b = outbounds.build(p, "test")
    assert b["protocol"] == "socks"
    assert b["settings"] == {"address": "1.1.1.1", "port": 1080}
    assert b["streamSettings"] == {
        "network": "tcp", "security": "none", "sockopt": {"interface": "__IFACE__"}
    }

    p = Profile(protocol="socks", address="1.1.1.1", port=1080, username="user", id="pass")
    b = outbounds.build(p, "test")
    assert b["settings"] == {"address": "1.1.1.1", "port": 1080, "user": "user", "pass": "pass"}

@pytest.mark.parametrize("protocol,security", [("http", "none"), ("http", "tls"),
                                             ("socks", "none")])
def test_http_socks_interface_binding(protocol, security):
    p = Profile(protocol=protocol, address="1.1.1.1", port=8080, security=security)
    proxy = outbounds.build(p, "proxy")
    assert proxy["streamSettings"]["sockopt"]["interface"] == "__IFACE__"

    cfg = json.loads(render.build_text(p, "eth0"))
    proxy = next(outbound for outbound in cfg["outbounds"] if outbound["tag"] == "proxy")
    assert proxy["streamSettings"]["sockopt"]["interface"] == "eth0"


@pytest.mark.parametrize("protocol,security", [
    ("http", "none"), ("http", "tls"), ("socks", "none"),
])
@pytest.mark.parametrize("network", ["tcp", "ws", "grpc", "httpupgrade", "xhttp", ""])
def test_http_socks_builders_force_tcp(protocol, security, network):
    p = Profile(protocol=protocol, address="example.com", port=8080,
                security=security, network=network, sni="example.com",
                path="/proxy", service_name="proxy")
    original = p.to_dict()
    stream = outbounds.build(p, "proxy")["streamSettings"]
    expected = {
        "network": "tcp", "security": security,
        "sockopt": {"interface": "__IFACE__"},
    }
    if security == "tls":
        expected["tlsSettings"] = {"serverName": "example.com"}
    assert stream == expected
    assert p.to_dict() == original


def test_render_udp_block():
    p_http = Profile(protocol="http", address="1.1.1.1", port=8080)
    cfg = json.loads(render.build_text(p_http, "eth0"))
    rules = cfg["routing"]["rules"]
    assert rules[-1] == {"type": "field", "network": "udp", "outboundTag": "block"}

    p_socks = Profile(protocol="socks", address="1.1.1.1", port=1080)
    cfg = json.loads(render.build_text(p_socks, "eth0"))
    rules = cfg["routing"]["rules"]
    assert rules[-1] != {"type": "field", "network": "udp", "outboundTag": "block"}

def test_chains_validate_accepts_http_socks():
    p1 = Profile(uid="p1", protocol="http", address="1.1.1.1", port=8080)
    p2 = Profile(uid="p2", protocol="socks", address="2.2.2.2", port=1080)
    chain = Chain(uid="c1", hops=["p1", "p2"])
    profiles = {p1.uid: p1, p2.uid: p2}
    problems = chains.validate(chain, profiles)
    assert not problems

def test_connection_accepts_passwordless_socks(monkeypatch):
    class DummyState:
        def is_connected(self): return False
        def pending(self): return {}
    conn = connection.Connection()
    conn.state = DummyState()
    # If connection.py raises ConnectError("profile is missing address or id"), this fails.
    # We mock _drain_pending_dns to just raise a different specific exception to halt the rest of connect()
    class Halt(Exception):
        pass
    monkeypatch.setattr(conn, "_drain_pending_dns", lambda *a, **kw: (_ for _ in ()).throw(Halt))
    p = Profile(protocol="socks", address="1.1.1.1", port=1080)
    with pytest.raises(Halt):
        conn.connect(p)

def test_xraycheck_http_socks_speedtest_and_chains():
    from xrayui import paths
    if not paths.xray_exe().exists():
        pytest.skip("xray executable not found")

    p_http = Profile(uid="p_http", protocol="http", address="1.1.1.1", port=8080)
    cfg_http = speedtest.build_test_config([p_http], [10000], "eth0")
    assert xraycheck.check_config(json.dumps(cfg_http)) is None

    p_socks = Profile(uid="p_socks", protocol="socks", address="1.1.1.1", port=1080)
    cfg_socks = speedtest.build_test_config([p_socks], [10001], "eth0")
    assert xraycheck.check_config(json.dumps(cfg_socks)) is None

    chain = Chain(uid="c1", hops=["p_http", "p_socks"])
    profiles = {p_http.uid: p_http, p_socks.uid: p_socks}
    resolved = resolve(chain, profiles)
    cfg_chain = render.build_text(resolved, "eth0", server_ip="1.1.1.1", include_tun=False)
    assert xraycheck.check_config(cfg_chain) is None
