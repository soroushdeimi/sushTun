"""Server table: model, filter/sort proxy, and the QR dialog."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui.core.profiles import Profile  # noqa: E402
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


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


A = Profile(name="Alpha", protocol="vless", address="a.example.com", port=443,
            id="u", network="ws", security="tls", uid="a", sub_uid="s1")
B = Profile(name="Beta", protocol="wireguard", address="b.example.com", port=51820,
            id="k", pbk="p", uid="b")
C = Profile(name="alpine", protocol="vless", address="10.0.0.9", port=443,
            id="u", network="tcp", security="reality", uid="c")


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
    assert model.data(idx(1, COL_TRANSPORT), Qt.DisplayRole) == "—"  # wireguard
    assert model.data(idx(0, COL_SUB), Qt.DisplayRole) == "My Sub"
    assert model.data(idx(1, COL_SUB), Qt.DisplayRole) == "—"
    assert model.data(idx(0, COL_DELAY), Qt.DisplayRole) == "42 ms"
    # A failure shows a short word in the cell; the full error is the tooltip.
    assert model.data(idx(1, COL_DELAY), Qt.DisplayRole) == "Failed"
    assert model.data(idx(1, COL_DELAY), Qt.ToolTipRole) == "unreachable"
    assert model.data(idx(0, COL_DELAY), Qt.ToolTipRole) is None


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
    assert model.data(model.index(1, COL_DELAY), Qt.DisplayRole) == "15 ms"
    assert model.data(model.index(0, COL_DELAY), Qt.DisplayRole) == "—"


def test_fastest_uid_ignores_failures_and_untested(qapp):
    model = ProfileTableModel()
    model.set_profiles([A, B, C], None)
    model.set_results({
        "a": {"delay_ms": 500.0, "error": None},
        "b": {"delay_ms": None, "error": "unreachable"},
        "c": {"delay_ms": 90.0, "error": None},
    })
    assert model.fastest_uid() == "c"


def test_qr_dialog_opens_with_a_non_null_pixmap(qapp):
    dlg = QrDialog("Alpha", "vless://uuid@a.example.com:443?type=ws#Alpha")
    assert not dlg.image_label.pixmap().isNull()
