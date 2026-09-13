import time

import pytest

from xrayui.core import alerts, subscription
from xrayui.core.profiles import Profile, ProfileStore
from xrayui.core.subscription import Subscription, SubscriptionStore, Usage, parse_userinfo

CFG = {"data_percent": 10, "data_gb": 1.0, "expiry_days": 3}


def test_parse_userinfo():
    u = parse_userinfo("upload=100; download=200; total=1000; expire=1700000000")
    assert u.upload == 100 and u.download == 200
    assert u.total == 1000 and u.expire == 1700000000
    assert u.used == 300 and u.remaining == 700


def test_usage_properties_unknown_total():
    u = Usage()
    assert u.percent_left is None
    assert u.days_left is None
    assert u.remaining == 0


def test_alert_low_data_warning():
    u = Usage(download=95 * 10**9, total=100 * 10**9)  # 5% left
    got = alerts.evaluate(Subscription(usage=u), CFG)
    assert any(a.level == "warning" and a.key.startswith("data:") for a in got)


def test_alert_critical_data():
    u = Usage(download=99 * 10**9, total=100 * 10**9)  # 1% left
    got = alerts.evaluate(Subscription(usage=u), CFG)
    assert any(a.level == "critical" for a in got)


def test_alert_expiry():
    u = Usage(expire=int(time.time() + 2 * 86400))
    got = alerts.evaluate(Subscription(usage=u), CFG)
    assert any(a.key.startswith("exp:") and a.level == "warning" for a in got)


def test_human_bytes():
    assert alerts.human_bytes(0) == "0 B"
    assert alerts.human_bytes(1536).endswith("KB")
    assert alerts.human_bytes(2 * 1024**3).endswith("GB")


def test_throttle_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts.paths, "base_dir", lambda: tmp_path)
    t = alerts.Throttle()
    assert t.allow("k", interval=100) is True
    assert t.allow("k", interval=100) is False


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(subscription.paths, "base_dir", lambda: tmp_path)
    return ProfileStore(), SubscriptionStore()


def test_refresh_keeps_active_uid_for_a_server_that_reappears(tmp_path, monkeypatch):
    profiles, store = _setup(tmp_path, monkeypatch)
    old = profiles.save(Profile(
        name="Old name", protocol="vless", address="a.example.com", port=443, id="uid-1",
    ))
    profiles.set_active(old.uid)
    sub = Subscription(url="https://sub.example/x", profile_uids=[old.uid])

    # The subscription reparses the same server (new name, no uid yet).
    refetched = Profile(name="New name", protocol="vless", address="a.example.com",
                         port=443, id="uid-1")
    monkeypatch.setattr(subscription, "fetch", lambda url, timeout=20.0, user_agent="": (Usage(), [refetched]))

    result = subscription.refresh(sub, profiles, store)

    assert result.profile_uids == [old.uid]
    assert profiles.active_uid() == old.uid
    kept = profiles.get(old.uid)
    assert kept is not None and kept.name == "New name"
    assert [p.uid for p in profiles.list()] == [old.uid]


def test_refresh_drops_an_invalid_profile_but_keeps_the_good_one(tmp_path, monkeypatch):
    profiles, store = _setup(tmp_path, monkeypatch)
    sub = Subscription(url="https://sub.example/x", profile_uids=[])
    junk = Profile(protocol="trojan", address="a.example.com", port=443, id="")  # no password
    good = Profile(protocol="trojan", address="b.example.com", port=443, id="pw1")
    monkeypatch.setattr(subscription, "fetch", lambda url, timeout=20.0, user_agent="": (Usage(), [junk, good]))

    result = subscription.refresh(sub, profiles, store)

    kept = [profiles.get(uid) for uid in result.profile_uids]
    assert [p.address for p in kept] == ["b.example.com"]


def test_refresh_refuses_to_wipe_everything_on_an_empty_parse(tmp_path, monkeypatch):
    profiles, store = _setup(tmp_path, monkeypatch)
    old = profiles.save(Profile(protocol="vless", address="a.example.com", port=443, id="uid-1"))
    profiles.set_active(old.uid)
    sub = Subscription(url="https://sub.example/x", profile_uids=[old.uid])

    # A panel error page or an empty body: nothing parses out.
    monkeypatch.setattr(subscription, "fetch", lambda url, timeout=20.0, user_agent="": (Usage(), []))

    try:
        subscription.refresh(sub, profiles, store)
        raised = False
    except ValueError:
        raised = True

    assert raised
    assert profiles.active_uid() == old.uid
    assert profiles.get(old.uid) is not None
    assert sub.profile_uids == [old.uid]


def test_refresh_drops_a_server_that_disappeared(tmp_path, monkeypatch):
    profiles, store = _setup(tmp_path, monkeypatch)
    kept = profiles.save(Profile(protocol="vless", address="a.example.com", port=443, id="uid-1"))
    gone = profiles.save(Profile(protocol="vless", address="b.example.com", port=443, id="uid-2"))
    sub = Subscription(url="https://sub.example/x", profile_uids=[kept.uid, gone.uid])

    refetched = Profile(protocol="vless", address="a.example.com", port=443, id="uid-1")
    monkeypatch.setattr(subscription, "fetch", lambda url, timeout=20.0, user_agent="": (Usage(), [refetched]))

    subscription.refresh(sub, profiles, store)

    assert profiles.get(kept.uid) is not None
    assert profiles.get(gone.uid) is None


