"""Reusable UI pieces: status card, profile panel, log view."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.profiles import Profile
from .theme import ERR, MUTED, OK, WARN


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
    importRequested = Signal()
    editRequested = Signal(str)
    duplicateRequested = Signal(str)
    deleteRequested = Signal(str)
    activated = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Profiles")
        header.setObjectName("H1")
        layout.addWidget(header)

        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._on_select)
        self.list.itemDoubleClicked.connect(lambda _i: self._emit(self.editRequested))
        layout.addWidget(self.list, 1)

        btns = QHBoxLayout()
        self.btn_import = QPushButton("Import")
        self.btn_edit = QPushButton("Edit")
        self.btn_dup = QPushButton("Duplicate")
        self.btn_del = QPushButton("Delete")
        self.btn_import.setObjectName("Primary")
        self.btn_import.clicked.connect(self.importRequested)
        self.btn_edit.clicked.connect(lambda: self._emit(self.editRequested))
        self.btn_dup.clicked.connect(lambda: self._emit(self.duplicateRequested))
        self.btn_del.clicked.connect(lambda: self._emit(self.deleteRequested))
        for b in (self.btn_import, self.btn_edit, self.btn_dup, self.btn_del):
            btns.addWidget(b)
        layout.addLayout(btns)

    def set_profiles(self, profiles: list[Profile], active_uid: str | None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for p in profiles:
            mark = "● " if p.uid == active_uid else "   "
            item = QListWidgetItem(f"{mark}{p.name}\n     {p.endpoint}")
            item.setData(Qt.UserRole, p.uid)
            self.list.addItem(item)
            if p.uid == active_uid:
                item.setSelected(True)
        self.list.blockSignals(False)

    def current_uid(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _emit(self, signal) -> None:
        uid = self.current_uid()
        if uid:
            signal.emit(uid)

    def _on_select(self) -> None:
        uid = self.current_uid()
        if uid:
            self.activated.emit(uid)


class LogView(QTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Log")
        self.setReadOnly(True)
        self.setFont(QFont("Cascadia Code", 10))
        self.document().setMaximumBlockCount(5000)

    def append_line(self, line: str) -> None:
        color = None
        if "[Warning]" in line or "failed" in line:
            color = WARN
        if "[Error]" in line or "panic" in line:
            color = ERR
        if "started" in line:
            color = OK
        text = html.escape(line)
        muted = MUTED
        payload = f'<span style="color:{color}">{text}</span>' if color else \
            f'<span style="color:{muted}">{text}</span>'
        self.append(payload)
        self.moveCursor(QTextCursor.End)

    def clear_log(self) -> None:
        self.clear()
