"""Guards for the sidebar window's scoped styles and the RTL popup text."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui.ui.mac import PopupButton  # noqa: E402
from xrayui.ui.sidebar import Sidebar  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_sidebar_stylesheet_is_scoped(qapp):
    sb = Sidebar()
    assert sb.styleSheet().lstrip().startswith("QFrame#Sidebar{")


def test_toolbar_stylesheet_is_scoped(qapp, tmp_path, monkeypatch):
    from xrayui import paths
    from xrayui.ui.main_window import MainWindow
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    win = MainWindow(elevated=False)
    try:
        assert win.toolbar.styleSheet().lstrip().startswith("QWidget#Toolbar{")
        assert win.toolbar.title.styleSheet().find("border") == -1
    finally:
        win.close()


def test_popup_text_positions_ltr_label_first_from_the_left():
    label_x, value_x = PopupButton._text_positions(200, 60, 40, rtl=False)
    assert label_x == 10
    assert value_x == 70


def test_popup_text_positions_rtl_label_first_from_the_right():
    label_x, value_x = PopupButton._text_positions(200, 60, 40, rtl=True)
    # label ends at the right padding, value sits to its left
    assert label_x + 60 == 190
    assert value_x + 40 == label_x


@pytest.mark.parametrize("lang", ["en", "fa"])
def test_main_window_fits_820x560_on_every_page(qapp, tmp_path, monkeypatch, lang):
    from xrayui import paths
    from xrayui.i18n import set_language
    from xrayui.ui.main_window import MainWindow
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    set_language(lang)
    win = MainWindow(elevated=False)
    try:
        assert win.minimumSizeHint().height() <= 560
        assert win.minimumSizeHint().width() <= 820
        win.resize(820, 560)
        win.show()
        qapp.processEvents()
        assert (win.width(), win.height()) == (820, 560)
        for index in range(5):
            win._show_page(index)
            qapp.processEvents()
            assert win._stack.currentIndex() == index
            assert win.height() == 560
    finally:
        win.close()
        set_language("en")


def test_dirty_routing_page_is_found_behind_its_scroll_area(qapp, tmp_path, monkeypatch):
    from xrayui import paths
    from xrayui.i18n import set_language
    from xrayui.ui import main_window as mw
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    win = mw.MainWindow(elevated=False)
    try:
        win._show_page(2)
        monkeypatch.setattr(win._routing_page, "is_dirty", lambda: True)
        asked = []
        monkeypatch.setattr(mw, "confirm_leave",
                            lambda page, parent: asked.append(page) or False)
        win._show_page(0)
        assert asked == [win._routing_page]
        assert win._stack.currentIndex() == 2
    finally:
        win.close()
        set_language("en")

def test_servers_page_is_the_finished_page(qapp, tmp_path, monkeypatch):
    from xrayui import paths
    from xrayui.ui.main_window import MainWindow
    from xrayui.ui.pages.servers_page import ServersPage
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    win = MainWindow(elevated=False)
    try:
        assert isinstance(win._stack.widget(0), ServersPage)
        assert win.status_card is win.servers_page.header
        assert win.profiles is win.servers_page.core
        assert win.btn_connect is win.servers_page.header.btn_connect
        win.show()
        assert not win.profiles.filter_edit.isVisible()
        assert win.servers_page.more_btn.toolTip()
    finally:
        win.close()


def test_settings_item_opens_the_settings_window(qapp, tmp_path, monkeypatch):
    from xrayui import paths
    from xrayui.ui import main_window as mw
    from xrayui.ui.settings_window import SettingsWindow
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    opened = []

    class Probe(SettingsWindow):
        def exec(self):
            opened.append(self)
            self._pages["general"].tun_mtu.setValue(1380)
            return 1

    monkeypatch.setattr(mw, "SettingsWindow", Probe)
    monkeypatch.setattr(mw.app_settings, "save", lambda settings: None)
    win = mw.MainWindow(elevated=False)
    try:
        win.sidebar.settingsRequested.emit()
        assert len(opened) == 1
        assert win.settings["tun_mtu"] == 1380
    finally:
        win.close()


def test_subscriptions_use_the_finished_page_and_sidebar_list(qapp, tmp_path, monkeypatch):
    from xrayui import paths
    from xrayui.core.subscription import Subscription
    from xrayui.ui.main_window import PAGE_SUBS, MainWindow
    from xrayui.ui.pages.subscriptions_page import (
        SidebarSubscriptionList,
        SubscriptionsPage,
        _SidebarSubRow,
    )
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    win = MainWindow(elevated=False)
    try:
        assert isinstance(win.subs_panel, SubscriptionsPage)
        assert isinstance(win.sidebar.sub_list_host, SidebarSubscriptionList)
        win.subs.save(Subscription(name="Main plan", url="https://sub.example/x"))
        win._reload_subs()
        rows = win.sidebar_subs.findChildren(_SidebarSubRow)
        assert len(rows) == 1
        rows[0].activated.emit(rows[0].uid)
        assert win._stack.currentIndex() == PAGE_SUBS
    finally:
        win.close()


def test_activity_uses_the_finished_page_and_runs_diagnostics(qapp, tmp_path, monkeypatch):
    from xrayui import paths
    from xrayui.ui.main_window import PAGE_ACTIVITY, MainWindow
    from xrayui.ui.pages.activity_page import ActivityPage
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    win = MainWindow(elevated=False)
    try:
        assert isinstance(win._stack.widget(PAGE_ACTIVITY), ActivityPage)
        assert win.tools is win.activity_page.tools
        assert win.log is win.activity_page.log
        monkeypatch.setattr(win, "_diag_fn", lambda: "diag report")
        monkeypatch.setattr(win, "_run_async", lambda fn, done: done(result=fn()))
        win.activity_page.diagnostics.runRequested.emit()
        assert win.activity_page.diagnostics.output.toPlainText() == "diag report"
    finally:
        win.close()


def test_sidebar_rows_are_clear_and_pinned_to_the_bottom(qapp, tmp_path, monkeypatch):
    from xrayui import paths
    from xrayui.ui.main_window import MainWindow
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    win = MainWindow(elevated=False)
    try:
        win.resize(1040, 700)
        win.show()
        qapp.processEvents()
        sb = win.sidebar
        assert "QFrame#Sidebar QWidget{background:transparent;}" in sb.styleSheet()
        # Settings sits at the very bottom of the sidebar, not under the list.
        bottom = sb._settings_row.geometry().bottom()
        assert sb.height() - bottom < 40, (sb.height(), bottom)
        # Every toolbar control shares the routing popup's height.
        tb = win.toolbar
        heights = {tb.btn_fragment.height(), tb.btn_low.height(), tb.filter_edit.height()}
        assert heights == {26}, heights
    finally:
        win.close()


def test_button_rows_are_level_and_the_lights_stay_close(qapp, tmp_path, monkeypatch,
                                                         flush_widgets):
    from PySide6.QtWidgets import QPushButton

    from xrayui import paths
    from xrayui.ui import theme
    from xrayui.ui.main_window import MainWindow
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    old = qapp.styleSheet()
    flush_widgets()
    qapp.setStyleSheet(theme.STYLESHEET)
    win = MainWindow(elevated=False)
    try:
        win.resize(1040, 700)
        win.show()
        qapp.processEvents()
        page = win.servers_page
        row = (page.core.btn_import, page.core.btn_test, page.core.btn_fastest, page.more_btn)
        assert len({w.height() for w in row}) == 1, [w.height() for w in row]
        header = win.status_card
        assert header.btn_more.height() == header.btn_connect.height()
        # A primary button is the same height as a plain one next to it.
        plain, primary = QPushButton("Cancel"), QPushButton("Done")
        primary.setObjectName("Primary")
        assert plain.sizeHint().height() == primary.sizeHint().height()
        if win.titlebar is not None:
            lights = win.titlebar.lights.lights
            gaps = [lights[i + 1].x() - (lights[i].x() + lights[i].width()) for i in range(2)]
            assert gaps == [8, 8], gaps
        assert "_arrow_down.svg" in theme.STYLESHEET
    finally:
        win.close()
        flush_widgets()
        qapp.setStyleSheet(old)
