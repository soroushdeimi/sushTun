import sys
import time

from xrayui.core import metrics


def test_macos_throughput_early_exit_if_no_device(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(metrics, "IS_MAC", True)

    monkeypatch.setattr(metrics, "_mac_counters", lambda dev: None)

    start = time.perf_counter()
    res = metrics._mac_throughput(5)
    elapsed = time.perf_counter() - start

    assert res is None
    assert elapsed < 1.0

def test_macos_baseline_sample(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(metrics, "IS_MAC", True)

    # baseline_sample should return None on macOS
    res = metrics.baseline_sample(1, "en0")
    assert res is None
