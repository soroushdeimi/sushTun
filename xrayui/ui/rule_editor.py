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
    QPushButton,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from .help import set_help

_PROTOCOLS = ["http", "tls", "bittorrent"]


def _protocol_help(name: str) -> tuple[str, str]:
    if name == "http":
        return (tr("Matches plain, unencrypted web traffic."),
                tr("Catch the old sites that still don't use HTTPS."))
    if name == "tls":
        return (tr("Matches encrypted connections, which is nearly all modern web "
                   "traffic."),
                tr("Catch every secure connection, whatever the website."))
    return (tr("Matches BitTorrent traffic."),
            tr("Block torrents on a server with a data cap."))


class CollapsibleSection(QWidget):
    """A "▸ Name"/"▾ Name" header that shows or hides a content widget.

    The glyph is part of the button's own text rather than Qt's built-in
    arrow icon (QToolButton.setArrowType): that icon paints in a fixed
    corner regardless of the widget's layoutDirection, so in RTL it lands
    on top of the Persian title instead of beside it.
    """

    def __init__(self, title: str, content: QWidget, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._content = content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._toggle = QToolButton()
        self._toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(False)
        self._toggle.setStyleSheet("QToolButton { border: none; }")
        self._toggle.toggled.connect(self._on_toggled)
        self._update_text(False)

        layout.addWidget(self._toggle)
        layout.addWidget(content)
        content.setVisible(False)

    @property
    def toggle(self) -> QToolButton:
        return self._toggle

    def _update_text(self, expanded: bool) -> None:
        if expanded:
            glyph = "▾"
        else:
            glyph = "◂" if self.isRightToLeft() else "▸"
        self._toggle.setText(f"{self._title} {glyph}" if self.isRightToLeft()
                             else f"{glyph} {self._title}")

    def _on_toggled(self, expanded: bool) -> None:
        self._update_text(expanded)
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
        set_help(self.remarks,
                 tr("Your own note about what this rule is for."),
                 tr("\"Banks stay direct\" beats a rule you can't remember."))
        form.addRow(tr("Remarks"), self.remarks)

        action_row = QHBoxLayout()
        self.rb_proxy = QRadioButton(tr("Proxy"))
        self.rb_direct = QRadioButton(tr("Direct"))
        self.rb_block = QRadioButton(tr("Block"))
        set_help(self.rb_proxy,
                 tr("Traffic that matches goes through the tunnel."),
                 tr("A site that's blocked where you live."))
        set_help(self.rb_direct,
                 tr("Traffic that matches skips the tunnel and goes straight out."),
                 tr("Your bank, which dislikes foreign addresses."))
        set_help(self.rb_block,
                 tr("Traffic that matches is dropped and goes nowhere."),
                 tr("Ads, trackers, and that one app that phones home."))
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
        set_help(self.domains,
                 tr("Websites to match, one per line. domain:example.com covers a "
                    "site and its subdomains, full: an exact name, keyword: any name "
                    "containing a word, geosite: a ready-made group."),
                 tr("geosite:google matches Google's whole family of sites."))
        layout.addWidget(self.domains, 1)

        layout.addWidget(QLabel(tr("IPs / CIDRs (one per line):")))
        self.ips = QPlainTextEdit("\n".join(r.get("ip") or []))
        self.ips.setPlaceholderText("10.0.0.0/8\ngeoip:ir")
        self.ips.setLayoutDirection(Qt.LeftToRight)
        set_help(self.ips,
                 tr("Addresses to match, one per line. A range like 10.0.0.0/8 covers "
                    "many at once, and geoip:ir covers a whole country."),
                 tr("192.168.0.0/16 matches everything on a typical home network."))
        layout.addWidget(self.ips, 1)

        adv_widget = QWidget()
        adv_form = QFormLayout(adv_widget)
        self.port = QLineEdit(r.get("port", ""))
        self.port.setPlaceholderText("443 or 1000-2000 or 80,443,8000-9000")
        set_help(self.port,
                 tr("Only match traffic going to these ports: one port, a range, or "
                    "a comma-separated list."),
                 tr("80,443 matches ordinary web browsing."))
        adv_form.addRow(tr("Port"), self.port)

        self.network = QComboBox()
        networks = [(tr("Any"), ""), ("TCP", "tcp"), ("UDP", "udp"), ("TCP+UDP", "tcp,udp")]
        for label, value in networks:
            self.network.addItem(label, value)
        idx = self.network.findData(r.get("network", ""))
        self.network.setCurrentIndex(idx if idx >= 0 else 0)
        set_help(self.network,
                 tr("Only match this kind of traffic. TCP covers most things; UDP "
                    "covers calls, games and QUIC."),
                 tr("Leave it on Any unless the rule is only for one of them."))
        adv_form.addRow(tr("Network"), self.network)

        proto_row = QHBoxLayout()
        self.protocol_boxes: dict[str, QCheckBox] = {}
        for name in _PROTOCOLS:
            cb = QCheckBox(name)
            cb.setChecked(name in (r.get("protocol") or []))
            set_help(cb, *_protocol_help(name))
            self.protocol_boxes[name] = cb
            proto_row.addWidget(cb)
        adv_form.addRow(tr("Protocol"), proto_row)

        self.process = QPlainTextEdit("\n".join(r.get("process") or []))
        set_help(self.process,
                 tr("Names of programs to match, one per line, such as firefox. "
                    "Works on Linux and Windows."),
                 tr("Name your download manager here and choose Direct to keep it "
                    "off the tunnel."))
        self.process.setMaximumHeight(70)
        adv_form.addRow(tr("Process"), self.process)

        adv_section = CollapsibleSection(tr("Advanced"), adv_widget)
        set_help(adv_section.toggle,
                 tr("Shows the rarely needed conditions."),
                 tr("Skip it for simple rules."))
        layout.addWidget(adv_section)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr("Save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.button(QDialogButtonBox.Save).setDefault(True)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Only Save may be default: on macOS an autoDefault Cancel took the
        # default role when the dialog was shown, and Enter threw the edit away.
        for btn in self.findChildren(QPushButton):
            btn.setAutoDefault(btn is buttons.button(QDialogButtonBox.Save))

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
