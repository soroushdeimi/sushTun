"""Reusable UI pieces: status card, profile panel, log view."""
from __future__ import annotations

import html
from collections.abc import Callable

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import share as share_mod
from ..core.profiles import Profile
from ..i18n import ltr, tr
from .server_table import (
    COL_ACTIVE,
    COL_DELAY,
    COL_NAME,
    COL_SUB,
    COL_TYPE,
    OPTIONAL_COLUMNS,
    ProfileFilterProxy,
    ProfileTableModel,
    QrDialog,
)
from .theme import ERR, MUTED, OK, WARN


class AlertBanner(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setVisible(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._action = QPushButton("")
        self._action.setVisible(False)
        self._action_connected = False
        close = QPushButton("✕")
        close.setFixedWidth(28)
        # A bare glyph means nothing to a screen reader or a hovering user.
        close.setToolTip(tr("Close"))
        close.setAccessibleName(tr("Close"))
        close.clicked.connect(lambda: self.setVisible(False))
        row.addWidget(self._label, 1)
        row.addWidget(self._action)
        row.addWidget(close)

    def show_alert(self, level: str, message: str, action_label: str = "",
                   action: Callable[[], None] | None = None) -> None:
        color = ERR if level == "critical" else WARN
        self.setStyleSheet(
            f"QFrame{{background:rgba(0,0,0,0.25);border:1px solid {color};"
            f"border-radius:10px;}} QLabel{{color:{color};font-weight:600;}}"
        )
        self._label.setText(message)
        # A banner shown twice with a fresh action must not also carry the
        # previous one's connection -- track whether one is connected since
        # disconnect() with nothing attached raises.
        if self._action_connected:
            self._action.clicked.disconnect()
            self._action_connected = False
        if action_label and action is not None:
            self._action.setText(action_label)
            self._action.clicked.connect(action)
            self._action_connected = True
            self._action.setVisible(True)
        else:
            self._action.setVisible(False)
        self.setVisible(True)


def _row(label: str) -> tuple[QLabel, QLabel]:
    key = QLabel(label)
    key.setObjectName("Muted")
    val = QLabel("—")
    return key, val


class StatusCard(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        grid = QGridLayout(self)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        title = QLabel(tr("Connection"))
        title.setObjectName("H1")
        self.pill = QLabel(tr("DISCONNECTED"))
        self.pill.setObjectName("PillOff")
        self.pill.setAlignment(Qt.AlignCenter)
        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.pill)
        grid.addLayout(top, 0, 0, 1, 2)

        self._vals: dict[str, QLabel] = {}
        rows = [
            (tr("Relay"), "endpoint"),
            (tr("Xray process"), "process"),
            (tr("Interface"), "iface"),
            (tr("Source IPv4"), "ip"),
            (tr("Gateway"), "gateway"),
            (tr("Tunnel ifIndex"), "tun"),
            (tr("Throughput"), "throughput"),
            (tr("Used this session"), "used"),
        ]
        for i, (label, key) in enumerate(rows, start=1):
            k, v = _row(label)
            self._vals[key] = v
            grid.addWidget(k, i, 0)
            grid.addWidget(v, i, 1)
        grid.setColumnStretch(1, 1)

    def set(self, key: str, value: str) -> None:
        if key in self._vals:
            # Throughput/usage figures ("↓ 4.2 ↑ 0.3 Mbit/s" in fa) hold
            # numbers with Latin units; an LTR isolate keeps them ordered.
            self._vals[key].setText(ltr(value or "—"))

    def set_connected(self, connected: bool) -> None:
        self.pill.setText(tr("CONNECTED") if connected else tr("DISCONNECTED"))
        self.pill.setObjectName("PillOn" if connected else "PillOff")
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)


class _ServerTableCore(QWidget):
    """The server table's reusable core: model, proxy, multi-select table,
    context menu, header menu and share/QR, extracted from ProfilePanel so
    the old panel and the new ServersPage behave identically. The filter
    input and the toolbar buttons exist here as widgets but the consumer
    places them in its own layout (the panel puts the toolbar below the
    table, the page above it)."""

    importRequested = Signal()
    editRequested = Signal(str)
    duplicateRequested = Signal(str)
    deleteRequested = Signal(str)
    activated = Signal(str)
    deleteManyRequested = Signal(list)
    testRealDelayRequested = Signal(list)
    tcpPingRequested = Signal(list)
    cancelTestRequested = Signal()
    useFastestRequested = Signal(str)
    removeFailedRequested = Signal()
    removeDuplicatesRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        if not hasattr(self, "_layout"):
            self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Widgets the consumer arranges itself; parenting them here stops
        # a consumer that skips one from leaving it orphaned and top-level.
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText(tr("Filter by name or address…"))

        self.model = ProfileTableModel()
        self.proxy = ProfileFilterProxy()
        self.proxy.setSourceModel(self.model)
        self.filter_edit.textChanged.connect(self.proxy.set_needle)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setTextElideMode(Qt.ElideRight)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col in (COL_ACTIVE, COL_DELAY, *[c for c, _ in OPTIONAL_COLUMNS]):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        # Transport already implies Type; both stay in the header menu.
        self.table.setColumnHidden(COL_TYPE, True)
        self.table.setColumnHidden(COL_SUB, True)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)

        self.table.setSortingEnabled(True)
        # setSortingEnabled(True) sorts by section 0 immediately; undo that
        # so the table keeps the store's order until a header is clicked.
        header.setSortIndicator(-1, Qt.AscendingOrder)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_menu)
        self.table.doubleClicked.connect(lambda _i: self._emit_current(self.editRequested))
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._layout.addWidget(self.table, 1)

        # An empty table says what to do next instead of showing a blank grid.
        self.empty_hint = QLabel(self.table.viewport())
        self.empty_hint.setObjectName("Muted")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setMinimumWidth(320)
        hint_layout = QVBoxLayout(self.table.viewport())
        hint_layout.addWidget(self.empty_hint, 0, Qt.AlignCenter)
        for signal in (self.proxy.rowsInserted, self.proxy.rowsRemoved,
                       self.proxy.modelReset, self.proxy.layoutChanged):
            signal.connect(self._update_empty_hint)
        self._update_empty_hint()

        # Toolbar buttons, placed by the consumer's own layout.
        self._testing = False
        self.btn_import = QPushButton(tr("Import"), self)
        self.btn_import.setObjectName("Primary")
        self.btn_import.clicked.connect(self.importRequested)

        self.btn_test = QToolButton(self)
        self.btn_test.setText(tr("Test"))
        self.btn_test.setPopupMode(QToolButton.MenuButtonPopup)
        self.btn_test.clicked.connect(lambda: self._start_test(real=True))
        test_menu = QMenu(self.btn_test)
        test_menu.addAction(tr("Real delay"), lambda: self._start_test(real=True))
        test_menu.addAction(tr("TCP ping"), lambda: self._start_test(real=False))
        self.btn_test.setMenu(test_menu)

        self.btn_fastest = QPushButton(tr("Use fastest"), self)
        self.btn_fastest.clicked.connect(self._use_fastest)

        self.btn_more = QToolButton(self)
        self.btn_more.setText("⋯")
        self.btn_more.setPopupMode(QToolButton.InstantPopup)
        more_menu = QMenu(self.btn_more)
        # addAction takes a callable; a SignalInstance is not one, so trigger
        # it via a lambda or the menu action dies with "not callable".
        more_menu.addAction(
            tr("Remove failed"), lambda checked=False: self.removeFailedRequested.emit()
        )
        more_menu.addAction(
            tr("Remove duplicates"),
            lambda checked=False: self.removeDuplicatesRequested.emit(),
        )
        self.btn_more.setMenu(more_menu)

        self.btn_import.setAccessibleName(tr("Import"))
        self.btn_test.setAccessibleName(tr("Test"))
        self.btn_fastest.setAccessibleName(tr("Use fastest"))
        self.btn_more.setAccessibleName(tr("More server actions"))

    def set_filter_text(self, text: str) -> None:
        self.filter_edit.setText(text)

    # -- population ----------------------------------------------------
    def _update_empty_hint(self, *_args) -> None:
        if self.proxy.rowCount():
            self.empty_hint.hide()
            return
        if self.model.rowCount():
            self.empty_hint.setText(tr("No servers match the filter."))
        else:
            self.empty_hint.setText(tr("No servers yet. Import a link, or add a subscription."))
        self.empty_hint.show()

    def set_profiles(self, profiles: list[Profile], active_uid: str | None) -> None:
        # A full reload (import/edit/delete/subscription refresh) must not
        # collapse a multi-selection down to one row: keep whatever's still
        # selectable, or fall back to the active row on a first load.
        previous = self.selected_uids()
        self.model.set_profiles(profiles, active_uid)
        keep = [u for u in previous if self.model.row_of_uid(u) is not None]
        if not keep and active_uid and self.model.row_of_uid(active_uid) is not None:
            keep = [active_uid]
        self._reselect(keep)

    def set_active(self, uid: str) -> None:
        # Just the ● marker moves, no reset -- selecting a row to activate
        # it must not disturb a multi-selection made for Test/Delete.
        self.model.set_active_uid(uid)

    def set_results(self, results: dict) -> None:
        self.model.set_results(results)

    def set_sub_names(self, names: dict) -> None:
        self.model.set_sub_names(names)

    def update_result(
        self, uid: str, delay_ms: float | None, error: str | None, skipped: bool = False,
    ) -> None:
        self.model.update_result(uid, delay_ms, error, skipped)

    def set_testing(self, active: bool) -> None:
        self._testing = active
        self.btn_test.setText(tr("Cancel") if active else tr("Test"))
        self.btn_fastest.setEnabled(not active)
        self.btn_more.setEnabled(not active)

    def _reselect(self, uids: list[str]) -> None:
        if not uids:
            return
        selection = QItemSelection()
        last_col = self.model.columnCount() - 1
        first_proxy_idx = None
        for uid in uids:
            row = self.model.row_of_uid(uid)  # a *source* row; map both ends from it
            if row is None:
                continue
            start = self.proxy.mapFromSource(self.model.index(row, 0))
            end = self.proxy.mapFromSource(self.model.index(row, last_col))
            if not start.isValid():
                continue
            selection.select(start, end)
            first_proxy_idx = first_proxy_idx or start
        if first_proxy_idx is None:
            return
        # Programmatic reselect after a reload must not re-fire `activated`
        # (that would re-persist the same active uid on every refresh, and
        # a multi-row reselect would collapse straight back to one anyway).
        sel_model = self.table.selectionModel()
        sel_model.blockSignals(True)
        sel_model.select(selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        # QTableView.setCurrentIndex() applies its own ClearAndSelect command
        # and would collapse the multi-row selection just made above; set
        # the current index on the selection model directly instead, with
        # NoUpdate so it doesn't touch the selection at all.
        sel_model.setCurrentIndex(first_proxy_idx, QItemSelectionModel.NoUpdate)
        sel_model.blockSignals(False)

    # -- selection / lookups ---------------------------------------------
    def current_uid(self) -> str | None:
        idx = self.table.currentIndex()
        if not idx.isValid():
            return None
        p = self.model.profile_at(self.proxy.mapToSource(idx).row())
        return p.uid if p else None

    def selected_uids(self) -> list[str]:
        uids = []
        for idx in self.table.selectionModel().selectedRows():
            p = self.model.profile_at(self.proxy.mapToSource(idx).row())
            if p:
                uids.append(p.uid)
        return uids

    def visible_uids(self) -> list[str]:
        """Uids in the table's current visible order (post header-sort)."""
        uids = []
        for row in range(self.proxy.rowCount()):
            p = self.model.profile_at(self.proxy.mapToSource(self.proxy.index(row, 0)).row())
            if p:
                uids.append(p.uid)
        return uids

    def _profile(self, uid: str) -> Profile | None:
        row = self.model.row_of_uid(uid)
        return self.model.profile_at(row) if row is not None else None

    def _emit_current(self, signal) -> None:
        uid = self.current_uid()
        if uid:
            signal.emit(uid)

    def _on_selection_changed(self, *_args) -> None:
        # Only a single selected row means "activate this one": a Ctrl-click
        # extending the selection to two rows must not immediately persist
        # whichever of them happens to be `current`, or Test/Delete could
        # never see more than one uid (the very next reload would reselect
        # just the newly-"activated" row).
        uids = self.selected_uids()
        if len(uids) == 1:
            self.activated.emit(uids[0])

    # -- toolbar / menu actions -------------------------------------------
    def _start_test(self, real: bool) -> None:
        if self._testing:
            self.cancelTestRequested.emit()
            return
        uids = self.visible_uids()
        if not uids:
            return
        (self.testRealDelayRequested if real else self.tcpPingRequested).emit(uids)

    def _use_fastest(self) -> None:
        uid = self.model.fastest_uid()
        if uid:
            self.useFastestRequested.emit(uid)

    def _delete_selected(self, uids: list[str]) -> None:
        if len(uids) == 1:
            self.deleteRequested.emit(uids[0])
        else:
            self.deleteManyRequested.emit(uids)

    def _no_share_link(self) -> None:
        QMessageBox.information(self, tr("No share link"),
                                tr("No share link for this server type."))

    def _copy_link(self, uid: str) -> None:
        p = self._profile(uid)
        if not p:
            return
        link = share_mod.share_link(p)
        if link is None:
            self._no_share_link()
            return
        QApplication.clipboard().setText(link)

    def _show_qr(self, uid: str) -> None:
        p = self._profile(uid)
        if not p:
            return
        link = share_mod.share_link(p)
        if link is None:
            self._no_share_link()
            return
        QrDialog(p.name, link, self).exec()

    def _build_context_menu(self, uids: list[str]) -> QMenu | None:
        if not uids:
            return None
        menu = QMenu(self)
        if len(uids) == 1:
            uid = uids[0]
            menu.addAction(tr("Set active"), lambda: self.activated.emit(uid))
            menu.addAction(tr("Edit"), lambda: self.editRequested.emit(uid))
            menu.addAction(tr("Clone"), lambda: self.duplicateRequested.emit(uid))
        menu.addAction(tr("Test real delay"), lambda: self.testRealDelayRequested.emit(uids))
        menu.addAction(tr("TCP ping"), lambda: self.tcpPingRequested.emit(uids))
        if len(uids) == 1:
            menu.addAction(tr("Copy share link"), lambda: self._copy_link(uids[0]))
            menu.addAction(tr("Show QR"), lambda: self._show_qr(uids[0]))
        menu.addSeparator()
        menu.addAction(tr("Delete"), lambda: self._delete_selected(uids))
        return menu

    def _show_menu(self, pos) -> None:
        menu = self._build_context_menu(self.selected_uids())
        if menu is None:
            return
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _build_header_menu(self) -> QMenu:
        menu = QMenu(self)
        for col, label in OPTIONAL_COLUMNS:
            action = menu.addAction(tr(label))
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(col))
            action.toggled.connect(lambda checked, c=col: self.table.setColumnHidden(c, not checked))
        return menu

    def _show_header_menu(self, pos) -> None:
        menu = self._build_header_menu()
        menu.exec(self.table.horizontalHeader().viewport().mapToGlobal(pos))


