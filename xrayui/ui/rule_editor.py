"""A single routing rule: the editor dialog, and a small collapsed-section
widget shared with the rule sets tab (routing_dialog.py)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr

_PROTOCOLS = ["http", "tls", "bittorrent"]


class CollapsibleSection(QWidget):
    """A "Name ▸"/"Name ▾" header that shows or hides a content widget."""

    def __init__(self, title: str, content: QWidget, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._content = content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._toggle = QToolButton()
        self._toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.RightArrow)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(False)
        self._toggle.setText(title)
        self._toggle.setStyleSheet("QToolButton { border: none; }")
        self._toggle.toggled.connect(self._on_toggled)

        layout.addWidget(self._toggle)
        layout.addWidget(content)
        content.setVisible(False)

    def _on_toggled(self, expanded: bool) -> None:
        self._toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._content.setVisible(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(expanded)


def default_rule() -> dict:
    return {"remarks": "", "enabled": True, "outbound": "proxy", "domain": [], "ip": [],
            "port": "", "network": "", "protocol": [], "process": []}


class RuleEditorDialog(QDialog):
    def __init__(self, rule: dict | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Edit rule"))
        self.resize(480, 560)
        self._rule = dict(rule) if rule else default_rule()
        r = self._rule
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.remarks = QLineEdit(r.get("remarks", ""))
        form.addRow(tr("Remarks"), self.remarks)

        action_row = QHBoxLayout()
        self.rb_proxy = QRadioButton(tr("Proxy"))
        self.rb_direct = QRadioButton(tr("Direct"))
        self.rb_block = QRadioButton(tr("Block"))
        for rb in (self.rb_proxy, self.rb_direct, self.rb_block):
            action_row.addWidget(rb)
        {"proxy": self.rb_proxy, "direct": self.rb_direct,
         "block": self.rb_block}.get(r.get("outbound", "proxy"), self.rb_proxy).setChecked(True)
        form.addRow(tr("Action"), action_row)
        layout.addLayout(form)

        layout.addWidget(QLabel(tr("Domains (one per line):")))
        self.domains = QPlainTextEdit("\n".join(r.get("domain") or []))
        # Routing-rule syntax examples (domain:/full:/geosite:/keyword: are
        # Xray's own prefixes) -- technical, left in English, and the field
        # itself stays LTR regardless of the app's own direction.
        self.domains.setPlaceholderText("domain:example.com\nfull:exact.example.com\n"
                                        "geosite:google\nkeyword:ads")
        self.domains.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(self.domains, 1)

        layout.addWidget(QLabel(tr("IPs / CIDRs (one per line):")))
        self.ips = QPlainTextEdit("\n".join(r.get("ip") or []))
        self.ips.setPlaceholderText("10.0.0.0/8\ngeoip:ir")
        self.ips.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(self.ips, 1)

        adv_widget = QWidget()
        adv_form = QFormLayout(adv_widget)
        self.port = QLineEdit(r.get("port", ""))
        self.port.setPlaceholderText("443 or 1000-2000 or 80,443,8000-9000")
        adv_form.addRow(tr("Port"), self.port)

        self.network = QComboBox()
        networks = [(tr("Any"), ""), ("TCP", "tcp"), ("UDP", "udp"), ("TCP+UDP", "tcp,udp")]
        for label, value in networks:
            self.network.addItem(label, value)
        idx = self.network.findData(r.get("network", ""))
        self.network.setCurrentIndex(idx if idx >= 0 else 0)
        adv_form.addRow(tr("Network"), self.network)

        proto_row = QHBoxLayout()
        self.protocol_boxes: dict[str, QCheckBox] = {}
        for name in _PROTOCOLS:
            cb = QCheckBox(name)
            cb.setChecked(name in (r.get("protocol") or []))
            self.protocol_boxes[name] = cb
            proto_row.addWidget(cb)
        adv_form.addRow(tr("Protocol"), proto_row)

        self.process = QPlainTextEdit("\n".join(r.get("process") or []))
        self.process.setToolTip(tr("Linux/Windows process names"))
        self.process.setMaximumHeight(70)
        adv_form.addRow(tr("Process"), self.process)

        layout.addWidget(CollapsibleSection(tr("Advanced"), adv_widget))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _lines(widget: QPlainTextEdit) -> list[str]:
        return [ln.strip() for ln in widget.toPlainText().splitlines() if ln.strip()]

    def _save(self) -> None:
        domains = self._lines(self.domains)
        ips = self._lines(self.ips)
        port = self.port.text().strip()
        network = self.network.currentData()
        protocol = [name for name, cb in self.protocol_boxes.items() if cb.isChecked()]
        process = self._lines(self.process)

        if not (domains or ips or port or network or protocol or process):
            QMessageBox.warning(self, tr("Empty rule"),
                                tr("This rule would match nothing. Add at least one condition."))
            return

        outbound = "proxy"
        if self.rb_direct.isChecked():
            outbound = "direct"
        elif self.rb_block.isChecked():
            outbound = "block"

        self._rule.update(
            remarks=self.remarks.text().strip(),
            outbound=outbound,
            domain=domains,
            ip=ips,
            port=port,
            network=network,
            protocol=protocol,
            process=process,
        )
        self.accept()

    def result_rule(self) -> dict:
        return self._rule
