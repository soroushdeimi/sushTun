"""Bypass / routing editor: what should skip the tunnel and go direct."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..core.routing import APP_PRESETS


class RoutingDialog(QDialog):
    def __init__(self, routing: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bypass & routing")
        self.resize(560, 640)
        self._routing = dict(routing)
        layout = QVBoxLayout(self)

        toggles = QGroupBox("Bypass the tunnel (go direct)")
        tg = QGridLayout(toggles)
        self.cb_low = QCheckBox("Low usage — bypass Windows telemetry/update chatter")
        self.cb_ads = QCheckBox("Block ads & trackers")
        self.cb_iran = QCheckBox("Iranian sites & IPs direct (geosite/geoip)")
        self.cb_private = QCheckBox("Local network / private IPs direct")
        self.cb_low.setChecked(routing.get("low_usage", False))
        self.cb_ads.setChecked(routing.get("block_ads", True))
        self.cb_iran.setChecked(routing.get("direct_iran", True))
        self.cb_private.setChecked(routing.get("direct_private", True))
        for i, cb in enumerate((self.cb_low, self.cb_ads, self.cb_iran, self.cb_private)):
            tg.addWidget(cb, i, 0)
        layout.addWidget(toggles)

        presets = QGroupBox("App presets (direct)")
        pg = QGridLayout(presets)
        self._preset_boxes: dict[str, QCheckBox] = {}
        enabled = set(routing.get("app_presets", []))
        for i, name in enumerate(APP_PRESETS):
            cb = QCheckBox(name)
            cb.setChecked(name in enabled)
            self._preset_boxes[name] = cb
            pg.addWidget(cb, i // 2, i % 2)
        layout.addWidget(presets)

        layout.addWidget(QLabel("Bypass domains (one per line — direct):"))
        self.domains = QPlainTextEdit("\n".join(routing.get("bypass_domains", [])))
        self.domains.setPlaceholderText("example.com\ngeosite:google")
        layout.addWidget(self.domains)

        layout.addWidget(QLabel("Bypass IPs / CIDRs (one per line — direct):"))
        self.ips = QPlainTextEdit("\n".join(routing.get("bypass_ips", [])))
        self.ips.setPlaceholderText("10.0.0.0/8\ngeoip:ir")
        layout.addWidget(self.ips)

        layout.addWidget(QLabel("Force through tunnel (one per line — proxy):"))
        self.proxy = QPlainTextEdit("\n".join(routing.get("proxy_domains", [])))
        layout.addWidget(self.proxy)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _lines(widget: QPlainTextEdit) -> list[str]:
        return [ln.strip() for ln in widget.toPlainText().splitlines() if ln.strip()]

    def result_routing(self) -> dict:
        self._routing.update(
            low_usage=self.cb_low.isChecked(),
            block_ads=self.cb_ads.isChecked(),
            direct_iran=self.cb_iran.isChecked(),
            direct_private=self.cb_private.isChecked(),
            app_presets=[n for n, cb in self._preset_boxes.items() if cb.isChecked()],
            bypass_domains=self._lines(self.domains),
            bypass_ips=self._lines(self.ips),
            proxy_domains=self._lines(self.proxy),
        )
        return self._routing
