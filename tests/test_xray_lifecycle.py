"""Child handles remain authoritative even when orphan discovery misses."""
from unittest.mock import Mock

import pytest

from xrayui.core import xray


@pytest.mark.parametrize("windows", [True, False])
def test_stop_kills_child_before_orphan_sweep(monkeypatch, windows):
    monkeypatch.setattr(xray, "IS_WIN", windows)
    events = []
    child = Mock(pid=1234)
    child.poll.return_value = None
    child.kill.side_effect = lambda: events.append("child")
    monkeypatch.setattr(xray.proc, "run", lambda *a, **k: events.append(a[0]))
    monkeypatch.setattr(xray, "_kill_all", lambda: events.append("sweep"))
    process = xray.XrayProcess()
    process._proc = child
    process.stop()
    assert events == ([['taskkill', '/f', '/t', '/pid', '1234'], "sweep"]
                      if windows else ["child", "sweep"])
    child.wait.assert_called_once_with(timeout=3)
    assert not process.is_running()


def test_start_spawn_failure_writes_error_to_log(monkeypatch, tmp_path):
    log_file = tmp_path / "xray.log"
    monkeypatch.setattr(xray.paths, "log_file", lambda: log_file)
    monkeypatch.setattr(xray.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(xray.paths, "asset_dir", lambda: tmp_path)
    monkeypatch.setattr(xray, "_kill_all", lambda: None)

    def fail_popen(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(xray.subprocess, "Popen", fail_popen)

    process = xray.XrayProcess()
    with pytest.raises(PermissionError, match="Permission denied"):
        process.start(tmp_path / "cfg.json")

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Failed to start Xray: [Errno 13] Permission denied" in content


def test_process_exit_without_output_records_exit_code_in_log(monkeypatch, tmp_path):
    log_file = tmp_path / "xray.log"
    monkeypatch.setattr(xray.paths, "log_file", lambda: log_file)

    child = Mock(pid=1234)
    child.poll.return_value = 1

    process = xray.XrayProcess()
    process._proc = child
    process._log = open(log_file, "w", encoding="utf-8")

    assert not process.is_running()
    content = log_file.read_text(encoding="utf-8")
    assert "Xray process exited with code 1" in content
    process.stop()


def test_process_killed_by_signal_records_signal_in_log(monkeypatch, tmp_path):
    log_file = tmp_path / "xray.log"
    monkeypatch.setattr(xray.paths, "log_file", lambda: log_file)

    child = Mock(pid=1234)
    child.poll.return_value = -11

    process = xray.XrayProcess()
    process._proc = child
    process._log = open(log_file, "w", encoding="utf-8")

    assert not process.is_running()
    content = log_file.read_text(encoding="utf-8")
    assert "Xray process killed by signal 11" in content
    process.stop()


def test_process_exit_with_existing_output_preserves_output(monkeypatch, tmp_path):
    log_file = tmp_path / "xray.log"
    monkeypatch.setattr(xray.paths, "log_file", lambda: log_file)

    child = Mock(pid=1234)
    child.poll.return_value = 1

    process = xray.XrayProcess()
    process._proc = child
    process._log = open(log_file, "w", encoding="utf-8")
    process._log.write("Failed to start: address already in use\n")
    process._log.flush()

    assert not process.is_running()
    content = log_file.read_text(encoding="utf-8")
    assert "Failed to start: address already in use" in content
    assert "Xray process exited with code" not in content
    process.stop()


