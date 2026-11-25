"""MASQUE editor panel: H2/H3, masked private key, WARP identity import.

Kept in its own module so the profile dialog only has to show/hide it and
copy a few fields on save. The WARP identity helper lives in
core.masque_identity (worker 2); it is imported lazily so the panel still
builds before that dependency is cherry-picked.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from ..i18n import tr
from .help import set_help

_HTTP_VERSIONS = ["h2", "h3"]


class MasquePanel(QGroupBox):
    """The MASQUE-specific rows. The dialog reads/writes the f_* fields."""

    def __init__(self, parent=None) -> None:
        super().__init__(tr("MASQUE"), parent)

        self.f_http_version = QComboBox()
        self.f_http_version.addItems(_HTTP_VERSIONS)
        self.f_private_key = QLineEdit()
        self.f_private_key.setEchoMode(QLineEdit.Password)
        self.f_public_key = QLineEdit()
        self.f_addresses = QLineEdit()
        self.f_remote_dns = QLineEdit()
        # Technical values (keys, IPs) stay LTR inside the RTL layout.
        for f in (self.f_private_key, self.f_public_key,
                  self.f_addresses, self.f_remote_dns):
            f.setLayoutDirection(Qt.LeftToRight)

        self.btn_import = QPushButton(tr("Import identity…"))
        self.btn_import.clicked.connect(self._import_identity)

        form = QFormLayout(self)
        form.addRow(tr("HTTP version"), self.f_http_version)
        form.addRow(tr("Private key"), self.f_private_key)
        form.addRow(tr("Public key"), self.f_public_key)
        form.addRow(tr("Tunnel addresses"), self.f_addresses)
        form.addRow(tr("Remote DNS"), self.f_remote_dns)
        row = QHBoxLayout()
        row.addWidget(self.btn_import)
        row.addStretch(1)
        form.addRow(row)

        set_help(self.f_http_version,
                 tr("The MASQUE carrier: h2 (HTTP/2) or h3 (HTTP/3)."),
                 tr("Pick the one your endpoint answers on."))
        set_help(self.f_private_key,
                 tr("Your P-256 device private key. Masked; never shown in "
                    "errors or logs."),
                 tr("Paste it from your WARP identity."))
        set_help(self.f_public_key,
                 tr("The endpoint's P-256 public key."),
                 tr("Paste it exactly as given."))
        set_help(self.f_addresses,
                 tr("The tunnel's IP addresses, comma or newline separated."),
                 tr("162.158.74.187/32, 2606:4700::/48"))
        set_help(self.f_remote_dns,
                 tr("Literal IP addresses to resolve through the tunnel."),
                 tr("1.1.1.1"))
        set_help(self.btn_import,
                 tr("Paste a WARP identity JSON to fill the keys and "
                    "addresses."),
                 tr("Copy the identity block your provider exported."))

    def load(self, p) -> None:
        # getattr so the panel builds before worker 1 adds the fields to
        # Profile (they default to "" once present).
        version = getattr(p, "masque_http_version", "")
        self.f_http_version.setCurrentText(version if version in _HTTP_VERSIONS else "h2")
        self.f_private_key.setText(getattr(p, "masque_private_key", ""))
        self.f_public_key.setText(getattr(p, "masque_public_key", ""))
        self.f_addresses.setText(getattr(p, "masque_addresses", ""))
        self.f_remote_dns.setText(getattr(p, "masque_remote_dns", ""))

    def apply(self, p) -> None:
        p.masque_http_version = self.f_http_version.currentText()
        p.masque_private_key = self.f_private_key.text().strip()
        p.masque_public_key = self.f_public_key.text().strip()
        p.masque_addresses = self.f_addresses.text().strip()
        p.masque_remote_dns = self.f_remote_dns.text().strip()

    def _import_identity(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getMultiLineText(
            self, tr("Import identity"),
            tr("Paste the WARP identity JSON:"), "")
        if not ok or not text.strip():
            return
        try:
            from ..core import masque_identity
            identity = masque_identity.parse_identity(text)
            fields = masque_identity.profile_fields(identity)
        except Exception:
            # The helper's own message may echo the pasted secret, so a fixed
            # string is shown instead of the exception text.
            QMessageBox.warning(self, tr("Import identity"),
                                tr("That identity could not be read."))
            return
        self.f_private_key.setText(fields.get("masque_private_key", ""))
        self.f_public_key.setText(fields.get("masque_public_key", ""))
        self.f_addresses.setText(fields.get("masque_addresses", ""))
