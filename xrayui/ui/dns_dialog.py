"""DNS editor: which resolvers Xray uses, and static domain overrides."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..core import dns as dns_mod

_INHERIT = "Template default"


class DnsDialog(QDialog):
    def __init__(self, dns: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DNS")
        self.resize(560, 640)
        self._dns = dict(dns)
        layout = QVBoxLayout(self)

        presets = QHBoxLayout()
        presets.addWidget(QLabel("Preset:"))
        for name, servers in dns_mod.PRESETS.items():
            btn = QPushButton(name)
            btn.clicked.connect(lambda _=False, s=servers: self._fill(s))
            presets.addWidget(btn)
        presets.addStretch(1)
        layout.addLayout(presets)

        layout.addWidget(QLabel("Resolvers (one per line, in order):"))
        self.servers = QPlainTextEdit("\n".join(dns.get("servers") or []))
        self.servers.setPlaceholderText(
            "Leave empty to keep the template's servers.\n"
            "https://1.1.1.1/dns-query\n"
            "tcp://9.9.9.9:53\n"
            "8.8.8.8\n"
            "Use literal IPs — a hostname needs another resolver to look it up first."
        )
        layout.addWidget(self.servers, 2)

        strategy = QHBoxLayout()
        strategy.addWidget(QLabel("Query strategy:"))
        self.strategy = QComboBox()
        self.strategy.addItem(_INHERIT, "")
        for name in dns_mod.QUERY_STRATEGIES:
            self.strategy.addItem(name, name)
        current = str(dns.get("query_strategy") or "")
        self.strategy.setCurrentIndex(max(0, self.strategy.findData(current)))
        self.strategy.setToolTip(
            "UseIPv4 avoids AAAA answers this IPv4-only tunnel cannot route.\n"
            "UseIP or UseIPv6 can make clients prefer an IPv6 path that leaves\n"
            "over your physical adapter instead of the tunnel."
        )
        strategy.addWidget(self.strategy, 1)
        layout.addLayout(strategy)

        layout.addWidget(QLabel("Static overrides (domain = address):"))
        self.hosts = QPlainTextEdit("\n".join(dns.get("hosts") or []))
        self.hosts.setPlaceholderText(
            "example.com = 93.184.216.34\ncdn.example.com = 1.2.3.4, 5.6.7.8")
        layout.addWidget(self.hosts, 1)

        note = QLabel("DNS queries leave over your normal connection, not the tunnel.")
        note.setObjectName("Muted")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _fill(self, servers: list[str]) -> None:
        self.servers.setPlainText("\n".join(servers))

    @staticmethod
    def _lines(widget: QPlainTextEdit) -> list[str]:
        return [ln.strip() for ln in widget.toPlainText().splitlines() if ln.strip()]

    def _save(self) -> None:
        # Xray exits on a config it cannot parse, so refuse to save a bad entry
        # rather than let the next connect fail with nothing to explain it.
        bad = dns_mod.invalid_servers(self._lines(self.servers))
        if bad:
            QMessageBox.warning(self, "Invalid resolver", "\n\n".join(bad[:8]))
            return
        self.accept()

    def result_dns(self) -> dict:
        self._dns.update(
            servers=dns_mod.clean_servers(self._lines(self.servers)),
            query_strategy=self.strategy.currentData(),
            hosts=self._lines(self.hosts),
        )
        return self._dns
