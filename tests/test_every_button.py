"""Every button in the main window reaches the handler it is meant to call.

Each handler is swapped for a recorder BEFORE the window is built (the window
wires bound methods at construction), then each control is clicked for real.
A button that nothing listens to -- as Connect was in the first sidebar build --
fails here instead of silently doing nothing.
"""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.core.subscription import Subscription  # noqa: E402
from xrayui.i18n import tr  # noqa: E402
from xrayui.ui import main_window as mw  # noqa: E402

_HANDLERS = (
    "_connect", "_disconnect", "_cleanup", "_reconnect_now", "_import",
    "_start_test", "_use_fastest", "_remove_failed", "_remove_duplicates",
    "_add_sub", "_update_all_subs", "_edit_sub", "_refresh_sub", "_delete_sub",
    "_open_settings", "_toggle_fragment", "_toggle_low_usage", "_set_routing_mode",
    "_toggle_gateway", "_run_tool",
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    calls: list[str] = []
    for name in _HANDLERS:
        monkeypatch.setattr(mw.MainWindow, name,
                            lambda self, *a, _n=name, **k: calls.append(_n))
    window = mw.MainWindow(elevated=True)
    window.calls = calls
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def _clicked(win, action) -> list[str]:
    win.calls.clear()
    action()
    QApplication.processEvents()
    return list(win.calls)


def test_connection_card_buttons(win):
    header = win.status_card
    assert _clicked(win, header.btn_connect.click) == ["_connect"]
    # Disconnect is only enabled while connected, as it is in the real app.
    header.btn_disconnect.setEnabled(True)
    assert _clicked(win, header.btn_disconnect.click) == ["_disconnect"]
    assert _clicked(win, header.btn_reconnect.click) == ["_reconnect_now"]
    restore = next(a for a in header.btn_more.menu().actions() if a.text() == tr("Restore network"))
    assert _clicked(win, restore.trigger) == ["_cleanup"]


def test_toolbar_buttons(win):
    tb = win.toolbar
    assert _clicked(win, tb.btn_fragment.click) == ["_toggle_fragment"]
    assert _clicked(win, tb.btn_low.click) == ["_toggle_low_usage"]
    menu = tb.btn_routing_popup.menu()
    assert menu is not None and menu.actions()
    assert _clicked(win, menu.actions()[0].trigger) == ["_set_routing_mode"]


def test_server_page_buttons(win):
    win.store.save(Profile(name="A", address="a.example.com", port=443, id="u1"))
    win.store.save(Profile(name="B", address="b.example.com", port=443, id="u2"))
    win._reload_profiles()
    core = win.profiles
    assert _clicked(win, core.btn_import.click) == ["_import"]
    assert _clicked(win, core.btn_test.click) == ["_start_test"]
    for action in core.btn_test.menu().actions():
        assert _clicked(win, action.trigger) == ["_start_test"], action.text()
    uid = core.visible_uids()[0]
    core.update_result(uid, 42.0, None)
    assert _clicked(win, core.btn_fastest.click) == ["_use_fastest"]
    more = {a.text(): a for a in win.servers_page.more_btn.menu().actions()}
    assert _clicked(win, more[tr("Remove failed")].trigger) == ["_remove_failed"]
    assert _clicked(win, more[tr("Remove duplicates")].trigger) == ["_remove_duplicates"]


def test_subscription_page_buttons(win):
    from xrayui.ui.mac import IconButton

    page = win.subs_panel
    by_text = {b.text(): b for b in page.findChildren(QPushButton)}
    assert _clicked(win, by_text[tr("Add")].click) == ["_add_sub"]
    assert _clicked(win, by_text[tr("Update all")].click) == ["_update_all_subs"]
    win.subs.save(Subscription(name="Main", url="https://sub.example/x"))
    win._reload_subs()
    QApplication.processEvents()
    icons = {b.toolTip(): b for b in page.findChildren(IconButton)}
    assert _clicked(win, icons[tr("Edit subscription")].click) == ["_edit_sub"]
    assert _clicked(win, icons[tr("Update now")].click) == ["_refresh_sub"]
    assert _clicked(win, icons[tr("Delete subscription")].click) == ["_delete_sub"]


def test_sidebar_buttons(win):
    for index, item in enumerate(win.sidebar._nav_items):
        item.click()
        QApplication.processEvents()
        assert win._stack.currentIndex() == index
    win.sidebar._settings_row.mousePressEvent(None)
    assert "_open_settings" in win.calls
    if win.btn_gateway.isEnabled():
        assert _clicked(win, win.btn_gateway.click) == ["_toggle_gateway"]


def test_activity_tool_buttons(win):
    buttons = [b for b in win.tools.findChildren(QPushButton) if b.isVisibleTo(win.tools)]
    assert buttons
    for button in buttons:
        assert _clicked(win, button.click) == ["_run_tool"], button.text()
    run = next(b for b in win.activity_page.diagnostics.findChildren(QPushButton))
    assert _clicked(win, run.click) == ["_run_tool"]
