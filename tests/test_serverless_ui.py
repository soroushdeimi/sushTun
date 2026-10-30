"""The Serverless toggle in the connection header and its saved setting."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHBoxLayout  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.i18n import set_language, tr  # noqa: E402
from xrayui.ui import main_window as mw  # noqa: E402
from xrayui.ui.connection_header import ConnectionHeader  # noqa: E402
from xrayui.ui.help import is_help  # noqa: E402


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
def win(qapp, datadir):
    window = mw.MainWindow(elevated=True)
    window.show()
    qapp.processEvents()
    yield window
    window.close()


@pytest.fixture
def saves(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(app_settings, "save",
                        lambda data: calls.append(dict(data["serverless"])))
    return calls


@pytest.fixture
def prompts(win, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(win.status_card, "show_reconnect", shown.append)
    return shown


def test_header_has_a_checkable_serverless_button_between_disconnect_and_more(qapp):
    header = ConnectionHeader()
    btn = header.btn_serverless
    assert btn.isCheckable()
    assert not btn.isChecked()
    assert is_help(btn.toolTip())
    row = next(lay for lay in header.findChildren(QHBoxLayout)
               if lay.indexOf(btn) >= 0)
    assert row.indexOf(header.btn_disconnect) + 1 == row.indexOf(btn)
    assert row.indexOf(btn) + 1 == row.indexOf(header.btn_more)


def test_restoring_the_state_is_silent_but_a_click_emits(qapp):
    header = ConnectionHeader()
    seen: list[bool] = []
    header.serverlessToggled.connect(seen.append)
    header.set_serverless(True)
    assert header.btn_serverless.isChecked()
    assert seen == []
    header.btn_serverless.click()
    assert seen == [False]
    header.btn_serverless.click()
    assert seen == [False, True]


def test_clicking_saves_the_setting_both_ways(win, saves):
    win.status_card.btn_serverless.click()
    assert win.settings["serverless"]["enabled"] is True
    assert [s["enabled"] for s in saves] == [True]
    win.status_card.btn_serverless.click()
    assert win.settings["serverless"]["enabled"] is False
    assert [s["enabled"] for s in saves] == [True, False]


def test_connected_toggle_asks_to_reconnect(win, saves, prompts, monkeypatch):
    monkeypatch.setattr(win.conn, "is_connected", lambda: True)
    win.status_card.btn_serverless.click()
    assert len(prompts) == 1
    assert tr("Serverless turned on") in prompts[0]
    win.status_card.btn_serverless.click()
    assert tr("Serverless turned off") in prompts[1]


def test_disconnected_toggle_shows_no_prompt(win, saves, prompts, monkeypatch):
    monkeypatch.setattr(win.conn, "is_connected", lambda: False)
    win.status_card.btn_serverless.click()
    assert prompts == []


def test_saved_setting_starts_the_button_checked(qapp, datadir):
    app_settings.save({**app_settings.load(), "serverless": {"enabled": True}})
    window = mw.MainWindow(elevated=True)
    try:
        assert window.status_card.btn_serverless.isChecked()
    finally:
        window.close()


def test_settings_default_and_round_trip(datadir):
    assert app_settings.load()["serverless"] == {"enabled": False, "skip_only_warning": False}
    app_settings.save({**app_settings.load(), "serverless": {"enabled": True}})
    assert app_settings.load()["serverless"]["enabled"] is True
