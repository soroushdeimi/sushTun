import pytest

from xrayui.core.importer import is_proxy_url, parse_http, parse_share_text, parse_socks
from xrayui.core.profiles import Profile
from xrayui.core.share import share_http, share_link, share_socks
from xrayui.core.subscription import subscription_url


def test_is_proxy_url():
    # http(s)
    assert is_proxy_url("http://1.2.3.4:8080") is True
    assert is_proxy_url("http://1.2.3.4:8080/") is True
    assert is_proxy_url("https://example.com:443") is True
    assert is_proxy_url("http://u:p@1.2.3.4:8080#name") is True

    # Not proxy urls (fall back to subscriptions)
    assert is_proxy_url("http://1.2.3.4:8080/path") is False
    assert is_proxy_url("http://1.2.3.4") is False  # Missing explicit port
    assert is_proxy_url("https://example.com") is False
    assert is_proxy_url("https://sub.example.com/sub/abc") is False
    assert is_proxy_url("http://1.2.3.4:8080/?q=1") is False

    # socks*
    assert is_proxy_url("socks://1.2.3.4:1080") is True
    assert is_proxy_url("socks5://1.2.3.4:1080") is True
    assert is_proxy_url("socks5h://1.2.3.4:1080") is True
    assert is_proxy_url("socks://1.2.3.4") is False  # missing port
    assert is_proxy_url("socks://:1080") is False  # missing host

def test_parse_http():
    p = parse_http("http://u:p@1.2.3.4:8080#my%20proxy")
    assert p.protocol == "http"
    assert p.network == "tcp"
    assert p.address == "1.2.3.4"
    assert p.port == 8080
    assert p.username == "u"
    assert p.id == "p"
    assert p.security == "none"
    assert p.name == "my proxy"

    # percent-encoded user/pass
    p2 = parse_http("http://p%40ss:w%3Aord@1.2.3.4:8080")
    assert p2.username == "p@ss"
    assert p2.id == "w:ord"
    assert p2.name == "1.2.3.4:8080"

    # https -> tls, sni
    p3 = parse_http("https://example.com:443")
    assert p3.security == "tls"
    assert p3.sni == "example.com"
    assert p3.address == "example.com"
    assert p3.port == 443

    # IP host -> no sni
    p4 = parse_http("https://1.2.3.4:443")
    assert p4.security == "tls"
    assert p4.sni == ""

    # IPv6
    p5 = parse_http("http://[2001:db8::1]:8080")
    assert p5.address == "2001:db8::1"
    assert p5.port == 8080

    # Missing port
    with pytest.raises(ValueError):
        parse_http("http://1.2.3.4")

    # Missing host
    with pytest.raises(ValueError):
        parse_http("http://:8080")

def test_parse_socks():
    p = parse_socks("socks://u:p@1.2.3.4:1080#name")
    assert p.protocol == "socks"
    assert p.network == "tcp"
    assert p.address == "1.2.3.4"
    assert p.port == 1080
    assert p.username == "u"
    assert p.id == "p"
    assert p.security == "none"
    assert p.name == "name"

    # v2rayN base64 form
    # base64("user:pass") = dXNlcjpwYXNz
    p2 = parse_socks("socks5://dXNlcjpwYXNz@1.2.3.4:1080#name")
    assert p2.username == "user"
    assert p2.id == "pass"

    # base64 without colon -> treat as username
    # base64("userpass") = dXNlcnBhc3M=
    p3 = parse_socks("socks5h://dXNlcnBhc3M=@1.2.3.4:1080")
    assert p3.username == "dXNlcnBhc3M="
    assert p3.id == ""

    with pytest.raises(ValueError):
        parse_socks("socks://1.2.3.4")

def test_parse_share_text():
    # Multi-line share text
    text = """
vless://uuid@1.2.3.4:443?type=tcp&security=none#vless
http://u:p@1.2.3.4:8080#http_proxy
https://sub.example.com/sub/abc
socks://dXNlcjpwYXNz@1.2.3.4:1080#socks_proxy
http://1.2.3.4:8080/path
    """
    profiles = parse_share_text(text)
    assert len(profiles) == 3
    assert profiles[0].protocol == "vless"
    assert profiles[1].protocol == "http"
    assert profiles[2].protocol == "socks"

def test_subscription_url():
    # Should return "" for proxy urls
    assert subscription_url("http://1.2.3.4:8080") == ""
    # Should return the url for actual subscriptions
    assert subscription_url("https://example.com/sub") == "https://example.com/sub"
    # Even single line
    assert subscription_url("https://example.com:443/sub") == "https://example.com:443/sub"

def test_share_http():
    p = Profile(
        name="http_proxy",
        protocol="http",
        address="1.2.3.4",
        port=8080,
        username="p@ss",
        id="w:ord",
        security="none"
    )
    link = share_http(p)
    assert link == "http://p%40ss:w%3Aord@1.2.3.4:8080#http_proxy"

    p_https = Profile(
        name="example.com",
        protocol="http",
        address="example.com",
        port=443,
        security="tls",
        sni="example.com"
    )
    assert share_http(p_https) == "https://example.com:443#example.com"

def test_share_socks():
    p = Profile(
        name="socks_proxy",
        protocol="socks",
        address="1.2.3.4",
        port=1080,
        username="user",
        id="pass"
    )
    link = share_socks(p)
    assert link == "socks://dXNlcjpwYXNz@1.2.3.4:1080#socks_proxy"

    p_noauth = Profile(
        name="socks_noauth",
        protocol="socks",
        address="1.2.3.4",
        port=1080
    )
    assert share_socks(p_noauth) == "socks://1.2.3.4:1080#socks_noauth"

def test_round_trip():
    original = "https://u:p@example.com:443#my%20proxy"
    p = parse_http(original)
    assert p.security == "tls"
    assert p.sni == "example.com"
    assert share_link(p) == original

    original_socks = "socks://dXNlcjpwYXNz@1.2.3.4:1080#name"
    p = parse_socks(original_socks)
    assert share_link(p) == original_socks

    # round-trip IPv6
    p_ipv6 = parse_http("http://[2001:db8::1]:8080#ipv6")
    assert share_link(p_ipv6) == "http://[2001:db8::1]:8080#ipv6"
