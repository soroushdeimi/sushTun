"""Bypass / routing editor as a thin dialog wrapper around RoutingPage.

All content and behaviour live in the page (see routing_page.py) so the
sidebar window can embed it in place; this class keeps the dialog's modal
interface (window title, Save/Cancel) for today's users.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

from ..core import xraycheck  # noqa: F401 -- tests monkeypatch rd.xraycheck.check_rules
from ..i18n import tr
from .pages.routing_page import (  # noqa: F401 (i18n coverage reads the name here)
    _RULE_COLS,
    RoutingPage,
)


class RoutingDialog(QDialog):
    def __init__(self, routing_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Bypass & routing"))
        self.resize(820, 660)
        self.page = RoutingPage(routing_cfg, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.page)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btn_save = buttons.button(QDialogButtonBox.Save)
        self.btn_save.setText(tr("Save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        self.btn_save.setDefault(True)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.page.applied.connect(lambda _cfg: self.accept())

    def _save(self) -> None:
        if self._busy:
            return
        self.page.apply()

    def __getattr__(self, name):
        return getattr(self.page, name)
