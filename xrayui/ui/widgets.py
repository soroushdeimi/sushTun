"""Reusable UI pieces: status card, profile panel, log view."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
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
    QPushButton,
    QTableView,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import share as share_mod
from ..core.profiles import Profile
from .server_table import ProfileFilterProxy, ProfileTableModel, QrDialog
from .theme import ERR, MUTED, OK, WARN


class AlertBanner(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setVisible(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        close = QPushButton("✕")
        close.setFixedWidth(28)
        close.clicked.connect(lambda: self.setVisible(False))
        row.addWidget(self._label, 1)
        row.addWidget(close)

    def show_alert(self, level: str, message: str) -> None:
        color = ERR if level == "critical" else WARN
        self.setStyleSheet(
            f"QFrame{{background:rgba(0,0,0,0.25);border:1px solid {color};"
            f"border-radius:10px;}} QLabel{{color:{color};font-weight:600;}}"
        )
        self._label.setText(message)
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

        title = QLabel("Connection")
        title.setObjectName("H1")
        self.pill = QLabel("DISCONNECTED")
        self.pill.setObjectName("PillOff")
        self.pill.setAlignment(Qt.AlignCenter)
        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.pill)
        grid.addLayout(top, 0, 0, 1, 2)

        self._vals: dict[str, QLabel] = {}
        rows = [
            ("Relay", "endpoint"),
            ("Xray process", "process"),
            ("Interface", "iface"),
            ("Source IPv4", "ip"),
            ("Gateway", "gateway"),
            ("Tunnel ifIndex", "tun"),
            ("Throughput", "throughput"),
            ("Used this session", "used"),
        ]
        for i, (label, key) in enumerate(rows, start=1):
            k, v = _row(label)
            self._vals[key] = v
            grid.addWidget(k, i, 0)
            grid.addWidget(v, i, 1)
        grid.setColumnStretch(1, 1)

    def set(self, key: str, value: str) -> None:
        if key in self._vals:
            self._vals[key].setText(value or "—")

    def set_connected(self, connected: bool) -> None:
        self.pill.setText("CONNECTED" if connected else "DISCONNECTED")
        self.pill.setObjectName("PillOn" if connected else "PillOff")
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)


class ProfilePanel(QWidget):
    # Kept exactly as before so MainWindow's wiring stays small.
    importRequested = Signal()
    editRequested = Signal(str)
    duplicateRequested = Signal(str)
    deleteRequested = Signal(str)
    activated = Signal(str)

    # New, additive: multi-select delete and the speed-test toolbar/menu.
    deleteManyRequested = Signal(list)
    testRealDelayRequested = Signal(list)
    tcpPingRequested = Signal(list)
    cancelTestRequested = Signal()
    useFastestRequested = Signal(str)
    removeFailedRequested = Signal()
    removeDuplicatesRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Profiles")
        header.setObjectName("H1")
        layout.addWidget(header)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by name or address…")
        layout.addWidget(self.filter_edit)

        self.model = ProfileTableModel()
        self.proxy = ProfileFilterProxy()
        self.proxy.setSourceModel(self.model)
        self.filter_edit.textChanged.connect(self.proxy.set_needle)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_menu)
        self.table.doubleClicked.connect(lambda _i: self._emit_current(self.editRequested))
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        self._testing = False
        toolbar = QHBoxLayout()
        self.btn_import = QPushButton("Import")
        self.btn_import.setObjectName("Primary")
        self.btn_import.clicked.connect(self.importRequested)

        self.btn_test = QToolButton()
        self.btn_test.setText("Test")
        self.btn_test.setPopupMode(QToolButton.MenuButtonPopup)
        self.btn_test.clicked.connect(lambda: self._start_test(real=True))
        test_menu = QMenu(self.btn_test)
        test_menu.addAction("Real delay", lambda: self._start_test(real=True))
        test_menu.addAction("TCP ping", lambda: self._start_test(real=False))
        self.btn_test.setMenu(test_menu)

        self.btn_fastest = QPushButton("Use fastest")
        self.btn_fastest.clicked.connect(self._use_fastest)

        self.btn_more = QToolButton()
        self.btn_more.setText("⋯")
        self.btn_more.setPopupMode(QToolButton.InstantPopup)
        more_menu = QMenu(self.btn_more)
        more_menu.addAction("Remove failed", self.removeFailedRequested)
        more_menu.addAction("Remove duplicates", self.removeDuplicatesRequested)
        self.btn_more.setMenu(more_menu)

        for w in (self.btn_import, self.btn_test, self.btn_fastest, self.btn_more):
            toolbar.addWidget(w)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

    # -- population ----------------------------------------------------
    def set_profiles(self, profiles: list[Profile], active_uid: str | None) -> None:
        self.model.set_profiles(profiles, active_uid)
        self._reselect(active_uid)

    def set_results(self, results: dict) -> None:
        self.model.set_results(results)

    def set_sub_names(self, names: dict) -> None:
        self.model.set_sub_names(names)

    def update_result(self, uid: str, delay_ms: float | None, error: str | None) -> None:
        self.model.update_result(uid, delay_ms, error)

    def set_testing(self, active: bool) -> None:
        self._testing = active
        self.btn_test.setText("Cancel" if active else "Test")
        self.btn_fastest.setEnabled(not active)
        self.btn_more.setEnabled(not active)

    def _reselect(self, active_uid: str | None) -> None:
        if not active_uid:
            return
        row = self.model.row_of_uid(active_uid)
        if row is None:
            return
        proxy_idx = self.proxy.mapFromSource(self.model.index(row, 0))
        if not proxy_idx.isValid():
            return
        # Programmatic reselect after a reload must not re-fire `activated`
        # (that would re-persist the same active uid on every refresh).
        self.table.selectionModel().blockSignals(True)
        self.table.selectRow(proxy_idx.row())
        self.table.selectionModel().blockSignals(False)

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

    def _visible_uids(self) -> list[str]:
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
        uid = self.current_uid()
        if uid:
            self.activated.emit(uid)

    # -- toolbar / menu actions -------------------------------------------
    def _start_test(self, real: bool) -> None:
        if self._testing:
            self.cancelTestRequested.emit()
            return
        uids = self._visible_uids()
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

    def _copy_link(self, uid: str) -> None:
        p = self._profile(uid)
        if p:
            QApplication.clipboard().setText(share_mod.share_link(p))

    def _show_qr(self, uid: str) -> None:
        p = self._profile(uid)
        if p:
            QrDialog(p.name, share_mod.share_link(p), self).exec()

    def _show_menu(self, pos) -> None:
        uids = self.selected_uids()
        if not uids:
            return
        menu = QMenu(self)
        if len(uids) == 1:
            uid = uids[0]
            menu.addAction("Set active", lambda: self.activated.emit(uid))
            menu.addAction("Edit", lambda: self.editRequested.emit(uid))
            menu.addAction("Clone", lambda: self.duplicateRequested.emit(uid))
        menu.addAction("Test real delay", lambda: self.testRealDelayRequested.emit(uids))
        menu.addAction("TCP ping", lambda: self.tcpPingRequested.emit(uids))
        if len(uids) == 1:
            menu.addAction("Copy share link", lambda: self._copy_link(uids[0]))
            menu.addAction("Show QR", lambda: self._show_qr(uids[0]))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self._delete_selected(uids))
        menu.exec(self.table.viewport().mapToGlobal(pos))


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