class ProfilePanel(_ServerTableCore):
    # Thin layout wrapper around _ServerTableCore: heading, filter, then the
    # toolbar under the table, exactly as before the extraction.
    def __init__(self) -> None:
        super().__init__()
        layout = self._layout
        header = QLabel(tr("Servers"))
        header.setObjectName("H1")
        layout.insertWidget(0, header)
        layout.insertWidget(1, self.filter_edit)

        toolbar = QHBoxLayout()
        for w in (self.btn_import, self.btn_test, self.btn_fastest, self.btn_more):
            toolbar.addWidget(w)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)


class LogView(QTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Log")
        self.setReadOnly(True)
        self.setFont(QFont("Cascadia Code", 10))
        self.document().setMaximumBlockCount(5000)

    @staticmethod
    def _markup(line: str) -> str:
        color = MUTED
        if "[Warning]" in line or "failed" in line:
            color = WARN
        if "[Error]" in line or "panic" in line:
            color = ERR
        if "started" in line:
            color = OK
        return f'<span style="color:{color}">{html.escape(line)}</span>'

    def append_line(self, line: str) -> None:
        self.append(self._markup(line))
        self.moveCursor(QTextCursor.End)

    def append_lines(self, lines: list[str]) -> None:
        # One append per batch: per-line appends stall the UI on busy logs.
        if not lines:
            return
        self.append("<br>".join(self._markup(ln) for ln in lines))
        self.moveCursor(QTextCursor.End)

    def clear_log(self) -> None:
        self.clear()
