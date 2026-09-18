"""DNS editor as a thin dialog wrapper around DnsPage.

All content and behaviour live in the page (see dns_page.py) so the
sidebar window can embed it in place; this class keeps the dialog's modal
interface (title, Save/Cancel) for today's users.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QScrollArea, QVBoxLayout

from ..core import xraycheck  # noqa: F401 -- tests monkeypatch dialogs_mod.xraycheck.check_config
from ..i18n import tr
from .pages.dns_page import DnsPage


class DnsDialog(QDialog):
    def __init__(self, dns: dict, routing_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DNS")
        self.resize(560, 720)
        self.page = DnsPage(dns, routing_cfg, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # The page is taller than a small laptop screen (more so in
        # Persian, which wraps); scroll it instead of forcing the height.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(self.page)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btn_save = buttons.button(QDialogButtonBox.Save)
        self.btn_save.setText(tr("Save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        self.btn_save.setDefault(True)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.page.applied.connect(lambda _dns: self.accept())

        # Qt hands the default to the first autoDefault button on show (the
        # Cloudflare preset); only Save may answer Enter.
        for btn in self.findChildren(QPushButton):
            btn.setAutoDefault(btn is self.btn_save)

    def _save(self) -> None:
        if self._busy:
            return
        self.page.apply()

    def __getattr__(self, name):
        return getattr(self.page, name)
