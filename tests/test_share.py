from xrayui.core import share
from xrayui.core.importer import parse_vless, parse_wireguard
from xrayui.core.profiles import Profile


def _same(a: Profile, b: Profile) -> bool:
    ad, bd = a.to_dict(), b.to_dict()
    for key in ("uid", "sub_uid"):
        ad.pop(key, None)
        bd.pop(key, None)
    return ad == bd


def test_vless_link_round_trips_tcp_tls():
    p = Profile(
        name="My Server", protocol="vless", address="a.example.com", port=443,
        id="uid-1", encryption="none", flow="xtls-rprx-vision", network="tcp",
        security="tls", sni="a.example.com", fp="chrome", alpn="h2,http/1.1",
    )
    assert _same(parse_vless(share.share_link(p)), p)


def test_vless_link_round_trips_ws_reality():
    p = Profile(
        name="Reality server", protocol="vless", address="203.0.113.5", port=443,
        id="uid-2", network="ws", security="reality", sni="www.microsoft.com",
        fp="chrome", pbk="PUBKEY", sid="ab12", spx="/spider",
        path="/rws", host="www.microsoft.com",
    )
    assert _same(parse_vless(share.share_link(p)), p)


def test_vless_link_round_trips_grpc():
    p = Profile(
        name="gRPC server", protocol="vless", address="c.example.com", port=443,
        id="uid-3", network="grpc", security="tls", sni="c.example.com",
        service_name="grpc-svc",
    )
    assert _same(parse_vless(share.share_link(p)), p)


def test_wireguard_link_round_trips():
    p = Profile(
        name="WG server", protocol="wireguard", address="1.2.3.4", port=51820,
        id="SECRETKEY", pbk="PEERKEY", wg_local_address="10.0.0.2/32",
        wg_preshared="PSK", wg_reserved="1,2,3", wg_mtu=1280, wg_keepalive=25,
    )
    assert _same(parse_wireguard(share.share_link(p)), p)


def test_wireguard_link_round_trips_ipv6_endpoint_and_default_mtu():
    p = Profile(
        name="WG v6", protocol="wireguard", address="2606:4700:d0::a29f:c001",
        port=2408, id="S", pbk="P",
    )
    assert _same(parse_wireguard(share.share_link(p)), p)


def test_wireguard_link_round_trips_base64_keys_with_slash_plus_and_equals():
    # Real WireGuard base64 keys routinely contain '/', '+' and '='. A '/'
    # in the userinfo (before '@') ends urlsplit's netloc early if it isn't
    # percent-encoded, which broke the private key specifically.
    p = Profile(
        name="WG b64", protocol="wireguard", address="1.2.3.4", port=51820,
        id="aB/c+d1EF/GHI=", pbk="pQ+R/ST8uVW=", wg_preshared="xY/z9+AB=",
    )
    assert _same(parse_wireguard(share.share_link(p)), p)
