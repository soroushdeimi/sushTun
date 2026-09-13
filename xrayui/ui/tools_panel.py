"""Diagnostics tools: ping, TCP delay, throughput, diagnostics."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr


class ToolsPanel(QWidget):
    pingRequested = Signal()
    delayRequested = Signal()
    throughputRequested = Signal()
    baselineRequested = Signal()
    diagnosticsRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self._buttons = []
        for text, signal in (
            (tr("Ping"), self.pingRequested),
            (tr("Relay TCP delay"), self.delayRequested),
            (tr("Throughput"), self.throughputRequested),
            (tr("Baseline"), self.baselineRequested),
            (tr("Diagnostics"), self.diagnosticsRequested),
        ):
            b = QPushButton(text)
            b.clicked.connect(signal)
            row.addWidget(b)
            self._buttons.append(b)
        layout.addLayout(row)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Cascadia Code", 10))
        # Diagnostic output (raw ping/delay/throughput numbers and paths).
        self.output.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(self.output, 1)

    def set_busy(self, busy: bool) -> None:
        for b in self._buttons:
            b.setEnabled(not busy)

    def set_result(self, text: str) -> None:
        self.output.setPlainText(text)
