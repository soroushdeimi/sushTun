"""Pages of the sidebar window: ServersPage, SubscriptionsPage,
SidebarSubscriptionList and ActivityPage -- construction, interactions,
signal plumbing and RTL-aware bits."""
from __future__ import annotations

import os
import time

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QToolButton  # noqa: E402

from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.core.subscription import Subscription, Usage  # noqa: E402
from xrayui.i18n import ltr, set_language, tr  # noqa: E402
from xrayui.ui.pages import (  # noqa: E402
    ActivityPage,
    ServersPage,
    SidebarSubscriptionList,
    SubscriptionsPage,
)
from xrayui.ui.pages.subscriptions_page import _PageSubscriptionRow, _SidebarSubRow  # noqa: E402
from xrayui.ui.theme import LINE, SUNKEN  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _english_namespace():
    set_language("en")
    yield
    set_language("en")


def _render(widget) -> QPixmap:
    pm = QPixmap(widget.size())
    widget.render(pm)
    return pm


A = Profile(name="Alpha", protocol="vless", address="a.example.com", port=443,
            id="u", network="ws", security="tls", uid="a", sub_uid="s1")
B = Profile(name="Beta", protocol="wireguard", address="b.example.com", port=51820,
            id="k", pbk="p", uid="b")
C = Profile(name="alpine", protocol="vless", address="10.0.0.9", port=443,
            id="u", network="tcp", security="reality", uid="c")


def _subs() -> list[Subscription]:
    return [
        Subscription(name="Main plan", url="https://sub.example.com/main", enabled=True,
                     usage=Usage(upload=2_000_000_000, download=78_000_000_000,
                                 total=100_000_000_000, expire=0),
                     updated=time.time()),
        Subscription(name="Old plan", url="https://sub.example.com/old", enabled=False),
    ]


def _rows(lst: SidebarSubscriptionList) -> list[_SidebarSubRow]:
    out = []
    for i in range(lst.layout().count()):
        w = lst.layout().itemAt(i).widget()
        if isinstance(w, _SidebarSubRow):
            out.append(w)
    return out


# -- ServersPage -----------------------------------------------------------
def test_servers_page_builds_and_lists_profiles(qapp):
    page = ServersPage()
    page.set_profiles([A, B, C], "a")
    assert page.core.model.rowCount() == 3
    assert page.visible_uids() == ["a", "b", "c"]
    assert page.current_uid() == "a"


def test_servers_page_activation_from_selection(qapp):
    page = ServersPage()
    page.set_profiles([A, B, C], "a")
    fired: list[str] = []
    page.activated.connect(fired.append)
    row = page.core.model.row_of_uid("b")
    page.table.selectRow(row)
    assert fired == ["b"]


def test_servers_page_table_sits_in_a_sunken_named_frame(qapp):
    page = ServersPage()
    frame = page.findChild(QFrame, "ServerTableFrame")
    assert frame is not None
    assert frame.styleSheet() == (
        f"QFrame#ServerTableFrame{{background:{SUNKEN};"
        f"border:1px solid {LINE};border-radius:10px;}}"
    )
    assert page.table.frameShape() == QFrame.NoFrame


def test_servers_page_filter_narrows_visible_uids(qapp):
    page = ServersPage()
    page.set_profiles([A, B, C], None)
    assert page.visible_uids() == ["a", "b", "c"]
    page.set_filter_text("alpine")
    qapp.processEvents()
    assert page.visible_uids() == ["c"]
    page.filter_edit.setText("alpha")
    qapp.processEvents()
    assert page.visible_uids() == ["a"]


def test_servers_page_import_button_carries_the_ellipsis(qapp):
    page = ServersPage()
    assert page.core.btn_import.text() == "Import…"
    assert page.core.btn_import.toolTip() == ""


def test_servers_page_more_button_is_an_accessible_icon_button(qapp):
    page = ServersPage()
    assert isinstance(page.more_btn, QToolButton)
    assert page.more_btn.toolTip() == tr("More server actions")
    assert page.more_btn.accessibleName() == tr("More server actions")
    assert page.more_btn.menu() is page.core.btn_more.menu()
    labels = [a.text() for a in page.more_btn.menu().actions()]
    assert labels == [tr("Remove failed"), tr("Remove duplicates")]


def test_servers_page_removals_forward_from_more_menu(qapp):
    page = ServersPage()
    fired: list[str] = []
    page.removeFailedRequested.connect(lambda: fired.append("failed"))
    page.removeDuplicatesRequested.connect(lambda: fired.append("dups"))
    actions = page.more_btn.menu().actions()
    actions[0].trigger()
    actions[1].trigger()
    assert fired == ["failed", "dups"]


