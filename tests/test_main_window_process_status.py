"""Status refresh must never query the process table on the UI thread."""
from types import SimpleNamespace
from unittest.mock import Mock

from xrayui.ui import main_window as ui


def window():
    w = SimpleNamespace(
        isVisible=lambda: True, isMinimized=lambda: False, tailer=SimpleNamespace(),
        conn=SimpleNamespace(is_connected=lambda: False, xray=Mock(),
                             state=SimpleNamespace(alias=None, ipv4=None, gateway=None,
                                                   tun_index=None)),
        status_card=Mock(), _active_profile=lambda: None, _show_exit_of_connected=lambda: None,
        _connected_chain=None, btn_connect=Mock(), btn_disconnect=Mock(), _busy=False,
        _refresh_status_subtitle=lambda: None, _orphan_running=False,
        _orphan_check_pending=False, _orphan_check_at=float('-inf'),
    )
    w.conn.xray.is_running.return_value = False
    w.jobs = []
    w._run_async = lambda work, done: w.jobs.append((work, done))
    return w


def test_status_query_is_background_cached_and_throttled(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(ui.time, "monotonic", lambda: now[0])
    query = Mock(return_value=True)
    monkeypatch.setattr(ui, "is_xray_running", query)
    w = window()
    ui.MainWindow._refresh_status(w)
    query.assert_not_called()
    assert len(w.jobs) == 1
    now[0] = 20
    ui.MainWindow._refresh_status(w)
    assert len(w.jobs) == 1  # even a slow query must not pile up
    work, done = w.jobs.pop()
    done(result=work())
    ui.MainWindow._refresh_status(w)
    w.status_card.set.assert_any_call("process", ui.tr("RUNNING"))
    assert not w.jobs
    now[0] = 31
    ui.MainWindow._refresh_status(w)
    assert len(w.jobs) == 1
    _, done = w.jobs.pop()
    done(result=False)
    ui.MainWindow._refresh_status(w)
    w.status_card.set.assert_any_call("process", ui.tr("STOPPED"))


def test_status_uses_child_without_discovery(monkeypatch):
    query = Mock()
    monkeypatch.setattr(ui, "is_xray_running", query)
    w = window()
    w.conn.xray.is_running.return_value = True
    ui.MainWindow._refresh_status(w)
    query.assert_not_called()
    assert not w.jobs
    w.status_card.set.assert_any_call("process", ui.tr("RUNNING"))
