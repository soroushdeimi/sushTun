"""Panel bodies and refresh identities; all fetches are offline."""
import base64
import io
import json
from urllib.parse import quote

import pytest

from xrayui.core import importer, subscription
from xrayui.core.profiles import Profile, ProfileStore

LINK = "vless://11111111-1111-1111-1111-111111111111@example.org:443#" + quote("تهران 🚀")


@pytest.mark.parametrize("suffix", ["", "x", "xx"])
@pytest.mark.parametrize("whitespace", ["\t", " \r\n\t"])
def test_base64_padding_ignores_all_whitespace(suffix, whitespace):
    encoded = base64.urlsafe_b64encode((LINK + suffix).encode()).decode().rstrip("=")
    wrapped = encoded[:7] + whitespace + encoded[7:]
    profiles = importer.parse_subscription(wrapped)
    assert len(profiles) == 1
    assert profiles[0].name == "تهران 🚀" + suffix


@pytest.mark.parametrize("body", ["a", "====", "@@@@", "💥", "not a subscription"])
def test_malformed_base64_is_not_a_profile(body):
    assert importer.parse_subscription(body) == []


def test_mixed_links_keep_duplicate_unicode_names():
    body = LINK + "\r\n" + "trojan://password@other.example:443#" + quote("تهران 🚀")
    profiles = importer.parse_subscription(body)
    assert [p.protocol for p in profiles] == ["vless", "trojan"]
    assert [p.name for p in profiles] == ["تهران 🚀"] * 2


def test_large_body_is_rejected_before_parsing(monkeypatch):
    class Response(io.BytesIO):
        headers = {}
    # Use a small limit to keep the regression cheap.
    monkeypatch.setattr(subscription, "MAX_BODY_BYTES", 128, raising=False)
    monkeypatch.setattr(subscription.urllib.request, "urlopen",
                        lambda *a, **k: Response((LINK + "\n").encode() * 20))
    with pytest.raises(ValueError, match="too large"):
        subscription.fetch("https://example.org/sub")


def test_duplicate_server_entries_keep_all_uids(monkeypatch, tmp_path):
    monkeypatch.setattr(subscription.paths, "base_dir", lambda: tmp_path)
    profiles = ProfileStore()
    store = subscription.SubscriptionStore()
    sub = subscription.Subscription(url="https://example.org/sub")
    def fetch(*a, **k):
        return subscription.Usage(), [importer.parse_vless(LINK), importer.parse_vless(LINK)]
    monkeypatch.setattr(subscription, "fetch", fetch)
    subscription.refresh(sub, profiles, store)
    original = list(sub.profile_uids)
    profiles.set_active(original[0])
    subscription.refresh(sub, profiles, store)
    assert sub.profile_uids == original
    assert profiles.active_uid() == original[0]
    assert profiles.get(original[0]) is not None


@pytest.mark.parametrize("wrapper", [lambda p: p, lambda p: [p]])
def test_xray_json_subscription(wrapper):
    config = {"outbounds": [{"protocol": "trojan", "settings": {
        "servers": [{"address": "example.org", "port": 443, "password": "secret"}]}}]}
    profiles = importer.parse_subscription(json.dumps(wrapper(config)))
    assert len(profiles) == 1
    assert profiles[0].address == "example.org"
    assert profiles[0].id == "secret"


@pytest.mark.parametrize("body", [
    'proxies:\n  - {name: Tehran, type: trojan, server: example.org, port: 443, password: secret}',
    json.dumps({"outbounds": [{"type": "trojan", "tag": "Tehran", "server": "example.org",
                              "server_port": 443, "password": "secret"}]}),
])
@pytest.mark.xfail(strict=True, reason=(
    "Clash and sing-box need explicit outbound conversion; treating their fields as Xray "
    "would silently lose transport and TLS options"))
def test_other_panel_config_formats(body):
    profiles = importer.parse_subscription(body)
    assert len(profiles) == 1
    assert profiles[0].address == "example.org"


def test_json_profile_body():
    profile = Profile(protocol="trojan", address="example.org", id="secret")
    assert importer.parse_subscription(json.dumps(profile.to_dict()))[0].id == "secret"


def test_base64_json_subscription():
    profile = Profile(protocol="trojan", address="example.org", id="secret")
    body = base64.b64encode(json.dumps([profile.to_dict()]).encode()).decode()
    assert importer.parse_subscription(body)[0].id == "secret"