def test_servers_page_test_button_menu_and_cancel(qapp):
    page = ServersPage()
    page.set_profiles([A, B, C], "a")
    real: list[list[str]] = []
    tcp: list[list[str]] = []
    page.testRealDelayRequested.connect(real.append)
    page.tcpPingRequested.connect(tcp.append)
    page.core.btn_test.click()
    assert real == [["a", "b", "c"]]
    page.core.btn_test.menu().actions()[1].trigger()
    assert tcp == [["a", "b", "c"]]

    cancelled: list[bool] = []
    page.cancelTestRequested.connect(lambda: cancelled.append(True))
    page.set_testing(True)
    assert page.core.btn_test.text() == tr("Cancel")
    page.core.btn_test.click()
    assert cancelled == [True]
    page.set_testing(False)
    assert page.core.btn_test.text() == tr("Test")


def test_servers_page_use_fastest_emits_best_uid(qapp):
    page = ServersPage()
    page.set_profiles([A, B, C], None)
    page.set_results({
        "a": {"delay_ms": 500.0, "error": None},
        "b": {"delay_ms": None, "error": "unreachable"},
        "c": {"delay_ms": 90.0, "error": None},
    })
    fired: list[str] = []
    page.useFastestRequested.connect(fired.append)
    page.core.btn_fastest.click()
    assert fired == ["c"]


def test_servers_page_intent_signals_reach_the_page(qapp):
    page = ServersPage()
    page.set_profiles([A, B, C], "a")
    counts: dict[str, int] = {}
    for name in ("importRequested", "editRequested", "duplicateRequested",
                 "deleteRequested", "deleteManyRequested", "connectRequested",
                 "disconnectRequested", "restoreNetworkRequested"):
        getattr(page, name).connect(
            lambda *_args, _nm=name: counts.__setitem__(_nm, counts.get(_nm, 0) + 1))

    page.core.btn_import.click()

    row_b = page.core.model.row_of_uid("b")
    page.table.selectRow(row_b)
    page.core._emit_current(page.editRequested)
    page.core._delete_selected([page.current_uid() or ""])

    page.header.btn_connect.click()
    page.header.btn_more.menu().actions()[0].trigger()

    assert counts["importRequested"] == 1
    assert counts["editRequested"] == 1
    assert counts["deleteRequested"] == 1
    assert counts["connectRequested"] == 1
    assert counts["restoreNetworkRequested"] == 1
    assert counts.get("disconnectRequested", 0) == 0


def test_servers_page_connection_header_state(qapp):
    page = ServersPage()
    page.set_connected(False)
    assert page.header._state.text() == tr("Disconnected")
    page.set_connected(True)
    assert page.header._state.text() == tr("Connected")
    page.set_connection("throughput", "↓ 4.2 ↑ 0.3 Mbit/s")
    assert page.header._down_up_col[1].text() == ltr("↓ 4.2 ↑ 0.3 Mbit/s")


def test_servers_page_renders(qapp):
    page = ServersPage()
    page.set_profiles([A, B, C], "a")
    page.set_results({"a": {"delay_ms": 85.0, "error": None},
                      "b": {"delay_ms": 650.0, "error": None},
                      "c": {"delay_ms": None, "error": None}})
    page.set_sub_names({"s1": "My Sub"})
    page.resize(796, 700)
    page.show()
    qapp.processEvents()
    _render(page)
    assert page.width() == 796
    page.close()


# -- SubscriptionsPage -----------------------------------------------------
def test_subscriptions_page_empty_state(qapp):
    page = SubscriptionsPage()
    assert page._empty.text() == tr("No subscriptions yet.")
    assert page._empty.isVisibleTo(page)


def test_subscriptions_page_rows_with_tooltipped_icon_buttons(qapp):
    page = SubscriptionsPage()
    page.set_subscriptions(_subs())
    rows = page.findChildren(_PageSubscriptionRow)
    assert len(rows) == 2
    tips = {tr("Edit subscription"), tr("Update now"), tr("Delete subscription")}
    for row in rows:
        row_tips = {b.toolTip() for b in row.findChildren(QToolButton)}
        assert row_tips == tips
        for b in row.findChildren(QToolButton):
            assert b.accessibleName() == b.toolTip()
            assert not b.text()  # icon-only


def test_subscriptions_page_row_buttons_emit_with_the_uid(qapp):
    page = SubscriptionsPage()
    subs = _subs()
    page.set_subscriptions(subs)
    edited: list[str] = []
    refreshed: list[str] = []
    deleted: list[str] = []
    page.editRequested.connect(edited.append)
    page.refreshRequested.connect(refreshed.append)
    page.deleteRequested.connect(deleted.append)
    rows = page.findChildren(_PageSubscriptionRow)
    for row in rows:
        for b in row.findChildren(QToolButton):
            b.click()
    assert edited == [s.uid for s in subs]
    assert refreshed == [s.uid for s in subs]
    assert deleted == [s.uid for s in subs]


def test_subscriptions_page_disabled_row_looks_muted(qapp):
    page = SubscriptionsPage()
    page.set_subscriptions(_subs())
    rows = page.findChildren(_PageSubscriptionRow)
    muted_enabled = [label.text() for label in rows[0].findChildren(QLabel, "Muted")]
    assert not any("disabled" in t for t in muted_enabled), muted_enabled
    muted_disabled = [label.text() for label in rows[1].findChildren(QLabel, "Muted")]
    assert any("disabled" in t for t in muted_disabled), muted_disabled
    # The "N GB left" fragment stays LTR-isolated in both rows.
    assert any("\u2066" in t for t in muted_enabled)
    assert any("\u2066" in t for t in muted_disabled)


