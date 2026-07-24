"""Diagnostics tools: ping, TCP delay, throughput, diagnostics."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ToolsPanel(QWidget):
    pingRequested = Signal()
    delayRequested = Signal()
    throughputRequested = Signal()
    diagnosticsRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self._buttons = []
        for text, signal in (
            ("Ping", self.pingRequested),
            ("Relay TCP delay", self.delayRequested),
            ("Throughput", self.throughputRequested),
            ("Diagnostics", self.diagnosticsRequested),
        ):
            b = QPushButton(text)
            b.clicked.connect(signal)
            row.addWidget(b)
            self._buttons.append(b)
        layout.addLayout(row)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Cascadia Code", 10))
        layout.addWidget(self.output, 1)

    def set_busy(self, busy: bool) -> None:
        for b in self._buttons:
            b.setEnabled(not busy)

    def set_result(self, text: str) -> None:
        self.output.setPlainText(text)
