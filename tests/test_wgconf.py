import base64

from xrayui.core import wgconf
from xrayui.core.profiles import Profile

PRIV = base64.b64encode(bytes(range(32))).decode()
PUB = base64.b64encode(bytes(range(32, 64))).decode()


def _profile(**overrides) -> Profile:
    base = dict(
        protocol="wireguard",
        address="203.0.113.10",
        port=51820,
        id=PRIV,
        pbk=PUB,
        wg_local_address="10.0.0.2/32",
    )
    base.update(overrides)
    return Profile(**base)


def test_b64_to_hex_round_trip():
    raw = bytes(range(32))
    key = base64.b64encode(raw).decode()
    assert wgconf.b64_to_hex(key) == raw.hex()


def test_allowed_ips_defaults_to_full_tunnel():
    p = _profile()
    assert wgconf.allowed_ips(p) == ["0.0.0.0/0", "::/0"]
    assert wgconf.is_full_tunnel(p)


def test_allowed_ips_split_tunnel():
    p = _profile(wg_allowed_ips="192.168.1.0/24, 10.10.0.0/16")
    assert wgconf.allowed_ips(p) == ["192.168.1.0/24", "10.10.0.0/16"]
    assert not wgconf.is_full_tunnel(p)


def test_is_full_tunnel_matrix():
    assert wgconf.is_full_tunnel(_profile(wg_allowed_ips=""))
    assert wgconf.is_full_tunnel(_profile(wg_allowed_ips="0.0.0.0/0"))
    assert wgconf.is_full_tunnel(_profile(wg_allowed_ips="::/0"))
    assert wgconf.is_full_tunnel(_profile(wg_allowed_ips="192.168.1.0/24, 0.0.0.0/0"))
    assert not wgconf.is_full_tunnel(_profile(wg_allowed_ips="192.168.1.0/24"))
    assert not wgconf.is_full_tunnel(_profile(wg_allowed_ips="192.168.1.0/24, 10.0.0.0/8"))


def test_local_addresses_multi():
    p = _profile(wg_local_address="10.0.0.2/32, fd00::2/128")
    assert wgconf.local_addresses(p) == ["10.0.0.2/32", "fd00::2/128"]


def test_local_addresses_empty():
    p = _profile(wg_local_address="")
    assert wgconf.local_addresses(p) == []


def test_has_reserved():
    assert wgconf.has_reserved(_profile(wg_reserved="1,2,3"))
    assert not wgconf.has_reserved(_profile(wg_reserved=""))
    assert not wgconf.has_reserved(_profile(wg_reserved="  "))


def test_endpoint_string_bracketed_ipv6():
    p = _profile(address="2606:4700:d0::a29f:c001", port=2408)
    assert wgconf.endpoint_string(p) == "[2606:4700:d0::a29f:c001]:2408"


def test_endpoint_string_override():
    p = _profile(address="wg.example.com", port=51820)
    assert wgconf.endpoint_string(p, "203.0.113.10") == "203.0.113.10:51820"


def test_uapi_payload_contains_expected_fields():
    p = _profile(wg_preshared=PUB, wg_keepalive=25, wg_allowed_ips="192.168.1.0/24")
    payload = wgconf.uapi_payload(p, endpoint_ip="203.0.113.10")
    assert payload.startswith("set=1\n")
    assert f"private_key={wgconf.b64_to_hex(PRIV)}" in payload
    assert f"public_key={wgconf.b64_to_hex(PUB)}" in payload
    assert f"preshared_key={wgconf.b64_to_hex(PUB)}" in payload
    assert "endpoint=203.0.113.10:51820" in payload
    assert "persistent_keepalive_interval=25" in payload
    assert "allowed_ip=192.168.1.0/24" in payload
    assert payload.endswith("\n\n")


def test_uapi_payload_uses_profile_endpoint_without_override():
    p = _profile(address="203.0.113.10")
    payload = wgconf.uapi_payload(p)
    assert "endpoint=203.0.113.10:51820" in payload


def test_uapi_payload_omits_optional_fields_when_unset():
    p = _profile(wg_preshared="", wg_keepalive=0)
    payload = wgconf.uapi_payload(p, endpoint_ip="203.0.113.10")
    assert "preshared_key=" not in payload
    assert "persistent_keepalive_interval=" not in payload


def test_render_conf_round_trip_shape():
    p = _profile(wg_preshared=PUB, wg_keepalive=25, wg_mtu=1280,
                 wg_allowed_ips="192.168.1.0/24")
    text = wgconf.render_conf(p)
    assert "[Interface]" in text
    assert f"PrivateKey = {PRIV}" in text
    assert "Address = 10.0.0.2/32" in text
    assert "MTU = 1280" in text
    assert "[Peer]" in text
    assert f"PublicKey = {PUB}" in text
    assert f"PresharedKey = {PUB}" in text
    assert "Endpoint = 203.0.113.10:51820" in text
    assert "AllowedIPs = 192.168.1.0/24" in text
    assert "PersistentKeepalive = 25" in text
