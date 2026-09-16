"""Import, profile editor and settings dialogs."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import autostart, coreopts, importer, render, xraycheck
from ..core import backup as backup_mod
from ..core import geo as geo_mod
from ..core import settings as app_settings
from ..core.outbounds.hysteria2 import normalize_ports
from ..core.profiles import Profile, normalize_pcs, valid_pcs
from ..core.subscription import DEFAULT_USER_AGENT, Subscription
from ..i18n import tr
from .rule_editor import CollapsibleSection
from .workers import Worker

_NETWORKS = ["tcp", "ws", "grpc", "h2", "kcp", "quic", "xhttp", "httpupgrade"]
_SECURITIES = ["none", "tls", "reality"]
_PROTOCOLS = ["vless", "vmess", "trojan", "shadowsocks", "hysteria2", "wireguard"]
_VMESS_SECURITIES = ["auto", "aes-128-gcm", "chacha20-poly1305", "none", "zero"]
_SS_METHODS = [
    "aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305",
    "none",
]

# A placeholder profile for validating candidate settings before saving them
# -- security=tls so fragment/mux eligibility is actually exercised when a
# Save turns either on. No live server is ever dialed; this only runs
# `xray run -test` against a throwaway config.
_SETTINGS_CHECK_PROFILE = Profile(
    name="settings check", protocol="vless", address="203.0.113.1", port=443,
    id="11111111-1111-1111-1111-111111111111", encryption="none",
    network="tcp", security="tls", sni="settings-check.invalid",
)


class ImportDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Import profiles"))
        self.resize(560, 420)
        self.profiles: list[Profile] = []

        self.tabs = QTabWidget()
        self.link_edit = QPlainTextEdit()
        self.link_edit.setPlaceholderText(tr(
            "Paste vless:// or wireguard:// links, a WireGuard .conf, or a base64 subscription…"
        ))
        self.link_edit.setLayoutDirection(Qt.LeftToRight)
        self.json_edit = QPlainTextEdit()
        self.json_edit.setPlaceholderText(
            tr("Paste a full Xray config, a WireGuard .conf, or a profile JSON…")
        )
        self.json_edit.setLayoutDirection(Qt.LeftToRight)
        self.tabs.addTab(self.link_edit, tr("Link / Subscription"))
        self.tabs.addTab(self.json_edit, "JSON")
        self.tabs.addTab(self._qr_tab(), tr("QR image"))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        # Qt's own standard-button text isn't translated by this app's i18n
        # (that needs a bundled Qt translation file, out of scope here) --
        # overridden explicitly instead.
        buttons.button(QDialogButtonBox.Ok).setText(tr("OK"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        ok_btn.setDefault(True)
        ok_btn.setAutoDefault(True)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

        # Qt falls back to the first autoDefault button in tab order when a
        # dialog is shown and focus lands elsewhere (e.g. the QR tab's Choose
        # image button -- this fails before reaching the QLineEdit as well);
        # keep OK the single autoDefault so Enter always means "OK".
        for btn in self.findChildren(QPushButton):
            if btn is not ok_btn:
                btn.setAutoDefault(False)

    def _qr_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.qr_path = QLineEdit()
        self.qr_path.setReadOnly(True)
        self.qr_path.setLayoutDirection(Qt.LeftToRight)
        pick = QPushButton(tr("Choose image…"))
        pick.clicked.connect(self._pick_qr)
        row = QHBoxLayout()
        row.addWidget(self.qr_path, 1)
        row.addWidget(pick)
        v.addWidget(QLabel(tr("Decode a vless:// or wireguard:// link from a QR code image.")))
        v.addLayout(row)
        v.addStretch(1)
        return w

    def _pick_qr(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("QR image"), "", "Images (*.png *.jpg *.jpeg *.bmp)"
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
            # importer's exceptions carry Xray/parsing-library text -- stays
            # in English, same as any other raw error from underlying code.
            QMessageBox.warning(self, tr("Import failed"), str(exc))
            return
        if not self.profiles:
            QMessageBox.warning(self, tr("Import failed"), tr("No valid profiles found."))
            return
        self.accept()


class ProfileEditDialog(QDialog):
    def __init__(self, profile: Profile, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Edit profile"))
        self.resize(520, 620)
        self._profile = profile

        self.tabs = QTabWidget()
        self.tabs.addTab(self._form_tab(profile), tr("Form"))
        self.raw = QPlainTextEdit(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
        self.raw.setLayoutDirection(Qt.LeftToRight)
        self.tabs.addTab(self.raw, tr("Raw JSON"))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr("Save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.button(QDialogButtonBox.Save).setDefault(True)
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
        outer = QVBoxLayout(w)
        form = QFormLayout()
        outer.addLayout(form)
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
        self.f_vmess_security = QComboBox()
        self.f_vmess_security.addItems(_VMESS_SECURITIES)
        self.f_vmess_security.setCurrentText(
            p.vmess_security if p.vmess_security in _VMESS_SECURITIES else "auto")
        self.f_ss_method = QComboBox()
        self.f_ss_method.addItems(_SS_METHODS)
        if p.ss_method in _SS_METHODS:
            self.f_ss_method.setCurrentText(p.ss_method)
        self.f_network = QComboBox()
        self.f_network.addItems(_NETWORKS)
        self.f_network.setCurrentText(p.network)
        self.f_security = QComboBox()
        self.f_security.addItems(_SECURITIES)
        self.f_security.setCurrentText(p.security)
        self.f_sni = QLineEdit(p.sni)
        self.f_fp = QLineEdit(p.fp)
        self.f_alpn = QLineEdit(p.alpn)
        self.f_pbk = QLineEdit(p.pbk)
        self.f_sid = QLineEdit(p.sid)
        self.f_spx = QLineEdit(p.spx)
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
        self.f_hy2_pcs = QLineEdit(p.pcs)
        self.f_hy2_obfs_password = QLineEdit(p.hy2_obfs_password)
        self.f_hy2_ports = QLineEdit(p.hy2_ports)
        self.f_hy2_ports.setPlaceholderText("20000-30000")
        self.f_hy2_hop_interval = QSpinBox()
        self.f_hy2_hop_interval.setRange(0, 3600)
        self.f_hy2_hop_interval.setSpecialValueText(tr("Default"))
        self.f_hy2_hop_interval.setToolTip(
            tr("0 lets Xray pick its own default. Otherwise 5-3600 seconds."))
        self.f_hy2_hop_interval.setValue(
            int(p.hy2_hop_interval) if p.hy2_hop_interval.isdigit() else 0)
        _hy2_mbps_tip = tr("Leave 0 to let the congestion control pick (BBR).")
        self.f_hy2_up_mbps = QSpinBox()
        self.f_hy2_up_mbps.setRange(0, 100000)
        self.f_hy2_up_mbps.setValue(int(p.hy2_up_mbps) if p.hy2_up_mbps else 0)
        self.f_hy2_up_mbps.setToolTip(_hy2_mbps_tip)
        self.f_hy2_down_mbps = QSpinBox()
        self.f_hy2_down_mbps.setRange(0, 100000)
        self.f_hy2_down_mbps.setValue(int(p.hy2_down_mbps) if p.hy2_down_mbps else 0)
        self.f_hy2_down_mbps.setToolTip(_hy2_mbps_tip)

        # Technical values (raw identifiers, keys, hosts) never mirror even
        # in an RTL layout -- only f_name (a freeform display name) doesn't
        # get this.
        for f in (self.f_address, self.f_id, self.f_encryption, self.f_flow, self.f_sni,
                 self.f_fp, self.f_alpn, self.f_pbk, self.f_sid, self.f_spx, self.f_path,
                 self.f_host, self.f_service, self.f_wg_local, self.f_wg_psk,
                 self.f_wg_reserved, self.f_hy2_pcs, self.f_hy2_obfs_password,
                 self.f_hy2_ports):
            f.setLayoutDirection(Qt.LeftToRight)

        self._add_row(form, tr("Name"), self.f_name)
        self._add_row(form, tr("Protocol"), self.f_protocol)
        self._add_row(form, tr("Address"), self.f_address)
        self._add_row(form, tr("Port"), self.f_port)
        self._lab_id = self._add_row(form, tr("UUID / private key"), self.f_id)
        self._lab_pbk = self._add_row(form, tr("Peer / Reality public key"), self.f_pbk)
        lab_vmess_sec = self._add_row(form, tr("VMess security"), self.f_vmess_security)
        lab_ss_method = self._add_row(form, tr("Method"), self.f_ss_method)
        lab_encryption = self._add_row(form, tr("Encryption"), self.f_encryption)
        lab_flow = self._add_row(form, tr("Flow"), self.f_flow)
        lab_network = self._add_row(form, tr("Network"), self.f_network)
        lab_security = self._add_row(form, tr("Security"), self.f_security)
        lab_sni = self._add_row(form, "SNI", self.f_sni)
        lab_fp = self._add_row(form, tr("Fingerprint"), self.f_fp)
        lab_alpn = self._add_row(form, "ALPN", self.f_alpn)
        lab_sid = self._add_row(form, tr("Reality sid"), self.f_sid)
        lab_spx = self._add_row(form, tr("Reality spiderX"), self.f_spx)
        lab_path = self._add_row(form, tr("Path"), self.f_path)
        lab_host = self._add_row(form, tr("Host"), self.f_host)
        lab_service = self._add_row(form, tr("gRPC service"), self.f_service)
        lab_hy2_pcs = self._add_row(form, tr("Pinned cert SHA-256"), self.f_hy2_pcs)
        lab_hy2_obfs = self._add_row(form, tr("Obfuscation password"), self.f_hy2_obfs_password)

        self._wg_labs = [
            self._add_row(form, tr("Local address"), self.f_wg_local),
            self._add_row(form, tr("Preshared key"), self.f_wg_psk),
            self._add_row(form, tr("Reserved"), self.f_wg_reserved),
            self._add_row(form, "MTU", self.f_wg_mtu),
            self._add_row(form, tr("Keepalive (s)"), self.f_wg_keepalive),
        ]
        self._wg_fields = [
            self.f_wg_local, self.f_wg_psk, self.f_wg_reserved,
            self.f_wg_mtu, self.f_wg_keepalive,
        ]

        self.f_header_type = QLineEdit(p.header_type)
        self.f_xhttp_mode = QLineEdit(p.xhttp_mode)
        self.f_xhttp_extra = QLineEdit(p.xhttp_extra)
        self.f_xhttp_extra.setPlaceholderText('{"headers": {"X-Extra": "1"}}')
        self.f_ech = QLineEdit(p.ech)
        self.f_pcs = QLineEdit(p.pcs)
        self.f_vcn = QLineEdit(p.vcn)
        for f in (self.f_header_type, self.f_xhttp_mode, self.f_xhttp_extra,
                 self.f_ech, self.f_pcs, self.f_vcn):
            f.setLayoutDirection(Qt.LeftToRight)

        adv_widget = QWidget()
        adv_form = QFormLayout(adv_widget)
        adv_form.setContentsMargins(0, 4, 0, 0)
        lab_header_type = self._add_row(adv_form, tr("Header type"), self.f_header_type)
        lab_xhttp_mode = self._add_row(adv_form, "xhttp mode", self.f_xhttp_mode)
        lab_xhttp_extra = self._add_row(adv_form, tr("xhttp extra (JSON)"), self.f_xhttp_extra)
        lab_ech = self._add_row(adv_form, tr("ECH config list"), self.f_ech)
        lab_pcs = self._add_row(adv_form, tr("Pinned cert SHA-256"), self.f_pcs)
        lab_vcn = self._add_row(adv_form, tr("Verify cert name"), self.f_vcn)
        lab_hy2_ports = self._add_row(adv_form, tr("Port-hopping range"), self.f_hy2_ports)
        lab_hy2_interval = self._add_row(adv_form, tr("Hop interval (s)"), self.f_hy2_hop_interval)
        lab_hy2_up = self._add_row(adv_form, "Up Mbps", self.f_hy2_up_mbps)
        lab_hy2_down = self._add_row(adv_form, "Down Mbps", self.f_hy2_down_mbps)

        # allow_insecure has no editor control any more: the bundled Xray
        # binary hard-refuses "allowInsecure" now (see
        # core/outbounds/_common.py), so a checkbox for it would silently do
        # nothing -- worse than not offering it. The field itself, and its
        # import/share round-trip, are untouched; this just surfaces it.
        self.insecure_note = QLabel(tr(
            "This server's link asks to skip certificate checks. This Xray "
            "version no longer allows that — pin the certificate's SHA-256 "
            "instead."
        ))
        self.insecure_note.setObjectName("Muted")
        self.insecure_note.setWordWrap(True)
        self.insecure_note.setVisible(bool(p.allow_insecure))
        adv_form.addRow(self.insecure_note)

        self._advanced = CollapsibleSection(tr("Advanced"), adv_widget)
        outer.addWidget(self._advanced)
        if p.allow_insecure:
            self._advanced.set_expanded(True)

        def wg() -> bool:
            return self.f_protocol.currentText() == "wireguard"

        def vless() -> bool:
            return self.f_protocol.currentText() == "vless"

        def vmess() -> bool:
            return self.f_protocol.currentText() == "vmess"

        def ss() -> bool:
            return self.f_protocol.currentText() == "shadowsocks"

        def hysteria2() -> bool:
            return self.f_protocol.currentText() == "hysteria2"

        def stream() -> bool:
            return not wg() and not hysteria2()

        def is_reality() -> bool:
            return stream() and self.f_security.currentText() == "reality"

        def is_tls_or_reality() -> bool:
            return stream() and self.f_security.currentText() in ("tls", "reality")

        def sni_visible() -> bool:
            return is_tls_or_reality() or hysteria2()

        def is_tls() -> bool:
            return stream() and self.f_security.currentText() == "tls"

        def is_grpc() -> bool:
            return stream() and self.f_network.currentText() == "grpc"

        def is_xhttp() -> bool:
            return stream() and self.f_network.currentText() == "xhttp"

        def is_tcp() -> bool:
            return stream() and self.f_network.currentText() == "tcp"

        def has_path_host() -> bool:
            if not stream():
                return False
            if self.f_network.currentText() in ("ws", "httpupgrade", "xhttp", "h2"):
                return True
            return (self.f_network.currentText() == "tcp"
                    and self.f_header_type.text().strip() == "http")

        self._pbk_visible = lambda: wg() or is_reality()
        self._visibility_rules = [
            (lab_vmess_sec, self.f_vmess_security, vmess),
            (lab_ss_method, self.f_ss_method, ss),
            (lab_encryption, self.f_encryption, vless),
            (lab_flow, self.f_flow, vless),
            (lab_network, self.f_network, stream),
            (lab_security, self.f_security, stream),
            (lab_sni, self.f_sni, sni_visible),
            (lab_fp, self.f_fp, is_tls_or_reality),
            (lab_alpn, self.f_alpn, is_tls),
            (lab_sid, self.f_sid, is_reality),
            (lab_spx, self.f_spx, is_reality),
            (lab_path, self.f_path, has_path_host),
            (lab_host, self.f_host, has_path_host),
            (lab_service, self.f_service, is_grpc),
            (lab_header_type, self.f_header_type, is_tcp),
            (lab_xhttp_mode, self.f_xhttp_mode, is_xhttp),
            (lab_xhttp_extra, self.f_xhttp_extra, is_xhttp),
            (lab_ech, self.f_ech, is_tls),
            (lab_pcs, self.f_pcs, is_tls),
            (lab_vcn, self.f_vcn, is_tls),
            (lab_hy2_pcs, self.f_hy2_pcs, hysteria2),
            (lab_hy2_obfs, self.f_hy2_obfs_password, hysteria2),
            (lab_hy2_ports, self.f_hy2_ports, hysteria2),
            (lab_hy2_interval, self.f_hy2_hop_interval, hysteria2),
            (lab_hy2_up, self.f_hy2_up_mbps, hysteria2),
            (lab_hy2_down, self.f_hy2_down_mbps, hysteria2),
        ]

        for combo in (self.f_protocol, self.f_network, self.f_security):
            combo.currentTextChanged.connect(self._sync_field_visibility)
        self.f_header_type.textChanged.connect(self._sync_field_visibility)
        self._sync_field_visibility()
        return w

    def _sync_field_visibility(self, *_args) -> None:
        protocol = self.f_protocol.currentText()
        wg = protocol == "wireguard"
        self._lab_id.setText(tr("Private key") if wg else tr("Password") if protocol in
                             ("trojan", "shadowsocks", "hysteria2") else "UUID")
        self._lab_pbk.setText(tr("Peer public key") if wg else tr("Reality public key"))
        pbk_visible = self._pbk_visible()
        self._lab_pbk.setVisible(pbk_visible)
        self.f_pbk.setVisible(pbk_visible)
        for lab, field, rule in self._visibility_rules:
            visible = rule()
            lab.setVisible(visible)
            field.setVisible(visible)
        for lab, field in zip(self._wg_labs, self._wg_fields, strict=True):
            lab.setVisible(wg)
            field.setVisible(wg)
        self._advanced.setVisible(not wg)

    def result_profile(self) -> Profile:
        return self._profile

    def _save(self) -> None:
        if self.tabs.currentIndex() == 1:
            try:
                data = json.loads(self.raw.toPlainText())
            except ValueError as exc:
                # Python's own JSON parser message -- stays in English.
                QMessageBox.warning(self, tr("Invalid JSON"), str(exc))
                return
            data["uid"] = self._profile.uid
            self._profile = Profile.from_dict(data)
        else:
            xhttp_extra = self.f_xhttp_extra.text().strip()
            if xhttp_extra:
                try:
                    parsed = json.loads(xhttp_extra)
                except ValueError:
                    parsed = None
                if not isinstance(parsed, dict):
                    QMessageBox.warning(self, tr("Invalid xhttp extra"),
                                        tr("xhttp extra must be a JSON object, e.g. "
                                          '{"headers": {"X-Extra": "1"}}.'))
                    return
            hy2_ports = self.f_hy2_ports.text().strip()
            if hy2_ports and normalize_ports(hy2_ports) is None:
                QMessageBox.warning(self, tr("Invalid port range"),
                                    tr("Port-hopping range must look like 20000-30000 "
                                      "(or a comma-separated list of ranges/ports), "
                                      "with every port 1-65535."))
                return
            pcs_widget = (self.f_hy2_pcs if self.f_protocol.currentText() == "hysteria2"
                         else self.f_pcs)
            pcs_raw = pcs_widget.text().strip()
            if pcs_raw and not valid_pcs(pcs_raw):
                QMessageBox.warning(self, tr("Invalid pinned certificate"),
                                    tr("Pinned cert SHA-256 must be 64 hex characters "
                                      "(colons and spaces are fine and will be removed)."))
                return
            p = self._profile
            # A stored default name (like a new rule set's "New set"), not
            # UI chrome -- left untranslated for the same reason those are.
            p.name = self.f_name.text().strip() or "Profile"
            p.protocol = self.f_protocol.currentText()
            p.address = self.f_address.text().strip()
            p.port = self.f_port.value()
            p.id = self.f_id.text().strip()
            p.encryption = self.f_encryption.text().strip() or "none"
            p.flow = self.f_flow.text().strip()
            p.vmess_security = self.f_vmess_security.currentText()
            p.ss_method = self.f_ss_method.currentText()
            p.network = self.f_network.currentText()
            p.security = self.f_security.currentText()
            p.sni = self.f_sni.text().strip()
            p.fp = self.f_fp.text().strip()
            p.alpn = self.f_alpn.text().strip()
            p.pbk = self.f_pbk.text().strip()
            p.sid = self.f_sid.text().strip()
            p.spx = self.f_spx.text().strip()
            p.path = self.f_path.text().strip()
            p.host = self.f_host.text().strip()
            p.service_name = self.f_service.text().strip()
            p.header_type = self.f_header_type.text().strip()
            p.xhttp_mode = self.f_xhttp_mode.text().strip()
            p.xhttp_extra = xhttp_extra
            # allow_insecure has no editor control -- never touched here, so
            # a profile that had it set keeps it set (see _form_tab).
            p.ech = self.f_ech.text().strip()
            # pcs has two editors -- the shared Advanced one, and a
            # dedicated main-form one for hysteria2 -- since only one is
            # ever visible, whichever matches the chosen protocol wins.
            # Normalized above (checked valid there too): "AB:CD:..." ->
            # unbroken lowercase hex, what Xray's own pin comparison wants.
            p.pcs = normalize_pcs(pcs_raw)
            p.vcn = self.f_vcn.text().strip()
            p.hy2_obfs_password = self.f_hy2_obfs_password.text().strip()
            # Already validated above -- normalize_ports can't return None
            # here for a non-empty hy2_ports, since we'd have refused Save.
            p.hy2_ports = normalize_ports(hy2_ports) if hy2_ports else ""
            p.hy2_hop_interval = (str(self.f_hy2_hop_interval.value())
                                  if self.f_hy2_hop_interval.value() else "")
            p.hy2_up_mbps = self.f_hy2_up_mbps.value()
            p.hy2_down_mbps = self.f_hy2_down_mbps.value()
            p.wg_local_address = self.f_wg_local.text().strip()
            p.wg_preshared = self.f_wg_psk.text().strip()
            p.wg_reserved = self.f_wg_reserved.text().strip()
            p.wg_mtu = self.f_wg_mtu.value()
            p.wg_keepalive = self.f_wg_keepalive.value()
        if not self._profile.address or not self._profile.id:
            QMessageBox.warning(self, tr("Missing fields"),
                                tr("Address and UUID / private key are required."))
            return
        if self._profile.protocol == "wireguard" and not self._profile.pbk:
            QMessageBox.warning(self, tr("Missing fields"),
                                tr("WireGuard peer public key is required."))
            return
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Settings"))
        outer = QVBoxLayout(self)

        content = QWidget()
        layout = QVBoxLayout(content)
        form = QFormLayout()
        layout.addLayout(form)

        self.ping_target = QLineEdit(str(settings.get("ping_target", "1.1.1.1")))
        self.ping_target.setLayoutDirection(Qt.LeftToRight)
        self.sample_seconds = QSpinBox()
        self.sample_seconds.setRange(1, 60)
        self.sample_seconds.setValue(int(settings.get("sample_seconds", 5)))
        self.tun_mtu = QSpinBox()
        self.tun_mtu.setRange(576, 9000)
        self.tun_mtu.setValue(int(settings.get("tun_mtu", 1420)))
        self.tun_mtu.setToolTip(tr(
            "Tunnel MTU. Lower leaves more headroom for encapsulation; "
            "higher reduces per-packet overhead. 1420 is a safe default."
        ))
        self.log_level = QComboBox()
        self.log_level.addItems(app_settings.LOG_LEVELS)
        current = str(settings.get("log_level", "warning"))
        if current in app_settings.LOG_LEVELS:
            self.log_level.setCurrentText(current)

        self.check_updates = QCheckBox(tr("Check for updates"))
        self.check_updates.setChecked(bool((settings.get("updates") or {}).get("check", True)))
        self._updates_extra = dict(settings.get("updates") or {})

        self.language = QComboBox()
        self.language.addItem("English", "en")
        self.language.addItem("فارسی", "fa")
        self._language_was = settings.get("language") or "en"
        idx = self.language.findData(self._language_was)
        self.language.setCurrentIndex(idx if idx >= 0 else 0)

        form.addRow(tr("Ping target"), self.ping_target)
        form.addRow(tr("Throughput sample (s)"), self.sample_seconds)
        form.addRow(tr("Tunnel MTU"), self.tun_mtu)
        form.addRow(tr("Xray log level"), self.log_level)
        form.addRow(tr("Language"), self.language)
        form.addRow(self.check_updates)

        # -- Geo data ---------------------------------------------------
        geo_cfg = settings.get("geo") or {}
        self._last_update = geo_cfg.get("last_update", 0)
        self._geo_busy = False
        self._geo_updated = False
        self.pool = QThreadPool.globalInstance()
        self._workers: set = set()

        geo_group = QGroupBox(tr("Geo data"))
        geo_form = QFormLayout(geo_group)

        self.geo_source = QComboBox()
        self.geo_source.addItems(list(geo_mod.SOURCES))
        current_source = str(geo_cfg.get("source", ""))
        if current_source in geo_mod.SOURCES:
            self.geo_source.setCurrentText(current_source)
        geo_form.addRow(tr("Source"), self.geo_source)

        update_row = QHBoxLayout()
        self.btn_geo_update = QPushButton(tr("Update now"))
        self.btn_geo_update.clicked.connect(self._update_geo_now)
        self.geo_status = QLabel(self._format_last_update())
        self.geo_status.setObjectName("Muted")
        self.geo_status.setWordWrap(True)
        update_row.addWidget(self.btn_geo_update)
        update_row.addWidget(self.geo_status, 1)
        geo_form.addRow(update_row)

        self.geo_auto_hours = QSpinBox()
        self.geo_auto_hours.setRange(0, 168)
        self.geo_auto_hours.setValue(int(geo_cfg.get("auto_update_hours", 0)))
        self.geo_auto_hours.setSpecialValueText(tr("Off"))
        geo_form.addRow(tr("Auto-update every (hours)"), self.geo_auto_hours)

        layout.addWidget(geo_group)

        # -- Startup ------------------------------------------------------
        startup_cfg = settings.get("startup") or {}
        startup_group = QGroupBox(tr("Startup"))
        startup_form = QFormLayout(startup_group)
        self._autostart_ok, autostart_reason = autostart.is_supported()
        self.start_on_login = QCheckBox(tr("Start sushTun when I log in"))
        self.start_on_login.setChecked(bool(startup_cfg.get("start_on_login")))
        self.start_on_login.setEnabled(self._autostart_ok)
        if not self._autostart_ok:
            # core.autostart.is_supported() returns one of a small fixed set
            # of English reasons; tr() translates it when known, else falls
            # back to the English text unchanged.
            self.start_on_login.setToolTip(tr(autostart_reason))
        startup_form.addRow(self.start_on_login)
        self.start_minimized = QCheckBox(tr("Start minimized to the tray"))
        self.start_minimized.setChecked(bool(startup_cfg.get("start_minimized")))
        startup_form.addRow(self.start_minimized)
        self.auto_connect = QCheckBox(tr("Connect automatically on start"))
        self.auto_connect.setChecked(bool(startup_cfg.get("auto_connect")))
        startup_form.addRow(self.auto_connect)
        layout.addWidget(startup_group)
        self._start_on_login_was = self.start_on_login.isChecked()

        # -- Backup & restore ----------------------------------------------
        backup_group = QGroupBox(tr("Backup && restore"))
        backup_layout = QVBoxLayout(backup_group)
        backup_warning = QLabel(tr(
            "A backup file contains your server passwords in plain text — "
            "store and share it carefully."))
        backup_warning.setObjectName("Muted")
        backup_warning.setWordWrap(True)
        backup_layout.addWidget(backup_warning)
        backup_row = QHBoxLayout()
        self.btn_backup = QPushButton(tr("Back up…"))
        self.btn_backup.clicked.connect(self._backup_now)
        self.btn_restore = QPushButton(tr("Restore…"))
        self.btn_restore.clicked.connect(self._restore_now)
        backup_row.addWidget(self.btn_backup)
        backup_row.addWidget(self.btn_restore)
        backup_layout.addLayout(backup_row)
        layout.addWidget(backup_group)
        self._restored = False
        self._backup_busy = False

        # -- Advanced (Phase 5 core options) -----------------------------
        core_cfg = settings.get("core") or {}
        frag_cfg = core_cfg.get("fragment") or {}
        mux_cfg = core_cfg.get("mux") or {}
        sniff_cfg = core_cfg.get("sniffing") or {}

        adv_widget = QWidget()
        adv_layout = QVBoxLayout(adv_widget)
        adv_layout.setContentsMargins(0, 4, 0, 0)

        frag_group = QGroupBox(tr("Anti-filter"))
        frag_form = QFormLayout(frag_group)
        self.frag_enabled = QCheckBox(tr("Enabled"))
        self.frag_enabled.setChecked(bool(frag_cfg.get("enabled")))
        frag_form.addRow(self.frag_enabled)
        self.frag_packets = QLineEdit(str(frag_cfg.get("packets") or "tlshello"))
        self.frag_packets.setLayoutDirection(Qt.LeftToRight)
        frag_form.addRow(tr("Packets"), self.frag_packets)
        self.frag_length = QLineEdit(str(frag_cfg.get("length") or "100-200"))
        self.frag_length.setLayoutDirection(Qt.LeftToRight)
        frag_form.addRow(tr("Length"), self.frag_length)
        self.frag_interval = QLineEdit(str(frag_cfg.get("interval") or "10-20"))
        self.frag_interval.setLayoutDirection(Qt.LeftToRight)
        frag_form.addRow(tr("Interval"), self.frag_interval)
        self.frag_max_split = QSpinBox()
        self.frag_max_split.setRange(0, 10000)
        self.frag_max_split.setValue(int(frag_cfg.get("max_split") or 0))
        frag_form.addRow(tr("Max split"), self.frag_max_split)
        adv_layout.addWidget(frag_group)

        mux_group = QGroupBox(tr("Multiplexing"))
        mux_form = QFormLayout(mux_group)
        self.mux_enabled = QCheckBox(tr("Enabled"))
        self.mux_enabled.setChecked(bool(mux_cfg.get("enabled")))
        mux_form.addRow(self.mux_enabled)
        self.mux_concurrency = QSpinBox()
        self.mux_concurrency.setRange(1, 1024)
        self.mux_concurrency.setValue(int(mux_cfg.get("concurrency") or 8))
        mux_form.addRow(tr("Concurrency"), self.mux_concurrency)
        self.mux_xudp_concurrency = QSpinBox()
        self.mux_xudp_concurrency.setRange(1, 1024)
        self.mux_xudp_concurrency.setValue(int(mux_cfg.get("xudp_concurrency") or 16))
        mux_form.addRow(tr("XUDP concurrency"), self.mux_xudp_concurrency)
        self.mux_xudp_udp443 = QComboBox()
        self.mux_xudp_udp443.addItems(list(coreopts.XUDP_UDP443_CHOICES))
        current_udp443 = str(mux_cfg.get("xudp_proxy_udp443") or "reject")
        if current_udp443 in coreopts.XUDP_UDP443_CHOICES:
            self.mux_xudp_udp443.setCurrentText(current_udp443)
        mux_form.addRow("XUDP UDP443", self.mux_xudp_udp443)
        adv_layout.addWidget(mux_group)

        sniff_group = QGroupBox(tr("Sniffing"))
        sniff_form = QFormLayout(sniff_group)
        self.sniff_enabled = QCheckBox(tr("Enabled"))
        self.sniff_enabled.setChecked(bool(sniff_cfg.get("enabled", True)))
        sniff_form.addRow(self.sniff_enabled)
        self.sniff_route_only = QCheckBox(tr("Route only"))
        self.sniff_route_only.setChecked(bool(sniff_cfg.get("route_only")))
        sniff_form.addRow(self.sniff_route_only)
        adv_layout.addWidget(sniff_group)

        proxy_group = QGroupBox(tr("Local proxy"))
        proxy_form = QFormLayout(proxy_group)
        self.socks_port = QSpinBox()
        self.socks_port.setRange(1024, 65535)
        self.socks_port.setValue(coreopts.valid_socks_port(core_cfg.get("socks_port")))
        proxy_form.addRow(tr("Port"), self.socks_port)
        self.allow_lan = QCheckBox(tr("Allow other devices on your network"))
        self.allow_lan.setChecked(bool(core_cfg.get("allow_lan")))
        proxy_form.addRow(self.allow_lan)
        self.lan_user = QLineEdit(str(core_cfg.get("lan_user") or ""))
        self.lan_user.setLayoutDirection(Qt.LeftToRight)
        proxy_form.addRow(tr("User"), self.lan_user)
        self.lan_pass = QLineEdit(str(core_cfg.get("lan_pass") or ""))
        self.lan_pass.setEchoMode(QLineEdit.Password)
        self.lan_pass.setLayoutDirection(Qt.LeftToRight)
        proxy_form.addRow(tr("Password"), self.lan_pass)
        self.lan_warning = QLabel(tr(
            "LAN sharing is on with no password — anyone on your network can use this proxy."))
        self.lan_warning.setObjectName("Muted")
        self.lan_warning.setWordWrap(True)
        proxy_form.addRow(self.lan_warning)
        self.allow_lan.toggled.connect(self._sync_lan_warning)
        self.lan_user.textChanged.connect(self._sync_lan_warning)
        self.lan_pass.textChanged.connect(self._sync_lan_warning)
        adv_layout.addWidget(proxy_group)

        fp_group = QGroupBox(tr("Default TLS fingerprint"))
        fp_form = QFormLayout(fp_group)
        self.default_fp = QComboBox()
        self.default_fp.addItem(tr("(off)"), "")
        for name in coreopts.DEFAULT_FP_CHOICES:
            self.default_fp.addItem(name, name)
        current_fp = str(core_cfg.get("default_fp") or "")
        self.default_fp.setCurrentIndex(max(0, self.default_fp.findData(current_fp)))
        fp_form.addRow(tr("Fingerprint"), self.default_fp)
        adv_layout.addWidget(fp_group)

        layout.addWidget(CollapsibleSection(tr("Advanced"), adv_widget))
        self._sync_lan_warning()

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, 1)

        self._busy = False
        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        outer.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btn_save = buttons.button(QDialogButtonBox.Save)
        self.btn_save.setText(tr("Save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        self.btn_save.setDefault(True)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        # The Advanced section alone can push this past 1000px, taller than
        # a small laptop screen; cap the initial height instead of letting
        # the dialog open bigger than the display, which -- unlike a window
        # -- a user cannot always resize their way out of on first open.
        width = 460
        height = 600
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            height = int(screen.availableGeometry().height() * 0.85)
        self.resize(width, height)

    def _sync_lan_warning(self) -> None:
        has_auth = bool(self.lan_user.text().strip()) and bool(self.lan_pass.text().strip())
        self.lan_warning.setVisible(self.allow_lan.isChecked() and not has_auth)

    def _format_last_update(self) -> str:
        if not self._last_update:
            return tr("Never updated")
        age_hours = (time.time() - self._last_update) / 3600
        if age_hours < 1:
            return tr("Updated {n}m ago", n=max(1, round(age_hours * 60)))
        return tr("Updated {n}h ago", n=round(age_hours))

    def _run_async(self, fn, done) -> None:
        worker = Worker(fn)

        def finish(result=None, error=None):
            self._workers.discard(worker)
            done(result=result, error=error)

        worker.signals.finished.connect(lambda r: finish(result=r))
        worker.signals.error.connect(lambda e: finish(error=e))
        self._workers.add(worker)
        self.pool.start(worker)

    def _update_geo_now(self) -> None:
        if self._geo_busy:
            return
        self._geo_busy = True
        self.btn_geo_update.setEnabled(False)
        self.geo_status.setText(tr("Updating…"))
        source = self.geo_source.currentText()

        def done(result=None, error=None):
            self._geo_busy = False
            self.btn_geo_update.setEnabled(True)
            if error:
                # geo.update()'s own error (a rejected download, a bad
                # archive) -- stays in English, same as any raw error.
                self.geo_status.setText(str(error))
                return
            self._last_update = time.time()
            self._geo_updated = True
            # The files were already swapped on disk by geo.update() -- persist
            # last_update AND the source actually used right away, rather than
            # waiting on this dialog's own Save, so both survive even if the
            # user then hits Cancel. `source` is what was actually downloaded
            # (captured before the update started), not necessarily whatever
            # the combo shows by the time it finishes.
            data = app_settings.load()
            data.setdefault("geo", {})
            data["geo"]["last_update"] = self._last_update
            data["geo"]["source"] = source
            app_settings.save(data)
            self.geo_status.setText(self._format_last_update())

        self._run_async(lambda: geo_mod.update(source), done)

    def geo_updated(self) -> bool:
        """Whether Update now succeeded while this dialog was open."""
        return self._geo_updated

    def _core_values(self) -> dict:
        return {
            "fragment": {
                "enabled": self.frag_enabled.isChecked(),
                "packets": self.frag_packets.text().strip() or "tlshello",
                "length": self.frag_length.text().strip() or "100-200",
                "interval": self.frag_interval.text().strip() or "10-20",
                "max_split": self.frag_max_split.value(),
            },
            "mux": {
                "enabled": self.mux_enabled.isChecked(),
                "concurrency": self.mux_concurrency.value(),
                "xudp_concurrency": self.mux_xudp_concurrency.value(),
                "xudp_proxy_udp443": self.mux_xudp_udp443.currentText(),
            },
            "sniffing": {
                "enabled": self.sniff_enabled.isChecked(),
                "route_only": self.sniff_route_only.isChecked(),
            },
            "socks_port": self.socks_port.value(),
            "allow_lan": self.allow_lan.isChecked(),
            "lan_user": self.lan_user.text().strip(),
            "lan_pass": self.lan_pass.text().strip(),
            "default_fp": self.default_fp.currentData() or "",
        }

    def values(self) -> dict:
        return {
            "ping_target": self.ping_target.text().strip() or "1.1.1.1",
            "sample_seconds": self.sample_seconds.value(),
            "tun_mtu": self.tun_mtu.value(),
            "log_level": self.log_level.currentText(),
            "language": self.language.currentData() or "en",
            "geo": {
                "source": self.geo_source.currentText(),
                "auto_update_hours": self.geo_auto_hours.value(),
                "last_update": self._last_update,
            },
            "core": self._core_values(),
            "startup": {
                "start_on_login": self.start_on_login.isChecked(),
                "start_minimized": self.start_minimized.isChecked(),
                "auto_connect": self.auto_connect.isChecked(),
            },
            # last_check/notified_version are not user-editable fields --
            # carried through from whatever they already were.
            "updates": {**self._updates_extra, "check": self.check_updates.isChecked()},
        }

    def restored(self) -> bool:
        """Whether Restore… succeeded while this dialog was open."""
        return self._restored

    def _backup_now(self) -> None:
        if self._backup_busy:
            return
        default_name = f"sushTun-backup-{time.strftime('%Y%m%d')}.zip"
        path, _ = QFileDialog.getSaveFileName(self, tr("Back up sushTun"), default_name,
                                              "Zip archives (*.zip)")
        if not path:
            return
        self._backup_busy = True
        self.btn_backup.setEnabled(False)

        def done(result=None, error=None):
            self._backup_busy = False
            self.btn_backup.setEnabled(True)
            if error:
                QMessageBox.warning(self, tr("Backup failed"), str(error))
                return
            QMessageBox.information(self, tr("Backup complete"), tr("Saved to {path}", path=path))

        # When elevated, backup() writes the finished zip through
        # core.userfs, which spawns a few short-lived subprocesses (each
        # with its own timeout) rather than a single instant local write --
        # off the UI thread, same as the Startup save already runs.
        self._run_async(lambda: backup_mod.backup(Path(path)), done)

    def _restore_now(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Restore sushTun backup"), "",
                                              "Zip archives (*.zip)")
        if not path:
            return
        if QMessageBox.question(
            self, tr("Restore backup"),
            tr("This replaces your current servers and settings with the backup's. Continue?"),
        ) != QMessageBox.Yes:
            return
        try:
            backup_mod.restore(Path(path))
        except (ValueError, OSError) as exc:
            # backup.restore()'s own message names the exact offending file
            # or JSON error -- stays in English, same as any raw error.
            QMessageBox.warning(self, tr("Restore failed"), str(exc))
            return
        self._restored = True
        QMessageBox.information(self, tr("Restore complete"),
                                tr("Restored. sushTun will reload your settings and servers."))

    def _save(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.btn_save.setEnabled(False)
        self.status_label.setText(tr("Validating…"))
        core_cfg = self._core_values()
        toggle_login = self.start_on_login.isChecked() != self._start_on_login_was
        want_login = self.start_on_login.isChecked()

        def work():
            text = render.build_text(
                _SETTINGS_CHECK_PROFILE, "lo", include_tun=False, core_cfg=core_cfg,
            )
            check_result = xraycheck.check_config(text)
            if check_result:
                return check_result, None
            if toggle_login:
                try:
                    (autostart.enable if want_login else autostart.disable)()
                except Exception as exc:
                    return None, str(exc)
            return None, None

        def done(result=None, error=None):
            self._busy = False
            self.btn_save.setEnabled(True)
            self.status_label.setText("")
            if error:
                QMessageBox.warning(self, tr("Validation failed"), str(error))
                return
            check_result, startup_error = result
            if check_result:
                # xraycheck.check_config's own text is Xray's raw parser
                # output -- stays in English.
                QMessageBox.warning(self, tr("Settings invalid"), check_result)
                return
            if startup_error:
                # core.autostart.enable/disable's own raised message --
                # stays in English, same as any other raw error.
                QMessageBox.warning(self, tr("Startup setting failed"), startup_error)
                return
            self._start_on_login_was = want_login
            if (self.language.currentData() or "en") != self._language_was:
                QMessageBox.information(self, tr("Language"),
                                        tr("Restart sushTun to apply the new language."))
            self.accept()

        self._run_async(work, done)


class SubscriptionEditDialog(QDialog):
    def __init__(self, sub: Subscription, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Edit subscription"))
        self.resize(420, 0)
        self._sub = sub
        # Auto-fill Name from the URL's host, same as the old bare "paste a
        # URL" Add flow -- but only until the user actually types a name of
        # their own; an existing sub's real name must never get clobbered
        # just because its URL field was touched.
        self._name_auto = sub.name in ("", "Subscription")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.f_name = QLineEdit(sub.name)
        form.addRow(tr("Name"), self.f_name)
        self.f_url = QLineEdit(sub.url)
        self.f_url.setLayoutDirection(Qt.LeftToRight)
        form.addRow("URL", self.f_url)
        self.f_enabled = QCheckBox(tr("Enabled"))
        self.f_enabled.setChecked(sub.enabled)
        form.addRow(self.f_enabled)
        self.f_auto_hours = QSpinBox()
        self.f_auto_hours.setRange(0, 168)
        self.f_auto_hours.setSpecialValueText(tr("0 (default)"))
        self.f_auto_hours.setValue(int(sub.auto_update_hours))
        form.addRow(tr("Auto-update every (hours)"), self.f_auto_hours)
        self.f_name_filter = QLineEdit(sub.name_filter)
        self.f_name_filter.setPlaceholderText(tr("Only keep servers whose name matches (regex)"))
        self.f_name_filter.setLayoutDirection(Qt.LeftToRight)
        form.addRow(tr("Name filter"), self.f_name_filter)
        self.f_user_agent = QLineEdit(sub.user_agent)
        self.f_user_agent.setPlaceholderText(DEFAULT_USER_AGENT)
        self.f_user_agent.setLayoutDirection(Qt.LeftToRight)
        form.addRow("User-Agent", self.f_user_agent)

        self.f_url.textEdited.connect(self._maybe_autofill_name)
        self.f_name.textEdited.connect(self._stop_autofill_name)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr("Save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.button(QDialogButtonBox.Save).setDefault(True)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _stop_autofill_name(self, _text: str) -> None:
        self._name_auto = False

    def _maybe_autofill_name(self, text: str) -> None:
        if not self._name_auto:
            return
        # setText() below never emits textEdited (only user typing does),
        # so this doesn't re-trigger _stop_autofill_name on itself.
        host = text.strip().split("//", 1)[-1].split("/", 1)[0]
        self.f_name.setText(host)

    def _save(self) -> None:
        url = self.f_url.text().strip()
        if not url:
            QMessageBox.warning(self, tr("Missing URL"), tr("Subscription URL is required."))
            return
        name_filter = self.f_name_filter.text().strip()
        if name_filter:
            try:
                re.compile(name_filter)
            except re.error as exc:
                # Python's own regex error message -- stays in English.
                QMessageBox.warning(self, tr("Invalid name filter"), str(exc))
                return
        self._sub.name = self.f_name.text().strip() or url
        self._sub.url = url
        self._sub.enabled = self.f_enabled.isChecked()
        self._sub.auto_update_hours = self.f_auto_hours.value()
        self._sub.name_filter = name_filter
        self._sub.user_agent = self.f_user_agent.text().strip()
        self.accept()

    def result_subscription(self) -> Subscription:
        return self._sub