def test_subscriptions_page_header_buttons(qapp):
    page = SubscriptionsPage()
    fired: list[str] = []
    page.addRequested.connect(lambda: fired.append("add"))
    page.updateAllRequested.connect(lambda: fired.append("all"))
    for b in page.findChildren(QPushButton):
        if b.text() == tr("Add"):
            b.click()
        elif b.text() == tr("Update all"):
            b.click()
    assert fired == ["all", "add"]


def test_subscriptions_page_double_click_row_edits(qapp):
    page = SubscriptionsPage()
    subs = _subs()
    page.set_subscriptions(subs)
    edited: list[str] = []
    page.editRequested.connect(edited.append)
    row = page.findChildren(_PageSubscriptionRow)[0]
    row.show()
    qapp.processEvents()
    QTest.mouseDClick(row, Qt.LeftButton)
    assert edited == [subs[0].uid]


def test_subscriptions_page_renders(qapp):
    page = SubscriptionsPage()
    page.set_subscriptions(_subs())
    page.resize(796, 700)
    page.show()
    qapp.processEvents()
    _render(page)
    page.close()


# -- SidebarSubscriptionList -----------------------------------------------
def test_sidebar_list_only_enabled_subs(qapp):
    lst = SidebarSubscriptionList()
    lst.set_subscriptions(_subs())
    rows = _rows(lst)
    assert len(rows) == 1
    names = [r.findChildren(QLabel)[0].text() for r in rows]
    assert names == ["Main plan"]


def test_sidebar_list_click_activates_the_subscription(qapp):
    lst = SidebarSubscriptionList()
    subs = _subs()
    lst.set_subscriptions(subs)
    fired: list[str] = []
    lst.activated.connect(fired.append)
    row = _rows(lst)[0]
    row.show()
    qapp.processEvents()
    QTest.mouseClick(row, Qt.LeftButton)
    assert fired == [subs[0].uid]


def test_sidebar_list_amount_is_ltr_isolated(qapp):
    lst = SidebarSubscriptionList()
    lst.set_subscriptions([_subs()[0]])
    labels = _rows(lst)[0].findChildren(QLabel)
    assert any("\u2066" in label.text() for label in labels), [x.text() for x in labels]


# -- ActivityPage ----------------------------------------------------------
def test_activity_page_tabs_switch_the_stack(qapp):
    page = ActivityPage()
    assert page.tabs.count() == 3
    assert page.tabs.tabText(0) == tr("Live log")
    assert page.tabs.tabText(1) == tr("Tools")
    assert page.tabs.tabText(2) == tr("Diagnostics")
    assert page.stack.currentIndex() == 0
    page.tabs.setCurrentIndex(2)
    qapp.processEvents()
    assert page.stack.currentIndex() == 2
    assert page.stack.currentWidget() is page.diagnostics


def test_activity_page_re_exposes_tool_signals(qapp):
    page = ActivityPage()
    fired: dict[str, bool] = {}
    for name in ("pingRequested", "delayRequested", "throughputRequested",
                 "baselineRequested", "diagnosticsRequested"):
        getattr(page, name).connect(
            lambda _name=name: fired.__setitem__(_name, True))
    names = ("pingRequested", "delayRequested", "throughputRequested",
             "baselineRequested", "diagnosticsRequested")
    for i, _name in enumerate(names):
        page.tools._buttons[i].click()
    assert fired == {name: True for name in names}


def test_activity_page_diagnostics_panel_and_both_run_buttons(qapp):
    page = ActivityPage()
    fired: list[str] = []
    page.diagnosticsRequested.connect(lambda: fired.append("run"))
    page.tools._buttons[4].click()  # Tools segment's Diagnostics button
    page.diagnostics.set_detail("tun", "utun3")
    page.diagnostics.set_detail("iface", "Ethernet")
    page.diagnostics.set_output("line 1")
    assert page.diagnostics.output.toPlainText() == "line 1"
    assert page.diagnostics._values["tun"].text() == ltr("utun3")
    run = page.diagnostics.findChild(QPushButton)
    assert run.text() == tr("Diagnostics")
    run.click()
    assert fired == ["run", "run"]


def test_activity_page_set_busy_disables_tools(qapp):
    page = ActivityPage()
    page.set_busy(True)
    assert not any(b.isEnabled() for b in page.tools._buttons)
    page.set_busy(False)
    assert all(b.isEnabled() for b in page.tools._buttons)


def test_activity_page_renders_each_segment(qapp):
    page = ActivityPage()
    page.resize(796, 700)
    page.show()
    qapp.processEvents()
    for seg in range(3):
        page.tabs.setCurrentIndex(seg)
        qapp.processEvents()
        _render(page)
    page.close()
