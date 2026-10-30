"""Connect with Serverless only: the header entry, the one-time warning, reconnect."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import serverless  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.core.geo_exit import ExitInfo  # noqa: E402
from xrayui.i18n import set_language, tr  # noqa: E402
from xrayui.ui import main_window as mw  # noqa: E402
from xrayui.ui.connection_header import ConnectionHeader  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    return tmp_path


@pytest.fixture
def win(qapp, datadir, monkeypatch):
    window = mw.MainWindow(elevated=True)
    window.show()
    qapp.processEvents()
    monkeypatch.setattr(window, "_run_async", lambda work, done: work())
    yield window
    window.close()


@pytest.fixture
def saves(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(app_settings, "save",
                        lambda data: calls.append(dict(data["serverless"])))
    return calls


@pytest.fixture
def connects(win, monkeypatch):
    seen: list = []
    monkeypatch.setattr(win.conn, "connect", seen.append)
    monkeypatch.setattr(win, "_on_conn_done", lambda *a, **k: None)
    return seen


@pytest.fixture
def asked(monkeypatch):
    calls: list = []

    def install(answer):
        monkeypatch.setattr(mw, "_ask_serverless_only",
                            lambda parent: calls.append(parent) or answer)
        return calls
    return install


def only_state(win, monkeypatch):
    # State exposes uids read-only; stand in for a live Serverless only tunnel.
    monkeypatch.setattr(win.conn, "state", SimpleNamespace(
        profile_uid=serverless.ONLY_UID, chain_uid="", is_connected=lambda: False))


def test_header_entry_sits_before_restore_and_follows_the_state(qapp):
    header = ConnectionHeader()
    actions = header.btn_more.menu().actions()
    act = header.act_serverless_only
    assert act.text() == tr("Connect with Serverless only")
    assert act.toolTip()
    assert actions.index(act) < [a.text() for a in actions].index(tr("Restore network"))
    seen: list[bool] = []
    header.serverlessOnlyRequested.connect(lambda: seen.append(True))
    act.trigger()
    assert seen == [True]
    header.set_connected(True)
    assert not act.isEnabled()
    header.set_connected(False)
    assert act.isEnabled()


def test_cancelling_the_warning_does_nothing(win, saves, connects, asked):
    calls = asked((False, False))
    win._connect_serverless_only()
    assert len(calls) == 1
    assert connects == []
    assert saves == []


def test_accepting_with_the_box_ticked_connects_and_remembers(win, saves, connects, asked):
    asked((True, True))
    active = win.store.active_uid()
    win._connect_serverless_only()
    assert len(connects) == 1
    assert serverless.is_only(connects[0])
    assert win.settings["serverless"]["skip_only_warning"] is True
    assert saves and saves[-1]["skip_only_warning"] is True
    assert win.store.active_uid() == active


def test_a_remembered_choice_skips_the_warning(win, saves, connects, asked):
    calls = asked((False, False))
    win.settings.setdefault("serverless", {})["skip_only_warning"] = True
    win._connect_serverless_only()
    assert calls == []
    assert len(connects) == 1
    assert serverless.is_only(connects[0])


def test_connected_or_busy_does_nothing(win, connects, asked, monkeypatch):
    calls = asked((True, False))
    monkeypatch.setattr(win.conn, "is_connected", lambda: True)
    win._connect_serverless_only()
    monkeypatch.setattr(win.conn, "is_connected", lambda: False)
    win._busy = True
    win._connect_serverless_only()
    assert calls == []
    assert connects == []


def test_reconnect_keeps_serverless_only(win, monkeypatch):
    order: list = []
    monkeypatch.setattr(win.conn, "disconnect", lambda: order.append("disconnect"))
    monkeypatch.setattr(win.conn, "connect", lambda p: order.append(p))
    monkeypatch.setattr(win, "_on_conn_done", lambda *a, **k: None)
    only_state(win, monkeypatch)
    win._reconnect_now()
    assert order[0] == "disconnect"
    assert len(order) == 2
    assert serverless.is_only(order[1])


def test_connected_profile_is_named_for_the_mode(win, monkeypatch):
    monkeypatch.setattr(win.conn, "is_connected", lambda: True)
    only_state(win, monkeypatch)
    profile = win._connected_profile()
    assert profile is not None
    assert profile.name == tr("Serverless only")


def test_exit_detected_stores_nothing_for_the_mode(win, monkeypatch):
    monkeypatch.setattr(win.conn, "is_connected", lambda: True)
    only_state(win, monkeypatch)
    before = [p.uid for p in win.store.list()]
    results = dict(win.results.load())
    win._on_exit_detected(serverless.ONLY_UID, ExitInfo(country="IR", ip="5.1.2.3"))
    assert [p.uid for p in win.store.list()] == before
    assert win.store.get(serverless.ONLY_UID) is None
    assert win.results.load() == results
