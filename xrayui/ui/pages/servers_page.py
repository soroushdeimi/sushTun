"""Servers page: connection header, table toolbar, filter and the server
table housed in a sunken panel, built from the shared _ServerTableCore."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ..connection_header import ConnectionHeader
from ..mac import IconButton
from ..theme import LINE, SUNKEN
from ..widgets import _ServerTableCore


class ServersPage(QWidget):
    # Re-exposes every core signal so a sidebar consumer wires the page once.
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
    connectRequested = Signal()
    disconnectRequested = Signal()
    restoreNetworkRequested = Signal()
    reconnectRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.header = ConnectionHeader()
        outer.addWidget(self.header)

        self.core = _ServerTableCore()
        # The page's own toolbar: Import opens the file dialog (hence the
        # ellipsis), Test is the split Real-delay/TCP-ping button, and the
        # More icon offers the destructive cleanups.
        self.core.btn_import.setText(tr("Import…"))
        tool = QHBoxLayout()
        tool.setSpacing(8)
        for w in (self.core.btn_import, self.core.btn_test, self.core.btn_fastest):
            tool.addWidget(w)
        self.more_btn = IconButton("ellipsis", tr("More server actions"))
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        self.more_btn.setMenu(self.core.btn_more.menu())
        tool.addWidget(self.more_btn)
        tool.addStretch(1)
        outer.addLayout(tool)

        outer.addWidget(self.core.filter_edit)

        # Sunken panel around the table; the four-pixel rim keeps the frame's
        # rounded corners clear of the table's own (NoFrame) edges.
        self.frame = QFrame()
        self.frame.setObjectName("ServerTableFrame")
        self.frame.setStyleSheet(
            f"QFrame#ServerTableFrame{{background:{SUNKEN};"
            f"border:1px solid {LINE};border-radius:10px;}}"
        )
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)
        self.core.table.setFrameShape(QFrame.NoFrame)
        frame_layout.addWidget(self.core)
        outer.addWidget(self.frame, 1)

        self._fwd = {
            self.core.importRequested: self.importRequested,
            self.core.editRequested: self.editRequested,
            self.core.duplicateRequested: self.duplicateRequested,
            self.core.deleteRequested: self.deleteRequested,
            self.core.activated: self.activated,
            self.core.deleteManyRequested: self.deleteManyRequested,
            self.core.testRealDelayRequested: self.testRealDelayRequested,
            self.core.tcpPingRequested: self.tcpPingRequested,
            self.core.cancelTestRequested: self.cancelTestRequested,
            self.core.useFastestRequested: self.useFastestRequested,
            self.core.removeFailedRequested: self.removeFailedRequested,
            self.core.removeDuplicatesRequested: self.removeDuplicatesRequested,
            self.header.connectRequested: self.connectRequested,
            self.header.disconnectRequested: self.disconnectRequested,
            self.header.restoreNetworkRequested: self.restoreNetworkRequested,
            self.header.reconnectRequested: self.reconnectRequested,
        }
        for source, target in self._fwd.items():
            source.connect(target)

    # -- conveniences forwarded to the core / header ----------------------
    def set_profiles(self, profiles, active_uid=None) -> None:
        self.core.set_profiles(profiles, active_uid)

    def set_active(self, uid: str) -> None:
        self.core.set_active(uid)

    def set_results(self, results: dict) -> None:
        self.core.set_results(results)

    def set_sub_names(self, names: dict) -> None:
        self.core.set_sub_names(names)

    def update_result(self, uid: str, delay_ms, error, skipped=False) -> None:
        self.core.update_result(uid, delay_ms, error, skipped)

    def set_testing(self, active: bool) -> None:
        self.core.set_testing(active)

    def set_filter_text(self, text: str) -> None:
        self.core.set_filter_text(text)

    def set_connection(self, key: str, value: str) -> None:
        self.header.set(key, value)

    def set_connected(self, connected: bool) -> None:
        self.header.set_connected(connected)

    @property
    def filter_edit(self):
        return self.core.filter_edit

    @property
    def table(self):
        return self.core.table
