"""Server table: model, filter/sort proxy, and the QR dialog."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.i18n import ltr  # noqa: E402
from xrayui.ui.server_table import (  # noqa: E402
    COL_DELAY,
    COL_NAME,
    COL_SUB,
    COL_TRANSPORT,
    COL_TYPE,
    ProfileFilterProxy,
    ProfileTableModel,
    QrDialog,
)
from xrayui.ui.theme import ERR, MUTED  # noqa: E402
from xrayui.ui.widgets import ProfilePanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


A = Profile(name="Alpha", protocol="vless", address="a.example.com", port=443,
            id="u", network="ws", security="tls", uid="a", sub_uid="s1")
B = Profile(name="Beta", protocol="wireguard", address="b.example.com", port=51820,
            id="k", pbk="p", uid="b")
C = Profile(name="alpine", protocol="vless", address="10.0.0.9", port=443,
            id="u", network="tcp", security="reality", uid="c")
D = Profile(name="WARP", protocol="wireguard", address="d.example.com", port=51820,
            id="k", pbk="p", uid="d")


def test_model_rows_and_columns(qapp):
    model = ProfileTableModel()
    model.set_profiles([A, B], "a")
    model.set_sub_names({"s1": "My Sub"})
    model.set_results({"a": {"delay_ms": 42.0, "error": None},
                        "b": {"delay_ms": None, "error": "unreachable"}})

    assert model.rowCount() == 2
    assert model.columnCount() == len(["", "Name", "Type", "Transport", "Subscription", "Delay"])

    idx = model.index
    assert model.data(idx(0, 0), Qt.DisplayRole) == "●"  # A is active
    assert model.data(idx(1, 0), Qt.DisplayRole) == ""
    assert model.data(idx(0, COL_NAME), Qt.DisplayRole) == "Alpha"
    assert model.data(idx(0, COL_TYPE), Qt.DisplayRole) == "vless"
    assert model.data(idx(0, COL_TRANSPORT), Qt.DisplayRole) == "ws/tls"
    assert model.data(idx(1, COL_TRANSPORT), Qt.DisplayRole) == "wg"  # wireguard
    assert model.data(idx(0, COL_SUB), Qt.DisplayRole) == "My Sub"
    assert model.data(idx(1, COL_SUB), Qt.DisplayRole) == "—"
    # The delay is an isolated LTR run so "42 ms" can't reorder inside RTL.
    assert model.data(idx(0, COL_DELAY), Qt.DisplayRole) == ltr("42 ms")
    # A failure shows a short word in the cell; the full error is the tooltip.
    assert model.data(idx(1, COL_DELAY), Qt.DisplayRole) == "Failed"
    assert model.data(idx(1, COL_DELAY), Qt.ToolTipRole) == "unreachable"
    assert model.data(idx(0, COL_DELAY), Qt.ToolTipRole) is None


def test_skipped_shows_muted_na_with_reason_in_tooltip(qapp):
    model = ProfileTableModel()
    model.set_profiles([A, B], "a")
    model.set_results({
        "a": {"delay_ms": None, "error": "unreachable", "skipped": False},
        "b": {"delay_ms": None, "error": "n/a (UDP)", "skipped": True},
    })
    idx = model.index
    assert model.data(idx(0, COL_DELAY), Qt.DisplayRole) == "Failed"
    assert model.data(idx(1, COL_DELAY), Qt.DisplayRole) == "n/a"
    assert model.data(idx(1, COL_DELAY), Qt.ToolTipRole) == "n/a (UDP)"
    assert model.data(idx(0, COL_DELAY), Qt.ForegroundRole) == QColor(ERR)
    assert model.data(idx(1, COL_DELAY), Qt.ForegroundRole) == QColor(MUTED)


def test_set_active_uid_moves_the_marker_without_a_reset(qapp):
    model = ProfileTableModel()
    model.set_profiles([A, B], "a")
    resets = []
    model.modelAboutToBeReset.connect(lambda: resets.append(1))

    model.set_active_uid("b")

    assert resets == []
    idx = model.index
    assert model.data(idx(0, 0), Qt.DisplayRole) == ""
    assert model.data(idx(1, 0), Qt.DisplayRole) == "●"


def test_set_results_and_set_sub_names_do_not_reset_the_model(qapp):
    # _reload_profiles() calls these before set_profiles(); a reset here
    # would clear the view's selection before set_profiles ever gets a
    # chance to preserve it (see main_window's Reconnect-now fix).
    model = ProfileTableModel()
    model.set_profiles([A, B], "a")
    resets = []
    model.modelAboutToBeReset.connect(lambda: resets.append(1))

    model.set_results({"a": {"delay_ms": 12.0, "error": None}})
    model.set_sub_names({"s1": "My Sub"})

    assert resets == []
    assert model.data(model.index(0, COL_DELAY), Qt.DisplayRole) == ltr("12 ms")
    assert model.data(model.index(0, COL_SUB), Qt.DisplayRole) == "My Sub"


def test_filter_matches_name_or_address(qapp):
    model = ProfileTableModel()
    model.set_profiles([A, B, C], None)
    proxy = ProfileFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_needle("alp")  # matches both "Alpha" (name) and "alpine" (name)
    assert proxy.rowCount() == 2

    proxy.set_needle("10.0.0.9")  # matches C's address only
    assert proxy.rowCount() == 1
    assert model.profile_at(proxy.mapToSource(proxy.index(0, 0)).row()).uid == "c"

    proxy.set_needle("")
    assert proxy.rowCount() == 3


def test_delay_sort_puts_failures_and_untested_last(qapp):
    model = ProfileTableModel()
    model.set_profiles([A, B, C], None)
    model.set_results({
        "a": {"delay_ms": 200.0, "error": None},
        "b": {"delay_ms": None, "error": "unreachable"},
        # "c" has no entry at all: untested
    })
    proxy = ProfileFilterProxy()
    proxy.setSourceModel(model)
    proxy.sort(COL_DELAY, Qt.AscendingOrder)

    ordered = [model.profile_at(proxy.mapToSource(proxy.index(r, 0)).row()).uid
               for r in range(proxy.rowCount())]
    assert ordered[0] == "a"  # the only one with a real delay
    assert set(ordered[1:]) == {"b", "c"}  # failed/untested, order between them unspecified


def test_update_result_changes_just_that_row(qapp):
    model = ProfileTableModel()
    model.set_profiles([A, B], "a")
    seen = []
    model.dataChanged.connect(lambda tl, br, roles=None: seen.append((tl.row(), br.row())))

    model.update_result("b", 15.0, None)

    assert seen == [(1, 1)]
    assert model.data(model.index(1, COL_DELAY), Qt.DisplayRole) == ltr("15 ms")
    assert model.data(model.index(0, COL_DELAY), Qt.DisplayRole) == "—"


def test_fastest_uid_ignores_failures_untested_and_skipped(qapp):
    model = ProfileTableModel()
    model.set_profiles([A, B, C, D], None)
    model.set_results({
        "a": {"delay_ms": 500.0, "error": None},
        "b": {"delay_ms": None, "error": "unreachable"},
        "c": {"delay_ms": 90.0, "error": None},
        "d": {"delay_ms": None, "error": "n/a (UDP)", "skipped": True},
    })
    assert model.fastest_uid() == "c"


def test_qr_dialog_opens_with_a_non_null_pixmap(qapp):
    dlg = QrDialog("Alpha", "vless://uuid@a.example.com:443?type=ws#Alpha")
    assert not dlg.image_label.pixmap().isNull()


# -- ProfilePanel widget -----------------------------------------------------
def _select_rows(panel, *rows) -> None:
    sel_model = panel.table.selectionModel()
    flags = QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
    for row in rows:
        sel_model.select(panel.proxy.index(row, 0), flags)
        flags = QItemSelectionModel.Select | QItemSelectionModel.Rows


def test_ctrl_select_reaches_two_rows_and_leaves_the_active_marker_alone(qapp):
    panel = ProfilePanel()
    panel.set_profiles([A, B, C], "a")

    _select_rows(panel, 0)  # a single click: activates row 0
    assert panel.selected_uids() == ["a"]

    _select_rows(panel, 0, 1)  # Ctrl-click adds row 1
    assert set(panel.selected_uids()) == {"a", "b"}
    # The marker still reflects whichever uid was last actually activated,
    # not whatever `current_uid()` happens to be after extending a selection.
    assert panel.model.data(panel.model.index(0, 0)) == "●"


def test_activated_only_fires_for_a_single_selected_row(qapp):
    panel = ProfilePanel()
    panel.set_profiles([A, B, C], None)
    fired = []
    panel.activated.connect(fired.append)

    _select_rows(panel, 0)
    assert fired == ["a"]

    fired.clear()
    _select_rows(panel, 0, 1)
    assert fired == []  # two rows selected now: no activation


def test_set_active_does_not_disturb_a_multi_selection(qapp):
    panel = ProfilePanel()
    panel.set_profiles([A, B, C], "a")
    _select_rows(panel, 0, 1)
    assert len(panel.selected_uids()) == 2

    panel.set_active("c")  # e.g. MainWindow after Use fastest picks a 3rd server

    assert len(panel.selected_uids()) == 2
    assert panel.model.data(panel.model.index(2, 0)) == "●"


def test_reload_keeps_a_multi_selection_when_the_rows_still_exist(qapp):
    panel = ProfilePanel()
    profiles = [A, B, C]
    panel.set_profiles(profiles, "a")
    _select_rows(panel, 0, 1)
    assert len(panel.selected_uids()) == 2

    panel.set_profiles(profiles, "a")  # e.g. MainWindow's _reload_profiles

    assert set(panel.selected_uids()) == {"a", "b"}


def _render(panel, width: int) -> None:
    panel.resize(width, 400)
    panel.show()
    QApplication.processEvents()
    QApplication.processEvents()


def test_delay_column_fits_inside_a_320px_panel(qapp):
    panel = ProfilePanel()
    panel.set_profiles([A, B, C], "a")
    panel.set_results({"a": {"delay_ms": 84.0, "error": None}})
    _render(panel, 320)
    try:
        left = panel.table.columnViewportPosition(COL_DELAY)
        width = panel.table.columnWidth(COL_DELAY)
        assert left >= 0
        assert left + width <= panel.table.viewport().width()
    finally:
        panel.close()


def test_type_and_subscription_hidden_by_default_transport_is_not(qapp):
    panel = ProfilePanel()
    assert panel.table.isColumnHidden(COL_TYPE)
    assert panel.table.isColumnHidden(COL_SUB)
    assert not panel.table.isColumnHidden(COL_TRANSPORT)


def test_header_menu_toggles_an_optional_column(qapp):
    panel = ProfilePanel()
    menu = panel._build_header_menu()
    action = next(a for a in menu.actions() if a.text() == "Transport")
    assert action.isChecked()

    action.trigger()
    assert panel.table.isColumnHidden(COL_TRANSPORT)

    action.trigger()
    assert not panel.table.isColumnHidden(COL_TRANSPORT)


def test_table_starts_unsorted(qapp):
    panel = ProfilePanel()
    assert panel.table.horizontalHeader().sortIndicatorSection() == -1


def test_more_menu_actions_fire_their_signals(qapp):
    panel = ProfilePanel()
    fired: list[str] = []
    panel.removeFailedRequested.connect(lambda: fired.append("failed"))
    panel.removeDuplicatesRequested.connect(lambda: fired.append("dups"))
    actions = panel.btn_more.menu().actions()
    assert [a.text() for a in actions] == ["Remove failed", "Remove duplicates"]
    for action in actions:
        action.trigger()  # SignalInstance is not callable: must fire via lambda
    assert fired == ["failed", "dups"]
