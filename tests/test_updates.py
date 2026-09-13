"""GitHub release check: version comparison and fetch-failure handling."""
from __future__ import annotations

from xrayui.core import updates


# -- is_newer -----------------------------------------------------------------
def test_is_newer_true_for_a_higher_version():
    assert updates.is_newer("v0.2.0", "0.1.13") is True


def test_is_newer_false_for_the_same_or_older_version():
    assert updates.is_newer("v0.1.13", "0.1.13") is False
    assert updates.is_newer("v0.1.0", "0.1.13") is False


def test_is_newer_false_for_a_prerelease_or_non_numeric_tag():
    assert updates.is_newer("v0.2.0-rc1", "0.1.13") is False
    assert updates.is_newer("nightly", "0.1.13") is False
    assert updates.is_newer("", "0.1.13") is False


def test_is_newer_handles_missing_v_prefix():
    assert updates.is_newer("0.2.0", "0.1.13") is True


def test_is_newer_compares_numerically_not_lexically():
    # "0.9.0" < "0.10.0" numerically, but ">" lexically as strings.
    assert updates.is_newer("v0.10.0", "0.9.0") is True


# -- latest_release -------------------------------------------------------
def test_latest_release_returns_tag_and_url():
    def fetch():
        return {"tag_name": "v0.2.0", "html_url": "https://example.com/releases/v0.2.0"}
    result = updates.latest_release(fetch=fetch)
    assert result == ("v0.2.0", "https://example.com/releases/v0.2.0")


def test_latest_release_returns_none_on_fetch_failure():
    def fetch():
        raise TimeoutError("no network")
    assert updates.latest_release(fetch=fetch) is None


def test_latest_release_returns_none_on_malformed_response():
    assert updates.latest_release(fetch=lambda: "not a dict") is None
    assert updates.latest_release(fetch=lambda: {}) is None
    assert updates.latest_release(fetch=lambda: {"tag_name": "v1"}) is None


def test_default_fetch_sends_the_app_user_agent(monkeypatch):
    captured = {}

    class FakeResp:
        def read(self):
            return b'{"tag_name": "v1.0.0", "html_url": "https://x"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=10):
        captured["header"] = req.get_header("User-agent")
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    result = updates.latest_release()
    assert result == ("v1.0.0", "https://x")
    assert captured["header"].startswith("sushTun/")
    assert captured["url"] == updates._API_URL
