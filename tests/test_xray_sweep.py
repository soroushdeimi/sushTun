"""Sweep crash orphans once on connect, without redundant retry queries."""
from unittest.mock import Mock

from xrayui.core import xray


def test_repeated_stop_skips_redundant_sweep_but_next_connect_sweeps(monkeypatch, tmp_path):
    sweep = Mock()
    monkeypatch.setattr(xray, "_kill_all", sweep)
    monkeypatch.setattr(xray.paths, "log_file", lambda: tmp_path / "xray.log")
    child = Mock()
    child.poll.return_value = 0
    monkeypatch.setattr(xray.subprocess, "Popen", lambda *a, **k: child)
    process = xray.XrayProcess()
    process.start(tmp_path / "config.json")
    assert sweep.call_count == 1
    process.stop()
    assert sweep.call_count == 2
    process.stop()
    assert sweep.call_count == 2
    process.start(tmp_path / "config.json")
    assert sweep.call_count == 3
    process.stop()


def test_restart_of_known_child_does_not_repeat_orphan_discovery(monkeypatch, tmp_path):
    sweep = Mock()
    monkeypatch.setattr(xray, "_kill_all", sweep)
    monkeypatch.setattr(xray.paths, "log_file", lambda: tmp_path / "xray.log")
    child = Mock()
    child.poll.return_value = 1  # an optional inbound failed to bind
    monkeypatch.setattr(xray.subprocess, "Popen", lambda *a, **k: child)
    process = xray.XrayProcess()
    process.start(tmp_path / "config.json")
    process.start(tmp_path / "config.json")
    assert sweep.call_count == 1
    process.stop()
    assert sweep.call_count == 2
