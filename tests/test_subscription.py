import time

from xrayui.core import alerts
from xrayui.core.subscription import Subscription, Usage, parse_userinfo

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