# -- Phase 6: enabled / auto_update_hours / name_filter / user_agent --------
def test_old_subscriptions_json_loads_with_the_new_defaults():
    old = {"url": "https://sub.example/x", "name": "Old sub", "uid": "u1",
          "usage": {}, "updated": 123.0, "profile_uids": []}
    sub = Subscription.from_dict(old)
    assert sub.enabled is True
    assert sub.auto_update_hours == 0
    assert sub.name_filter == ""
    assert sub.user_agent == ""
    # And nothing already there was disturbed.
    assert sub.name == "Old sub" and sub.updated == 123.0


def test_fetch_sends_the_subscriptions_own_user_agent(monkeypatch):
    captured = {}

    class FakeResp:
        headers = {}

        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=20.0):
        captured["header"] = req.get_header("User-agent")
        return FakeResp()

    monkeypatch.setattr(subscription.urllib.request, "urlopen", fake_urlopen)
    subscription.fetch("https://sub.example/x", user_agent="MyClient/1.0")
    assert captured["header"] == "MyClient/1.0"


def test_fetch_falls_back_to_the_default_user_agent(monkeypatch):
    captured = {}

    class FakeResp:
        headers = {}

        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=20.0):
        captured["header"] = req.get_header("User-agent")
        return FakeResp()

    monkeypatch.setattr(subscription.urllib.request, "urlopen", fake_urlopen)
    subscription.fetch("https://sub.example/x")
    assert captured["header"] == subscription.DEFAULT_USER_AGENT


def test_refresh_name_filter_keeps_only_matches_case_insensitively(tmp_path, monkeypatch):
    profiles, store = _setup(tmp_path, monkeypatch)
    sub = Subscription(url="https://sub.example/x", name_filter="germany")
    de1 = Profile(protocol="vless", address="a.example.com", port=443, id="u1", name="Germany 1")
    de2 = Profile(protocol="vless", address="b.example.com", port=443, id="u2", name="GERMANY-2")
    fr = Profile(protocol="vless", address="c.example.com", port=443, id="u3", name="France 1")
    monkeypatch.setattr(subscription, "fetch",
                        lambda url, timeout=20.0, user_agent="": (Usage(), [de1, de2, fr]))

    result = subscription.refresh(sub, profiles, store)

    kept = [profiles.get(uid) for uid in result.profile_uids]
    assert {p.address for p in kept} == {"a.example.com", "b.example.com"}


def test_refresh_invalid_regex_ignores_the_filter_and_fetches_everything(tmp_path, monkeypatch):
    profiles, store = _setup(tmp_path, monkeypatch)
    sub = Subscription(url="https://sub.example/x", name_filter="[unterminated")
    a = Profile(protocol="vless", address="a.example.com", port=443, id="u1", name="A")
    b = Profile(protocol="vless", address="b.example.com", port=443, id="u2", name="B")
    monkeypatch.setattr(subscription, "fetch",
                        lambda url, timeout=20.0, user_agent="": (Usage(), [a, b]))

    result = subscription.refresh(sub, profiles, store)

    kept = [profiles.get(uid) for uid in result.profile_uids]
    assert {p.address for p in kept} == {"a.example.com", "b.example.com"}


def test_refresh_filter_matching_nothing_keeps_old_servers_and_uids(tmp_path, monkeypatch):
    profiles, store = _setup(tmp_path, monkeypatch)
    old = profiles.save(Profile(protocol="vless", address="a.example.com", port=443,
                                id="uid-1", name="Old"))
    profiles.set_active(old.uid)
    sub = Subscription(url="https://sub.example/x", profile_uids=[old.uid],
                       name_filter="no-such-name-anywhere")
    new = Profile(protocol="vless", address="b.example.com", port=443, id="uid-2", name="New")
    monkeypatch.setattr(subscription, "fetch",
                        lambda url, timeout=20.0, user_agent="": (Usage(), [new]))

    with pytest.raises(ValueError):
        subscription.refresh(sub, profiles, store)

    assert profiles.active_uid() == old.uid
    assert profiles.get(old.uid) is not None
    assert sub.profile_uids == [old.uid]


# -- is_due -------------------------------------------------------------------
def test_is_due_disabled_sub_is_never_due():
    sub = Subscription(enabled=False, updated=0)
    assert subscription.is_due(sub, global_hours=6, now=time.time()) is False


def test_is_due_never_updated_is_due_once_interval_is_nonzero():
    sub = Subscription(enabled=True, updated=0)
    assert subscription.is_due(sub, global_hours=6, now=time.time()) is True


def test_is_due_per_sub_interval_wins_over_global():
    now = time.time()
    sub = Subscription(enabled=True, auto_update_hours=1, updated=now - 2 * 3600)
    # Per-sub says overdue (1h), global would say not yet (24h).
    assert subscription.is_due(sub, global_hours=24, now=now) is True

    sub2 = Subscription(enabled=True, auto_update_hours=24, updated=now - 2 * 3600)
    # Per-sub says not yet (24h), global would say overdue (1h).
    assert subscription.is_due(sub2, global_hours=1, now=now) is False


def test_is_due_zero_effective_hours_means_never():
    sub = Subscription(enabled=True, auto_update_hours=0, updated=0)
    assert subscription.is_due(sub, global_hours=0, now=time.time()) is False


def test_is_due_not_yet_due_with_a_recent_update():
    now = time.time()
    sub = Subscription(enabled=True, auto_update_hours=6, updated=now - 3600)
    assert subscription.is_due(sub, global_hours=6, now=now) is False
