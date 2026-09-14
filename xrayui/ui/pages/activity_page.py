"""Activity page: a segmented tab bar switching between the live log, the
diagnostics tools and a read-only diagnostics readout."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import ltr, tr
from ..mac import InsetGroup
from ..tools_panel import ToolsPanel
from ..widgets import LogView

_DIAGNOSTIC_ROWS = (
    (tr("Xray process"), "process"),
    (tr("Interface"), "iface"),
    (tr("Source IPv4"), "ip"),
    (tr("Gateway"), "gateway"),
    (tr("Tunnel ifIndex"), "tun"),
)


class _DiagnosticsPanel(QWidget):
    """The four-inset diagnostics readout: current xray process/interface
    pairing plus a "Run diagnostics" button and its raw output."""

    runRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self._values: dict[str, QLabel] = {}
        group = InsetGroup()
        for label, key in _DIAGNOSTIC_ROWS:
            value = QLabel("—")
            value.setObjectName("Mono")
            group.add_row(label, value)
            self._values[key] = value
        outer.addWidget(group)

        run = QPushButton(tr("Diagnostics"))
        run.clicked.connect(self.runRequested)
        run_row = QHBoxLayout()
        run_row.addWidget(run)
        run_row.addStretch(1)
        outer.addLayout(run_row)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        # Raw paths and numbers -- force LTR so lines don't reorder in fa.
        self.output.setLayoutDirection(Qt.LeftToRight)
        outer.addWidget(self.output, 1)

    def set_detail(self, key: str, value: str) -> None:
        label = self._values.get(key)
        if label is not None:
            label.setText(ltr(value))

    def set_output(self, text: str) -> None:
        self.output.setPlainText(text)


class ActivityPage(QWidget):
    pingRequested = Signal()
    delayRequested = Signal()
    throughputRequested = Signal()
    baselineRequested = Signal()
    diagnosticsRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.tabs = QTabBar()
        self.tabs.addTab(tr("Live log"))
        self.tabs.addTab(tr("Tools"))
        self.tabs.addTab(tr("Diagnostics"))
        outer.addWidget(self.tabs, 0, Qt.AlignLeft)

        self.stack = QStackedWidget()
        self.log = LogView()
        self.tools = ToolsPanel()
        self.diagnostics = _DiagnosticsPanel()
        for widget in (self.log, self.tools, self.diagnostics):
            self.stack.addWidget(widget)
        outer.addWidget(self.stack, 1)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)

        # The page is the single surface a sidebar consumer wires into its
        # handlers; the tools segment's signals become the page's own.
        self.tools.pingRequested.connect(self.pingRequested)
        self.tools.delayRequested.connect(self.delayRequested)
        self.tools.throughputRequested.connect(self.throughputRequested)
        self.tools.baselineRequested.connect(self.baselineRequested)
        self.tools.diagnosticsRequested.connect(self.diagnosticsRequested)
        self.diagnostics.runRequested.connect(self.diagnosticsRequested)

    def set_busy(self, busy: bool) -> None:
        self.tools.set_busy(busy)

    def append_log(self, line: str) -> None:
        self.log.append(line)
