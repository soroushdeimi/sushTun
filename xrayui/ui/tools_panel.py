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
from .help import set_help


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
        for text, signal, what, example in (
            (tr("Ping"), self.pingRequested,
             tr("Pings your active server and the internet address from Settings "
                "(Ping target) and shows the replies."),
             tr("Is it the server or your Wi-Fi? Compare the two lines.")),
            (tr("Relay TCP delay"), self.delayRequested,
             tr("Opens a few plain connections to the active server and shows the "
                "average, fastest and slowest time."),
             tr("Pages feel sluggish? See whether the server itself is the slow part.")),
            (tr("Throughput"), self.throughputRequested,
             tr("Measures the tunnel's real traffic for a few seconds, so start a "
                "download first."),
             tr("Start a big download, press this, and read your true speed.")),
            (tr("Baseline"), self.baselineRequested,
             tr("Compares your real network adapter with the tunnel over a few "
                "seconds. Windows only."),
             tr("Curious how much the tunnel costs you in speed? This tells you.")),
            (tr("Diagnostics"), self.diagnosticsRequested,
             tr("Collects the network details the tunnel relies on: server ping, "
                "DNS, routes and the latest log lines."),
             tr("Asking for help? Paste this output along with your question.")),
        ):
            b = QPushButton(text)
            set_help(b, what, example)
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
