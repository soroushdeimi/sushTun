"""Import, profile editor and settings dialogs."""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import importer
from ..core.profiles import Profile

_NETWORKS = ["tcp", "ws", "grpc", "h2", "kcp", "quic"]
_SECURITIES = ["none", "tls", "reality"]
_PROTOCOLS = ["vless", "wireguard"]


class ImportDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import profiles")
        self.resize(560, 420)
        self.profiles: list[Profile] = []

        self.tabs = QTabWidget()
        self.link_edit = QPlainTextEdit()
        self.link_edit.setPlaceholderText(
            "Paste vless:// or wireguard:// links, a WireGuard .conf, or a base64 subscription…"
        )
        self.json_edit = QPlainTextEdit()
        self.json_edit.setPlaceholderText(
            "Paste a full Xray config, a WireGuard .conf, or a profile JSON…"
        )
        self.tabs.addTab(self.link_edit, "Link / Subscription")
        self.tabs.addTab(self.json_edit, "JSON")
        self.tabs.addTab(self._qr_tab(), "QR image")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    def _qr_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.qr_path = QLineEdit()
        self.qr_path.setReadOnly(True)
        pick = QPushButton("Choose image…")
        pick.clicked.connect(self._pick_qr)
        row = QHBoxLayout()
        row.addWidget(self.qr_path, 1)
        row.addWidget(pick)
        v.addWidget(QLabel("Decode a vless:// or wireguard:// link from a QR code image."))
        v.addLayout(row)
        v.addStretch(1)
        return w

    def _pick_qr(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "QR image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.qr_path.setText(path)

    def _accept(self) -> None:
        try:
            idx = self.tabs.currentIndex()
            if idx == 0:
                self.profiles = importer.parse_share_text(self.link_edit.toPlainText())
            elif idx == 1:
                self.profiles = [importer.parse_json(self.json_edit.toPlainText())]
            else:
                self.profiles = importer.parse_qr(self.qr_path.text())
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        if not self.profiles:
            QMessageBox.warning(self, "Import failed", "No valid profiles found.")
            return
        self.accept()


class ProfileEditDialog(QDialog):
    def __init__(self, profile: Profile, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit profile")
        self.resize(520, 620)
        self._profile = profile

        self.tabs = QTabWidget()
        self.tabs.addTab(self._form_tab(profile), "Form")
        self.raw = QPlainTextEdit(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
        self.tabs.addTab(self.raw, "Raw JSON")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    def _add_row(self, form: QFormLayout, text: str, widget) -> QLabel:
        lab = QLabel(text)
        form.addRow(lab, widget)
        return lab

    def _form_tab(self, p: Profile) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.f_name = QLineEdit(p.name)
        self.f_protocol = QComboBox()
        self.f_protocol.addItems(_PROTOCOLS)
        self.f_protocol.setCurrentText(p.protocol if p.protocol in _PROTOCOLS else "vless")
        self.f_address = QLineEdit(p.address)
        self.f_port = QSpinBox()
        self.f_port.setRange(1, 65535)
        self.f_port.setValue(p.port)
        self.f_id = QLineEdit(p.id)
        self.f_encryption = QLineEdit(p.encryption)
        self.f_flow = QLineEdit(p.flow)
        self.f_network = QComboBox()
        self.f_network.addItems(_NETWORKS)
        self.f_network.setCurrentText(p.network)
        self.f_security = QComboBox()
        self.f_security.addItems(_SECURITIES)
        self.f_security.setCurrentText(p.security)
        self.f_sni = QLineEdit(p.sni)
        self.f_fp = QLineEdit(p.fp)
        self.f_pbk = QLineEdit(p.pbk)
        self.f_sid = QLineEdit(p.sid)
        self.f_path = QLineEdit(p.path)
        self.f_host = QLineEdit(p.host)
        self.f_service = QLineEdit(p.service_name)
        self.f_wg_local = QLineEdit(p.wg_local_address)
        self.f_wg_psk = QLineEdit(p.wg_preshared)
        self.f_wg_reserved = QLineEdit(p.wg_reserved)
        self.f_wg_mtu = QSpinBox()
        self.f_wg_mtu.setRange(576, 1500)
        self.f_wg_mtu.setValue(int(p.wg_mtu) if p.wg_mtu else 1420)
        self.f_wg_keepalive = QSpinBox()
        self.f_wg_keepalive.setRange(0, 600)
        self.f_wg_keepalive.setValue(int(p.wg_keepalive) if p.wg_keepalive else 0)
        self.f_wg_allowed_ips = QLineEdit(p.wg_allowed_ips)
        self.f_wg_allowed_ips.setPlaceholderText("Empty = full tunnel (0.0.0.0/0, ::/0)")
        self.f_wg_endpoint_via_proxy = QCheckBox("Route WireGuard endpoint through the proxy lane")
        self.f_wg_endpoint_via_proxy.setChecked(bool(p.wg_endpoint_via_proxy))

        self._add_row(form, "Name", self.f_name)
        self._add_row(form, "Protocol", self.f_protocol)
        self._add_row(form, "Address", self.f_address)
        self._add_row(form, "Port", self.f_port)
        self._lab_id = self._add_row(form, "UUID / private key", self.f_id)
        self._lab_pbk = self._add_row(form, "Peer / Reality public key", self.f_pbk)
        self._vless_labs = [
            self._add_row(form, "Encryption", self.f_encryption),
            self._add_row(form, "Flow", self.f_flow),
            self._add_row(form, "Network", self.f_network),
            self._add_row(form, "Security", self.f_security),
            self._add_row(form, "SNI", self.f_sni),
            self._add_row(form, "Fingerprint", self.f_fp),
            self._add_row(form, "Reality sid", self.f_sid),
            self._add_row(form, "Path", self.f_path),
            self._add_row(form, "Host", self.f_host),
            self._add_row(form, "gRPC service", self.f_service),
        ]
        self._vless_fields = [
            self.f_encryption, self.f_flow, self.f_network, self.f_security,
            self.f_sni, self.f_fp, self.f_sid, self.f_path, self.f_host, self.f_service,
        ]
        self._wg_labs = [
            self._add_row(form, "Local address", self.f_wg_local),
            self._add_row(form, "Preshared key", self.f_wg_psk),
            self._add_row(form, "Reserved", self.f_wg_reserved),
            self._add_row(form, "MTU", self.f_wg_mtu),
            self._add_row(form, "Keepalive (s)", self.f_wg_keepalive),
            self._add_row(form, "Allowed IPs", self.f_wg_allowed_ips),
            self._add_row(form, "Endpoint routing", self.f_wg_endpoint_via_proxy),
        ]
        self._wg_fields = [
            self.f_wg_local, self.f_wg_psk, self.f_wg_reserved,
            self.f_wg_mtu, self.f_wg_keepalive,
            self.f_wg_allowed_ips, self.f_wg_endpoint_via_proxy,
        ]
        self.f_protocol.currentTextChanged.connect(self._sync_protocol_fields)
        self._sync_protocol_fields(self.f_protocol.currentText())
        return w

    def _sync_protocol_fields(self, protocol: str) -> None:
        wg = protocol == "wireguard"
        self._lab_id.setText("Private key" if wg else "UUID")
        self._lab_pbk.setText("Peer public key" if wg else "Reality public key")
        for lab, field in zip(self._vless_labs, self._vless_fields, strict=True):
            lab.setVisible(not wg)
            field.setVisible(not wg)
        for lab, field in zip(self._wg_labs, self._wg_fields, strict=True):
            lab.setVisible(wg)
            field.setVisible(wg)

    def result_profile(self) -> Profile:
        return self._profile

    def _save(self) -> None:
        if self.tabs.currentIndex() == 1:
            try:
                data = json.loads(self.raw.toPlainText())
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid JSON", str(exc))
                return
            data["uid"] = self._profile.uid
            self._profile = Profile.from_dict(data)
        else:
            p = self._profile
            p.name = self.f_name.text().strip() or "Profile"
            p.protocol = self.f_protocol.currentText()
            p.address = self.f_address.text().strip()
            p.port = self.f_port.value()
            p.id = self.f_id.text().strip()
            p.encryption = self.f_encryption.text().strip() or "none"
            p.flow = self.f_flow.text().strip()
            p.network = self.f_network.currentText()
            p.security = self.f_security.currentText()
            p.sni = self.f_sni.text().strip()
            p.fp = self.f_fp.text().strip()
            p.pbk = self.f_pbk.text().strip()
            p.sid = self.f_sid.text().strip()
            p.path = self.f_path.text().strip()
            p.host = self.f_host.text().strip()
            p.service_name = self.f_service.text().strip()
            p.wg_local_address = self.f_wg_local.text().strip()
            p.wg_preshared = self.f_wg_psk.text().strip()
            p.wg_reserved = self.f_wg_reserved.text().strip()
            p.wg_mtu = self.f_wg_mtu.value()
            p.wg_keepalive = self.f_wg_keepalive.value()
            p.wg_allowed_ips = self.f_wg_allowed_ips.text().strip()
            p.wg_endpoint_via_proxy = self.f_wg_endpoint_via_proxy.isChecked()
        if not self._profile.address or not self._profile.id:
            QMessageBox.warning(self, "Missing fields", "Address and UUID / private key are required.")
            return
        if self._profile.protocol == "wireguard" and not self._profile.pbk:
            QMessageBox.warning(self, "Missing fields", "WireGuard peer public key is required.")
            return
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(360, 200)
        form = QFormLayout(self)

        self.ping_target = QLineEdit(str(settings.get("ping_target", "1.1.1.1")))
        self.sample_seconds = QSpinBox()
        self.sample_seconds.setRange(1, 60)
        self.sample_seconds.setValue(int(settings.get("sample_seconds", 5)))
        form.addRow("Ping target", self.ping_target)
        form.addRow("Throughput sample (s)", self.sample_seconds)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {
            "ping_target": self.ping_target.text().strip() or "1.1.1.1",
            "sample_seconds": self.sample_seconds.value(),
        }
