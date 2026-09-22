"""System Settings style settings window for sushTun.

Replaces the long scrolling SettingsDialog with a sidebar of topics and
a stacked widget of topic pages. All fields from SettingsDialog are
preserved. Staged edits: nothing is saved until Done is clicked.
"""
from __future__ import annotations

import copy
import ipaddress
import secrets
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core import autostart, coreopts, render, xraycheck
from ..core import backup as backup_mod
from ..core import exits as exits_mod
from ..core import forwards as forwards_mod
from ..core import geo as geo_mod
from ..core import settings as app_settings
from ..core import updates as updates_mod
from ..core.profiles import Profile
from ..i18n import ltr, tr
from .icons import icon
from .mac import InsetGroup, Switch
from .titlebar import TrafficLight, _LightGroup
from .workers import Worker

# Placeholder profile for validating candidate settings before saving
# (copied from dialogs.py to keep core/ Qt-free)
_SETTINGS_CHECK_PROFILE = Profile(
    name="settings check", protocol="vless", address="203.0.113.1", port=443,
    id="11111111-1111-1111-1111-111111111111", encryption="none",
    network="tcp", security="tls", sni="settings-check.invalid",
)

# Topic definitions: (key, label, icon_name, tile_color)
TOPICS = [
    ("general", "General", "settings", "#8e8e93"),
    ("anti-filter", "Anti-filter", "anti-filter", "#bf5af2"),
    ("local-proxy", "Local proxy", "servers", "#30d158"),
    ("geo-data", "Geo data", "routing", "#0a84ff"),
    ("hotspot", "Hotspot", "hotspot", "#34c759"),
    ("startup", "Startup", "arrow-up", "#ff9f0a"),
    ("exits", "Multi-exit port", "subscriptions", "#5e5ce6"),
    ("forwards", "Port forwarding", "activity", "#ff9f0a"),
    ("backup", "Backup", "archive", "#64d2ff"),
    ("language", "Language", "language", "#ff375f"),
]


class _IconTile(QWidget):
    """A 22px rounded-square coloured tile with a centered icon."""

    def __init__(self, icon_name: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._color = color
        self.setFixedSize(22, 22)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Colored background
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        p.drawRoundedRect(0, 0, 22, 22, 6, 6)
        # White icon centered
        pix = icon(self._icon_name, "#ffffff", 13).pixmap(13, 13)
        x = (22 - 13) // 2
        y = (22 - 13) // 2
        p.drawPixmap(x, y, pix)


class SettingsSidebarItem(QPushButton):
    """A sidebar navigation button with coloured icon tile + text."""

    def __init__(self, text: str, icon_name: str, tile_color: str, parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self._icon_name = icon_name
        self._tile_color = tile_color
        # A real child widget, positioned in resizeEvent -- re-rendering its
        # paint via QWidget.render() is not supported in PySide6.
        self._icon_tile = _IconTile(icon_name, tile_color, self)
        self._icon_tile.show()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(text)
        self.setToolTip(text)
        self.setFixedHeight(28)
        # Layout: tile (22px) + gap (8px) + text
        self._tile_x = 8
        self._text_x = 8 + 22 + 8

    def sizeHint(self):
        from PySide6.QtCore import QSize
        fm = QFontMetrics(self.font())
        text_w = fm.horizontalAdvance(self.text())
        return QSize(self._text_x + text_w + 12, 28)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        rtl = self.layoutDirection() == Qt.RightToLeft
        tile_x = w - 8 - 22 if rtl else 8
        self._icon_tile.move(tile_x, max((h - 22) // 2, 0))

    def visible_text(self) -> str:
        """The text as paintEvent will draw it (possibly elided)."""
        fm = QFontMetrics(self.font())
        if self.layoutDirection() == Qt.RightToLeft:
            avail = max(self._icon_tile.x() - 8 - 12, 0)
        else:
            avail = max(self.width() - self._text_x - 12, 0)
        return fm.elidedText(self.text(), Qt.ElideRight, avail)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background on hover/checked
        if self.isChecked() and self.isEnabled():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 26))
            p.drawRoundedRect(0, 0, w, h, 6, 6)
        elif self.underMouse() and self.isEnabled():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 15))
            p.drawRoundedRect(0, 0, w, h, 6, 6)

        # Text
        fm = QFontMetrics(self.font())
        rtl = self.layoutDirection() == Qt.RightToLeft
        text_color = QColor("#ffffff") if self.isChecked() else QColor("#dcdce0")
        if rtl:
            # The tile sits on the right; the text runs from 12px after the
            # left edge up to 8px before the tile, right-aligned.
            right = self._icon_tile.x() - 8
            avail = max(right - 12, 0)
            elided = fm.elidedText(self.text(), Qt.ElideRight, avail)
            p.setPen(text_color)
            p.drawText(right - avail, 0, avail, h,
                       Qt.AlignRight | Qt.AlignVCenter, elided)
        else:
            text_x = self._text_x
            avail = w - text_x - 12
            elided = fm.elidedText(self.text(), Qt.ElideRight, max(avail, 0))
            p.setPen(text_color)
            p.drawText(text_x, 0, avail, h, Qt.AlignLeft | Qt.AlignVCenter, elided)
        p.end()


class _GeneralPage(QWidget):
    """General settings: ping target, throughput sample, log level, MTU, check updates."""

    # The main window owns installing an update, so a found release is handed
    # up rather than acted on here.
    updateAvailable = Signal(object)

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._check_worker = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel(tr("General"))
        title.setObjectName("H1")
        layout.addWidget(title)

        group = InsetGroup(self)

        self.ping_target = QLineEdit(str(self._settings.get("ping_target", "1.1.1.1")))
        self.ping_target.setLayoutDirection(Qt.LeftToRight)
        group.add_row(tr("Ping target"), self.ping_target)

        self.sample_seconds = QSpinBox()
        self.sample_seconds.setRange(1, 60)
        self.sample_seconds.setValue(int(self._settings.get("sample_seconds", 5)))
        group.add_row(tr("Throughput sample (s)"), self.sample_seconds)

        self.tun_mtu = QSpinBox()
        self.tun_mtu.setRange(576, 9000)
        self.tun_mtu.setValue(int(self._settings.get("tun_mtu", 1420)))
        self.tun_mtu.setToolTip(tr(
            "Tunnel MTU. Lower leaves more headroom for encapsulation; "
            "higher reduces per-packet overhead. 1420 is a safe default."
        ))
        group.add_row(tr("Tunnel MTU"), self.tun_mtu)

        self.log_level = QComboBox()
        self.log_level.addItems(app_settings.LOG_LEVELS)
        current = str(self._settings.get("log_level", "warning"))
        if current in app_settings.LOG_LEVELS:
            self.log_level.setCurrentText(current)
        group.add_row(tr("Xray log level"), self.log_level)

        self.check_updates = Switch()
        self.check_updates.setChecked(bool((self._settings.get("updates") or {}).get("check", True)))
        group.add_row(tr("Check for updates"), self.check_updates)

        # The version and a way to check right now, next to the switch that
        # decides whether sushTun checks on its own: someone who has just
        # heard about a release should not have to wait a day for it.
        self.btn_check_now = QPushButton(tr("Check now"))
        self.btn_check_now.clicked.connect(self._check_now)
        self.update_status = QLabel("")
        self.update_status.setObjectName("Muted")
        self.update_status.setWordWrap(True)
        version_row = QWidget()
        vr = QHBoxLayout(version_row)
        vr.setContentsMargins(0, 0, 0, 0)
        vr.setSpacing(8)
        vr.addWidget(self.update_status, 1)
        vr.addWidget(self.btn_check_now)
        group.add_row(tr("Version {version}", version=ltr(__version__)), version_row)

        layout.addWidget(group)
        layout.addStretch(1)

    def _check_now(self) -> None:
        self.btn_check_now.setEnabled(False)
        self.update_status.setText(tr("Checking…"))
        worker = Worker(updates_mod.latest_release)
        worker.signals.finished.connect(self._on_checked)
        worker.signals.error.connect(lambda _msg: self._on_checked(None))
        self._check_worker = worker  # QRunnable is not kept alive by the pool
        QThreadPool.globalInstance().start(worker)

    def _on_checked(self, release) -> None:
        self._check_worker = None
        self.btn_check_now.setEnabled(True)
        if release is None:
            self.update_status.setText(tr("Could not reach GitHub."))
            return
        if not updates_mod.is_newer(release.tag, __version__):
            self.update_status.setText(tr("You're up to date."))
            return
        self.update_status.setText(
            tr("sushTun {tag} is available", tag=ltr(release.tag)))
        self.updateAvailable.emit(release)

    def collect(self) -> dict:
        return {
            "ping_target": self.ping_target.text().strip() or "1.1.1.1",
            "sample_seconds": self.sample_seconds.value(),
            "tun_mtu": self.tun_mtu.value(),
            "log_level": self.log_level.currentText(),
            "updates": {"check": self.check_updates.isChecked()},
        }

    def apply_to(self, target: dict) -> None:
        target.update(self.collect())


class _AntiFilterPage(QWidget):
    """Anti-filter: TLS fragment + multiplexing settings."""

    def __init__(self, core_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._core_cfg = core_cfg
        frag_cfg = core_cfg.get("fragment") or {}
        mux_cfg = core_cfg.get("mux") or {}
        self._frag_cfg = frag_cfg
        self._mux_cfg = mux_cfg
        self._sockopt_cfg = core_cfg.get("sockopt") or {}
        self._noise_cfg = core_cfg.get("udp_noise") or {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel(tr("Anti-filter"))
        title.setObjectName("H1")
        layout.addWidget(title)

        # TLS Fragment section
        frag_group = InsetGroup(self)
        self.frag_enabled = Switch()
        self.frag_enabled.setChecked(bool(self._frag_cfg.get("enabled")))
        frag_group.add_row(
            tr("Split the TLS handshake"),
            self.frag_enabled,
            tr("Try this if servers connect but sites won't load.")
        )

        self.frag_packets = QLineEdit(str(self._frag_cfg.get("packets") or "tlshello"))
        self.frag_packets.setLayoutDirection(Qt.LeftToRight)
        frag_group.add_row(tr("Packets"), self.frag_packets)

        self.frag_length = QLineEdit(str(self._frag_cfg.get("length") or "100-200"))
        self.frag_length.setLayoutDirection(Qt.LeftToRight)
        frag_group.add_row(tr("Length"), self.frag_length)

        self.frag_interval = QLineEdit(str(self._frag_cfg.get("interval") or "10-20"))
        self.frag_interval.setLayoutDirection(Qt.LeftToRight)
        frag_group.add_row(tr("Interval"), self.frag_interval)

        self.frag_max_split = QSpinBox()
        self.frag_max_split.setRange(0, 10000)
        self.frag_max_split.setValue(int(self._frag_cfg.get("max_split") or 0))
        frag_group.add_row(tr("Max split"), self.frag_max_split)

        layout.addWidget(frag_group)

        # Divider + footnote
        footnote = QLabel(tr(
            "Applies to TLS and Reality servers over TCP. The speed test uses it too, "
            "so servers that only work with it don't show as failed."
        ))
        footnote.setObjectName("Muted")
        footnote.setWordWrap(True)
        layout.addWidget(footnote)

        # Multiplexing section
        mux_group = InsetGroup(self)
        self.mux_enabled = Switch()
        self.mux_enabled.setChecked(bool(self._mux_cfg.get("enabled")))
        mux_group.add_row(tr("Multiplexing"), self.mux_enabled)

        self.mux_concurrency = QSpinBox()
        self.mux_concurrency.setRange(1, 1024)
        self.mux_concurrency.setValue(int(self._mux_cfg.get("concurrency") or 8))
        mux_group.add_row(tr("Concurrency"), self.mux_concurrency)

        self.mux_xudp_concurrency = QSpinBox()
        self.mux_xudp_concurrency.setRange(1, 1024)
        self.mux_xudp_concurrency.setValue(int(self._mux_cfg.get("xudp_concurrency") or 16))
        mux_group.add_row(tr("XUDP concurrency"), self.mux_xudp_concurrency)

        self.mux_xudp_udp443 = QComboBox()
        self.mux_xudp_udp443.addItems(list(coreopts.XUDP_UDP443_CHOICES))
        current_udp443 = str(self._mux_cfg.get("xudp_proxy_udp443") or "reject")
        if current_udp443 in coreopts.XUDP_UDP443_CHOICES:
            self.mux_xudp_udp443.setCurrentText(current_udp443)
        mux_group.add_row(tr("XUDP UDP443"), self.mux_xudp_udp443)

        layout.addWidget(mux_group)

        # TCP tuning for the connection to the server
        tcp_group = InsetGroup(self)
        self.tcp_fast_open = Switch()
        self.tcp_fast_open.setChecked(self._sockopt_cfg.get("tcp_fast_open") is True)
        tcp_group.add_row(tr("TCP Fast Open"), self.tcp_fast_open,
                          tr("Saves a round trip when opening connections."))
        self.tcp_mptcp = Switch()
        self.tcp_mptcp.setChecked(self._sockopt_cfg.get("tcp_mptcp") is True)
        tcp_group.add_row(tr("Multipath TCP"), self.tcp_mptcp,
                          tr("Falls back to normal TCP if the system can't use it."))
        # Only algorithms this kernel has: an unavailable one fails every dial.
        self.tcp_congestion = QComboBox()
        self.tcp_congestion.addItem(tr("System default"), "")
        for name in coreopts.available_tcp_congestion():
            self.tcp_congestion.addItem(name, name)
        index = self.tcp_congestion.findData(str(self._sockopt_cfg.get("tcp_congestion") or ""))
        self.tcp_congestion.setCurrentIndex(max(index, 0))
        # Windows and macOS ignore the setting, so don't offer it there.
        if self.tcp_congestion.count() > 1:
            tcp_group.add_row(tr("Congestion control"), self.tcp_congestion)
        layout.addWidget(tcp_group)

        # UDP noise before a Hysteria2 handshake
        noise_group = InsetGroup(self)
        self.noise_enabled = Switch()
        self.noise_enabled.setChecked(self._noise_cfg.get("enabled") is True)
        noise_group.add_row(tr("UDP noise"), self.noise_enabled,
                            tr("Sends a few random packets before connecting. "
                               "Hysteria2 servers only."))
        self.noise_length = QLineEdit(str(self._noise_cfg.get("length") or "10-20"))
        self.noise_length.setLayoutDirection(Qt.LeftToRight)
        noise_group.add_row(tr("Packet size"), self.noise_length)
        self.noise_delay = QLineEdit(str(self._noise_cfg.get("delay") or "10-16"))
        self.noise_delay.setLayoutDirection(Qt.LeftToRight)
        noise_group.add_row(tr("Delay (ms)"), self.noise_delay)
        layout.addWidget(noise_group)
        layout.addStretch(1)

    def collect(self) -> dict:
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
            "sockopt": {
                "tcp_fast_open": self.tcp_fast_open.isChecked(),
                "tcp_mptcp": self.tcp_mptcp.isChecked(),
                "tcp_congestion": self.tcp_congestion.currentData() or "",
            },
            "udp_noise": {
                "enabled": self.noise_enabled.isChecked(),
                "length": self.noise_length.text().strip() or "10-20",
                "delay": self.noise_delay.text().strip() or "10-16",
            },
        }

    def apply_to(self, target: dict) -> None:
        target["fragment"] = self.collect()["fragment"]
        target["mux"] = self.collect()["mux"]
        target["sockopt"] = self.collect()["sockopt"]
        target["udp_noise"] = self.collect()["udp_noise"]


class _ExitsPage(QWidget):
    """Multi-exit port: one local SOCKS port, the username picks the server.

    Off by default; see core/exits.py for what gets rendered and why any bad
    value only switches the feature off for that connection."""

    def __init__(self, exits_cfg: dict, core_cfg: dict, dns_cfg: dict,
                 profiles: list[Profile], parent=None) -> None:
        super().__init__(parent)
        self._exits_cfg = exits_cfg
        self._core_cfg = core_cfg
        self._remote_dns = bool(dns_cfg.get("remote_via_tunnel"))
        self._profiles = {p.uid: p for p in profiles}
        self._rows: list[tuple[QWidget, QLineEdit, QComboBox]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        title = QLabel(tr("Multi-exit port"))
        title.setObjectName("H1")
        layout.addWidget(title)

        cfg = self._exits_cfg
        group = InsetGroup(self)
        self.enabled = Switch()
        self.enabled.setChecked(cfg.get("enabled") is True)
        group.add_row(tr("Multi-exit port"), self.enabled,
                      tr("One local SOCKS port where the username picks the server."))
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        port = cfg.get("port")
        self.port.setValue(port if isinstance(port, int) and 1024 <= port <= 65535 else 10809)
        group.add_row(tr("Port"), self.port)
        # A password is required (the username only means something with auth),
        # so there is always one to show.
        self.password = QLineEdit(str(cfg.get("password") or "") or secrets.token_urlsafe(9))
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setLayoutDirection(Qt.LeftToRight)
        self.btn_show = QPushButton(tr("Show"))
        self.btn_show.setCheckable(True)
        self.btn_show.toggled.connect(lambda on: self.password.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        pw_row = QWidget()
        pw_layout = QHBoxLayout(pw_row)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.addWidget(self.password, 1)
        pw_layout.addWidget(self.btn_show)
        group.add_row(tr("Password"), pw_row)
        layout.addWidget(group)

        # Made before the rows: adding a row updates it.
        self.dns_warning = QLabel(tr(
            "Some exits use a host name. With remote DNS through the tunnel, they can "
            "only be reached while the main server is up."))
        self.dns_warning.setObjectName("Muted")
        self.dns_warning.setWordWrap(True)
        self._rows_box = QVBoxLayout()
        layout.addLayout(self._rows_box)
        for item in cfg.get("items") or []:
            if isinstance(item, dict):
                self._add_row(str(item.get("user") or ""), item.get("profile_uid"))
        self.btn_add = QPushButton(tr("Add exit"))
        self.btn_add.clicked.connect(lambda: self._add_row("", None))
        layout.addWidget(self.btn_add, 0, Qt.AlignLeading)

        hint = QLabel(tr("Use socks5://USERNAME:PASSWORD@127.0.0.1:PORT. TCP only."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self.dns_warning)
        self._update_warning()
        layout.addStretch(1)

    def _add_row(self, user: str, uid: str | None) -> None:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        name = QLineEdit(user)
        name.setPlaceholderText(tr("username"))
        name.setLayoutDirection(Qt.LeftToRight)
        server = QComboBox()
        for p in self._profiles.values():
            server.addItem(p.name or p.address, p.uid)
        if uid and uid not in self._profiles:
            server.addItem(tr("(missing server)"), uid)
        if uid:
            server.setCurrentIndex(max(server.findData(uid), 0))
        server.currentIndexChanged.connect(self._update_warning)
        remove = QPushButton()
        remove.setIcon(icon("close"))
        remove.setToolTip(tr("Remove exit"))
        remove.setAccessibleName(tr("Remove exit"))
        entry = (row, name, server)
        remove.clicked.connect(lambda: self._remove_row(entry))
        box.addWidget(name, 1)
        box.addWidget(server, 2)
        box.addWidget(remove)
        self._rows.append(entry)
        self._rows_box.addWidget(row)
        self._update_warning()

    def _remove_row(self, entry) -> None:
        self._rows.remove(entry)
        entry[0].setParent(None)
        self._update_warning()

    def _update_warning(self) -> None:
        def is_host(uid) -> bool:
            p = self._profiles.get(uid)
            if p is None:
                return False
            try:
                ipaddress.ip_address(p.address)
            except ValueError:
                return True
            return False
        self.dns_warning.setVisible(
            self._remote_dns and any(is_host(server.currentData()) for _r, _n, server in self._rows))

    def collect(self) -> dict:
        return {
            "enabled": self.enabled.isChecked(),
            "port": self.port.value(),
            "password": self.password.text(),
            "items": [{"user": name.text().strip(), "profile_uid": server.currentData()}
                      for _row, name, server in self._rows],
        }

    def problem(self) -> str | None:
        """Why these values can't be saved, or None. Only checked while on."""
        cfg = self.collect()
        if not cfg["enabled"]:
            return None
        why = exits_mod.port_problem(cfg["port"], self._core_cfg)
        if why is None and not cfg["password"]:
            why = "a password is required"
        if why is None:
            why = exits_mod.items_problem(cfg["items"], set(self._profiles))
        return tr("Multi-exit port: {why}", why=why) if why else None


class _HotspotPage(QWidget):
    """Hotspot: name, password and Wi-Fi options.

    Linux drives NetworkManager, so every option here is ours to set. Windows
    runs one Mobile Hotspot for the whole machine and the app rewrites its
    configuration through the same WinRT surface the Settings app uses --
    which covers the name, password, security and band, but has no notion of
    a hidden network or of keeping clients apart, so those two rows are Linux
    only."""

    def __init__(self, gateway_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._gateway_cfg = gateway_cfg
        self._win = sys.platform == "win32"
        self._editable = self._win or sys.platform.startswith("linux")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel(tr("Hotspot"))
        title.setObjectName("H1")
        layout.addWidget(title)

        cfg = self._gateway_cfg
        group = InsetGroup(self)
        self.ssid = QLineEdit(str(cfg.get("ssid") or ("" if self._win else "sushTun")))
        if self._win:
            # Empty means "leave the hotspot named the way Windows has it",
            # which beats showing a name the user never chose.
            self.ssid.setPlaceholderText(tr("Keep the name Windows already uses"))
        group.add_row(tr("Network name"), self.ssid)

        self.password = QLineEdit(str(cfg.get("password") or ""))
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setLayoutDirection(Qt.LeftToRight)
        if self._win:
            self.password.setPlaceholderText(tr("Keep the password Windows already uses"))
        self.btn_show = QPushButton(tr("Show"))
        self.btn_show.setCheckable(True)
        self.btn_show.toggled.connect(lambda on: self.password.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        self.btn_new = QPushButton(tr("New"))
        self.btn_new.setToolTip(tr("Make a new random password"))
        self.btn_new.clicked.connect(
            lambda: self.password.setText(secrets.token_urlsafe(9)))
        pw_row = QWidget()
        pw_layout = QHBoxLayout(pw_row)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.setSpacing(8)
        pw_layout.addWidget(self.password, 1)
        pw_layout.addWidget(self.btn_show)
        pw_layout.addWidget(self.btn_new)
        group.add_row(tr("Password"), pw_row)

        self.security = QComboBox()
        self.security.addItem(tr("WPA2"), "wpa2")
        self.security.addItem(tr("WPA3 (if your Wi-Fi card supports it)"), "wpa3")
        self.security.setCurrentIndex(max(self.security.findData(cfg.get("security")), 0))
        group.add_row(tr("Security"), self.security)

        self.band = QComboBox()
        self.band.addItem(tr("Automatic"), "auto")
        self.band.addItem(tr("2.4 GHz"), "bg")
        self.band.addItem(tr("5 GHz"), "a")
        self.band.setCurrentIndex(max(self.band.findData(cfg.get("band")), 0))
        group.add_row(tr("Band"), self.band,
                      None if self._win else
                      tr("While this computer is on Wi-Fi, the hotspot uses the same band."))

        # Windows' hotspot API exposes neither of these, so offering them
        # would be a switch that silently does nothing.
        self.hidden = self.isolation = None
        if not self._win:
            self.hidden = Switch()
            self.hidden.setChecked(cfg.get("hidden") is True)
            group.add_row(tr("Hide the network name"), self.hidden)

            self.isolation = Switch()
            self.isolation.setChecked(cfg.get("isolation") is True)
            group.add_row(tr("Keep devices apart"), self.isolation,
                          tr("Devices on the hotspot can't reach each other."))
        layout.addWidget(group)

        if self._win:
            note = tr("Windows applies these the next time the hotspot starts, "
                      "to its Mobile hotspot as a whole.")
        elif self._editable:
            note = tr("Changes apply the next time the hotspot starts.")
        else:
            note = tr("Sharing the tunnel over a hotspot isn't available "
                      "on this system.")
        label = QLabel(note)
        label.setObjectName("Muted")
        label.setWordWrap(True)
        layout.addWidget(label)
        group.setEnabled(self._editable)
        layout.addStretch(1)

    def problem(self) -> str | None:
        """Why these values can't be saved, or None."""
        if not self._editable:
            return None
        name = self.ssid.text().strip()
        # On Windows an empty name is a choice: keep the hotspot's own.
        if not (self._win and not name) and not 1 <= len(name.encode("utf-8")) <= 32:
            return tr("The network name must be 1 to 32 bytes long.")
        pw = self.password.text()
        # Empty is fine: a password is made the first time the hotspot starts.
        if pw and not (8 <= len(pw) <= 63 and all(" " <= ch <= "~" for ch in pw)):
            return tr("The hotspot password must be 8 to 63 plain characters (A-Z, 0-9, symbols).")
        return None

    def collect(self) -> dict:
        """The whole gateway dict: its on/off keys are kept as they are."""
        out = dict(self._gateway_cfg)
        if self._editable:
            out.update(ssid=self.ssid.text().strip(), password=self.password.text(),
                       security=self.security.currentData(), band=self.band.currentData())
        if self.hidden is not None and self.isolation is not None:
            out.update(hidden=self.hidden.isChecked(),
                       isolation=self.isolation.isChecked())
        return out


class _ForwardsPage(QWidget):
    """Port forwarding: a local port that always reaches one fixed host:port.

    Empty by default; see core/forwards.py. Each forward is checked on its own,
    and a bad or busy one is only skipped for that connection."""

    _NETWORKS = (("tcp", "TCP"), ("udp", "UDP"), ("tcp,udp", "TCP + UDP"))

    def __init__(self, forwards_cfg, core_cfg: dict, exits_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._core_cfg = core_cfg
        self._exits_cfg = exits_cfg
        self._rows: list[dict] = []
        self._build_ui(forwards_cfg if isinstance(forwards_cfg, list) else [])

    def _build_ui(self, items: list) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        title = QLabel(tr("Port forwarding"))
        title.setObjectName("H1")
        layout.addWidget(title)
        intro = QLabel(tr("Each local port always reaches one fixed address, through the "
                          "tunnel or directly."))
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._rows_box = QVBoxLayout()
        layout.addLayout(self._rows_box)
        for item in items:
            if isinstance(item, dict):
                self._add_row(item)
        self.btn_add = QPushButton(tr("Add forward"))
        self.btn_add.clicked.connect(lambda: self._add_row({}))
        layout.addWidget(self.btn_add, 0, Qt.AlignLeading)
        note = QLabel(tr("Newer Xray servers refuse private addresses such as the server's "
                         "own 127.0.0.1, so a forward to them will not connect. A shared "
                         "forward can be used by anyone on your network."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    def _add_row(self, item: dict) -> None:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        port = QSpinBox()
        port.setRange(1024, 65535)
        value = item.get("port")
        port.setValue(value if isinstance(value, int) and 1024 <= value <= 65535 else 2222)
        port.setToolTip(tr("Local port"))
        target = QLineEdit(str(item.get("target") or ""))
        target.setPlaceholderText(tr("host:port"))
        target.setLayoutDirection(Qt.LeftToRight)
        via = QComboBox()
        via.addItem(tr("Through the tunnel"), "proxy")
        via.addItem(tr("Direct"), "direct")
        via.setCurrentIndex(max(via.findData(item.get("via")), 0))
        network = QComboBox()
        for key, label in self._NETWORKS:
            network.addItem(label, key)
        network.setCurrentIndex(max(network.findData(item.get("network")), 0))
        enabled = QCheckBox()
        enabled.setChecked(item.get("enabled", True) is not False)
        enabled.setToolTip(tr("Use this forward"))
        enabled.setAccessibleName(tr("Use this forward"))
        lan = QCheckBox(tr("LAN"))
        lan.setChecked(item.get("lan") is True)
        lan.setToolTip(tr("Let other devices on your network use this forward."))
        remove = QPushButton()
        remove.setIcon(icon("close"))
        remove.setToolTip(tr("Remove forward"))
        remove.setAccessibleName(tr("Remove forward"))
        entry = {"row": row, "enabled": enabled, "port": port, "target": target,
                 "via": via, "network": network, "lan": lan}
        remove.clicked.connect(lambda: self._remove_row(entry))
        box.addWidget(enabled)
        box.addWidget(port)
        box.addWidget(target, 2)
        box.addWidget(via, 1)
        box.addWidget(network)
        box.addWidget(lan)
        box.addWidget(remove)
        self._rows.append(entry)
        self._rows_box.addWidget(row)

    def _remove_row(self, entry) -> None:
        self._rows.remove(entry)
        entry["row"].setParent(None)

    def collect(self) -> list[dict]:
        return [{"enabled": r["enabled"].isChecked(), "port": r["port"].value(),
                 "target": r["target"].text().strip(), "via": r["via"].currentData(),
                 "network": r["network"].currentData(), "lan": r["lan"].isChecked()}
                for r in self._rows]

    def problem(self, exits_cfg: dict | None = None) -> str | None:
        """Why these forwards can't be saved, or None. `exits_cfg` is the
        multi-exit setting about to be saved, whose port they must not take."""
        taken = forwards_mod.taken_ports(self._core_cfg, exits_cfg or self._exits_cfg)
        for item in self.collect():
            if not item["enabled"]:
                continue  # a switched-off row is never rendered
            why = forwards_mod.item_problem(item, taken)
            if why:
                return tr("Port forwarding: {why}", why=why)
            taken.add(item["port"])
        return None


class _LocalProxyPage(QWidget):
    """Local proxy: port, allow LAN, auth, sniffing, default FP."""

    def __init__(self, core_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._core_cfg = core_cfg
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel(tr("Local proxy"))
        title.setObjectName("H1")
        layout.addWidget(title)

        group = InsetGroup(self)

        self.socks_port = QSpinBox()
        self.socks_port.setRange(1024, 65535)
        self.socks_port.setValue(coreopts.valid_socks_port(self._core_cfg.get("socks_port")))
        group.add_row(tr("Port"), self.socks_port)

        self.allow_lan = Switch()
        self.allow_lan.setChecked(bool(self._core_cfg.get("allow_lan")))
        group.add_row(tr("Allow other devices on your network"), self.allow_lan)

        self.lan_user = QLineEdit(str(self._core_cfg.get("lan_user") or ""))
        self.lan_user.setLayoutDirection(Qt.LeftToRight)
        group.add_row(tr("User"), self.lan_user)

        self.lan_pass = QLineEdit(str(self._core_cfg.get("lan_pass") or ""))
        self.lan_pass.setEchoMode(QLineEdit.Password)
        self.lan_pass.setLayoutDirection(Qt.LeftToRight)
        group.add_row(tr("Password"), self.lan_pass)

        self.lan_warning = QLabel(tr(
            "LAN sharing is on with no password — anyone on your network can use this proxy."
        ))
        self.lan_warning.setObjectName("Muted")
        self.lan_warning.setWordWrap(True)
        self.lan_warning.setVisible(False)
        group.add_row("", self.lan_warning)

        self.allow_lan.toggled.connect(self._sync_lan_warning)
        self.lan_user.textChanged.connect(self._sync_lan_warning)
        self.lan_pass.textChanged.connect(self._sync_lan_warning)
        self._sync_lan_warning()

        self.sniff_enabled = Switch()
        self.sniff_enabled.setChecked(bool(self._core_cfg.get("sniffing", {}).get("enabled", True)))
        group.add_row(tr("Sniffing"), self.sniff_enabled)

        self.sniff_route_only = Switch()
        self.sniff_route_only.setChecked(bool(self._core_cfg.get("sniffing", {}).get("route_only")))
        group.add_row(tr("Route only"), self.sniff_route_only)

        self.default_fp = QComboBox()
        self.default_fp.addItem(tr("(off)"), "")
        for name in coreopts.DEFAULT_FP_CHOICES:
            self.default_fp.addItem(name, name)
        current_fp = str(self._core_cfg.get("default_fp") or "")
        self.default_fp.setCurrentIndex(max(0, self.default_fp.findData(current_fp)))
        group.add_row(tr("Default TLS fingerprint"), self.default_fp)

        layout.addWidget(group)
        layout.addStretch(1)

    def _sync_lan_warning(self) -> None:
        has_auth = bool(self.lan_user.text().strip()) and bool(self.lan_pass.text().strip())
        self.lan_warning.setVisible(self.allow_lan.isChecked() and not has_auth)

    def collect(self) -> dict:
        return {
            "socks_port": self.socks_port.value(),
            "allow_lan": self.allow_lan.isChecked(),
            "lan_user": self.lan_user.text().strip(),
            "lan_pass": self.lan_pass.text().strip(),
            "sniffing": {
                "enabled": self.sniff_enabled.isChecked(),
                "route_only": self.sniff_route_only.isChecked(),
            },
            "default_fp": self.default_fp.currentData() or "",
        }

    def apply_to(self, target: dict) -> None:
        target.update(self.collect())


class _GeoDataPage(QWidget):
    """Geo data: source, update now, auto-update hours."""

    geo_updated = Signal(bool)

    def __init__(self, geo_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._geo_cfg = geo_cfg
        self._last_update = geo_cfg.get("last_update", 0)
        self._geo_busy = False
        self._geo_updated = False
        self.pool = QThreadPool.globalInstance()
        self._workers: set = set()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel(tr("Geo data"))
        title.setObjectName("H1")
        layout.addWidget(title)

        group = InsetGroup(self)

        self.geo_source = QComboBox()
        self.geo_source.addItems(list(geo_mod.SOURCES))
        current_source = str(self._geo_cfg.get("source", ""))
        if current_source in geo_mod.SOURCES:
            self.geo_source.setCurrentText(current_source)
        group.add_row(tr("Source"), self.geo_source)

        update_cell = QWidget()
        update_row = QHBoxLayout(update_cell)
        update_row.setContentsMargins(0, 0, 0, 0)
        self.btn_geo_update = QPushButton(tr("Update now"))
        self.btn_geo_update.clicked.connect(self._update_geo_now)
        self.geo_status = QLabel(self._format_last_update())
        self.geo_status.setObjectName("Muted")
        self.geo_status.setWordWrap(True)
        update_row.addWidget(self.btn_geo_update)
        update_row.addWidget(self.geo_status, 1)
        group.add_row("", update_cell)

        self.geo_auto_hours = QSpinBox()
        self.geo_auto_hours.setRange(0, 168)
        self.geo_auto_hours.setValue(int(self._geo_cfg.get("auto_update_hours", 0)))
        self.geo_auto_hours.setSpecialValueText(tr("Off"))
        group.add_row(tr("Auto-update every (hours)"), self.geo_auto_hours)

        layout.addWidget(group)
        layout.addStretch(1)

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
                self.geo_status.setText(str(error))
                return
            self._last_update = time.time()
            self._geo_updated = True
            data = app_settings.load()
            data.setdefault("geo", {})
            data["geo"]["last_update"] = self._last_update
            data["geo"]["source"] = source
            app_settings.save(data)
            self.geo_status.setText(self._format_last_update())
            self.geo_updated.emit(True)

        self._run_async(lambda: geo_mod.update(source), done)

    def collect(self) -> dict:
        return {
            "source": self.geo_source.currentText(),
            "auto_update_hours": self.geo_auto_hours.value(),
            "last_update": self._last_update,
        }

    def apply_to(self, target: dict) -> None:
        target.update(self.collect())

    def geo_updated_flag(self) -> bool:
        return self._geo_updated


class _StartupPage(QWidget):
    """Startup: start at login, minimized, auto-connect."""

    def __init__(self, startup_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._startup_cfg = startup_cfg
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel(tr("Startup"))
        title.setObjectName("H1")
        layout.addWidget(title)

        group = InsetGroup(self)

        self._autostart_ok, autostart_reason = autostart.is_supported()
        self.start_on_login = Switch()
        self.start_on_login.setChecked(bool(self._startup_cfg.get("start_on_login")))
        self.start_on_login.setEnabled(self._autostart_ok)
        if not self._autostart_ok:
            self.start_on_login.setToolTip(tr(autostart_reason))
        group.add_row(tr("Start sushTun when I log in"), self.start_on_login)

        self.start_minimized = Switch()
        self.start_minimized.setChecked(bool(self._startup_cfg.get("start_minimized")))
        group.add_row(tr("Start minimized to the tray"), self.start_minimized)

        self.auto_connect = Switch()
        self.auto_connect.setChecked(bool(self._startup_cfg.get("auto_connect")))
        group.add_row(tr("Connect automatically on start"), self.auto_connect)

        layout.addWidget(group)
        layout.addStretch(1)

    def collect(self) -> dict:
        return {
            "start_on_login": self.start_on_login.isChecked(),
            "start_minimized": self.start_minimized.isChecked(),
            "auto_connect": self.auto_connect.isChecked(),
        }

    def apply_to(self, target: dict) -> None:
        target.update(self.collect())


class _BackupPage(QWidget):
    """Backup & restore: backup/restore buttons with warnings."""

    restored = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._restored = False
        self._backup_busy = False
        self.pool = QThreadPool.globalInstance()
        self._workers: set = set()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel(tr("Backup"))
        title.setObjectName("H1")
        layout.addWidget(title)

        group = InsetGroup(self)

        backup_warning = QLabel(tr(
            "A backup file contains your server passwords in plain text — "
            "store and share it carefully."
        ))
        backup_warning.setObjectName("Muted")
        backup_warning.setWordWrap(True)
        group.add_row("", backup_warning)

        self.btn_backup = QPushButton(tr("Back up…"))
        self.btn_backup.clicked.connect(self._backup_now)
        self.btn_restore = QPushButton(tr("Restore…"))
        self.btn_restore.clicked.connect(self._restore_now)

        backup_cell = QWidget()
        backup_row = QHBoxLayout(backup_cell)
        backup_row.setContentsMargins(0, 0, 0, 0)
        backup_row.addWidget(self.btn_backup)
        backup_row.addWidget(self.btn_restore)
        group.add_row("", backup_cell)

        layout.addWidget(group)
        layout.addStretch(1)

    def _run_async(self, fn, done) -> None:
        worker = Worker(fn)

        def finish(result=None, error=None):
            self._workers.discard(worker)
            done(result=result, error=error)

        worker.signals.finished.connect(lambda r: finish(result=r))
        worker.signals.error.connect(lambda e: finish(error=e))
        self._workers.add(worker)
        self.pool.start(worker)

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
            QMessageBox.warning(self, tr("Restore failed"), str(exc))
            return
        self._restored = True
        QMessageBox.information(self, tr("Restore complete"),
                                tr("Restored. sushTun will reload your settings and servers."))
        self.restored.emit(True)

    def restored_flag(self) -> bool:
        return self._restored


class _LanguagePage(QWidget):
    """Language: English / فارسی with restart note."""

    def __init__(self, current_lang: str, parent=None) -> None:
        super().__init__(parent)
        self._current_lang = current_lang
        self._language_was = current_lang
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel(tr("Language"))
        title.setObjectName("H1")
        layout.addWidget(title)

        group = InsetGroup(self)

        self.language = QComboBox()
        self.language.addItem("English", "en")
        self.language.addItem("فارسی", "fa")
        idx = self.language.findData(self._current_lang)
        self.language.setCurrentIndex(idx if idx >= 0 else 0)
        group.add_row(tr("Language"), self.language)

        layout.addWidget(group)
        layout.addStretch(1)

    def collect(self) -> dict:
        return {"language": self.language.currentData() or "en"}

    def apply_to(self, target: dict) -> None:
        target.update(self.collect())

    def language_changed(self) -> bool:
        return (self.language.currentData() or "en") != self._language_was


class SettingsWindow(QDialog):
    """System Settings style settings window with sidebar navigation."""

    # General → Check now found one. Installing it belongs to the main window,
    # which is the only thing that can quit the app afterwards.
    updateAvailable = Signal(object)

    def __init__(
        self,
        settings: dict,
        parent=None,
        topic: str = "general",
        profiles: list[Profile] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Settings"))
        # Same chrome as the main window: outside macOS the window draws its
        # own working traffic lights. The native title bar was light-themed
        # and, on GNOME, offered no close button at all.
        self._frameless = sys.platform != "darwin"
        if self._frameless:
            self.setWindowFlag(Qt.FramelessWindowHint)
        self.setObjectName("SettingsWindow")
        self._settings = copy.deepcopy(settings)
        self._original_settings = copy.deepcopy(settings)
        self._profiles = list(profiles or [])
        self._busy = False
        self.pool = QThreadPool.globalInstance()
        self._workers: set = set()
        self._language_was = settings.get("language", "en")

        # Build UI
        self._build_ui()

        # Select initial topic
        self._select_topic(topic)

        # Window size
        width = 820
        height = 560
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            max_h = int(screen.availableGeometry().height() * 0.85)
            height = min(height, max_h)
        self.resize(width, height)

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Sidebar
        self._sidebar = QWidget()
        self._sidebar.setObjectName("Sidebar")
        self._sidebar.setFixedWidth(210)
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(10, 16, 10, 16)
        sidebar_layout.setSpacing(2)

        if self._frameless:
            # Real buttons: close cancels (discarding edits, like Esc).
            self.btn_close = TrafficLight("close")
            self.btn_minimize = TrafficLight("minimize")
            self.btn_zoom = TrafficLight("zoom")
            self.btn_close.clicked.connect(self.reject)
            self.btn_minimize.clicked.connect(self.showMinimized)
            self.btn_zoom.clicked.connect(
                lambda: self.showNormal() if self.isMaximized() else self.showMaximized())
            self.lights = _LightGroup([self.btn_close, self.btn_minimize, self.btn_zoom])
            sidebar_layout.addWidget(self.lights, 0, Qt.AlignLeading)
            sidebar_layout.addSpacing(16)

        # Sidebar items
        self._sidebar_items = []
        for key, label, icon_name, color in TOPICS:
            # Translate at build time so a language switch mid-session sticks.
            item = SettingsSidebarItem(tr(label), icon_name, color)
            item.setProperty("topic_key", key)
            item.clicked.connect(lambda checked=False, k=key: self._select_topic(k))
            sidebar_layout.addWidget(item)
            self._sidebar_items.append(item)

        sidebar_layout.addStretch(1)
        outer.addWidget(self._sidebar)

        # Right column: inline status line, topic stack, and buttons row.
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(0)

        # Status label for validation errors -- sits at the top of the
        # current topic when visible, hidden otherwise.
        self._status_label = QLabel("")
        self._status_label.setObjectName("Muted")
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        right_col.addWidget(self._status_label)

        # Stacked widget for topic pages
        self._stack = QStackedWidget()
        right_col.addWidget(self._stack, 1)

        # Create topic pages
        core_cfg = self._settings.get("core") or {}
        geo_cfg = self._settings.get("geo") or {}
        startup_cfg = self._settings.get("startup") or {}

        self._pages = {}
        self._pages["general"] = _GeneralPage(self._settings)
        self._pages["general"].updateAvailable.connect(self.updateAvailable)
        self._pages["anti-filter"] = _AntiFilterPage(core_cfg)
        self._pages["local-proxy"] = _LocalProxyPage(core_cfg)
        self._pages["geo-data"] = _GeoDataPage(geo_cfg)
        self._pages["hotspot"] = _HotspotPage(self._settings.get("gateway") or {})
        self._pages["startup"] = _StartupPage(startup_cfg)
        self._pages["exits"] = _ExitsPage(self._settings.get("exits") or {}, core_cfg,
                                          self._settings.get("dns") or {}, self._profiles)
        self._pages["forwards"] = _ForwardsPage(self._settings.get("forwards"), core_cfg,
                                                self._settings.get("exits") or {})
        self._pages["backup"] = _BackupPage()
        self._pages["language"] = _LanguagePage(self._language_was)

        for page in self._pages.values():
            # A topic page can be taller than the window (Persian wraps more);
            # without scrolling its rows are squeezed and overlap each other.
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.NoFrame)
            area.setWidget(page)
            self._stack.addWidget(area)

        # Connect signals for side effects
        self._pages["geo-data"].geo_updated.connect(self._on_geo_updated)
        self._pages["backup"].restored.connect(self._on_restored)

        # Buttons: Cancel, then Done (default) last, as on macOS
        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(18, 10, 18, 14)
        buttons_row.setSpacing(8)
        buttons_row.addStretch(1)
        btn_cancel = QPushButton(tr("Cancel"))
        btn_cancel.setAutoDefault(False)
        btn_cancel.clicked.connect(self.reject)
        buttons_row.addWidget(btn_cancel)
        self.btn_done = QPushButton(tr("Done"))
        # The theme paints #Primary blue, marking the button Enter triggers.
        self.btn_done.setObjectName("Primary")
        self.btn_done.setDefault(True)
        self.btn_done.setAutoDefault(True)
        self.btn_done.clicked.connect(self._on_done)
        buttons_row.addWidget(self.btn_done)
        right_col.addLayout(buttons_row)

        outer.addLayout(right_col, 1)

        # Store references for validation
        self._core_cfg = core_cfg
        self._start_on_login_was = self._pages["startup"].start_on_login.isChecked()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt convention
        # Without a native title bar, empty space (the sidebar, the page
        # margins) is where the window is dragged from.
        handle = self.windowHandle()
        if (self._frameless and event.button() == Qt.LeftButton
                and handle is not None and handle.startSystemMove()):
            event.accept()
            return
        super().mousePressEvent(event)

    def _select_topic(self, key: str) -> None:
        """Switch to the given topic page."""
        if key not in self._pages:
            key = "general"
        idx = list(self._pages.keys()).index(key)
        self._stack.setCurrentIndex(idx)
        for item in self._sidebar_items:
            item.setChecked(item.property("topic_key") == key)
        self._hide_status()

    def _hide_status(self) -> None:
        self._status_label.setText("")
        self._status_label.setVisible(False)

    def _show_status(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.setVisible(True)

    def _on_geo_updated(self, _flag: bool) -> None:
        pass  # Handled in collect

    def _on_restored(self, _flag: bool) -> None:
        pass  # Handled in collect

    def _on_done(self) -> None:
        if self._busy:
            return
        problem = (self._pages["exits"].problem() or self._pages["hotspot"].problem()
                   or self._pages["forwards"].problem(self._pages["exits"].collect()))
        if problem:
            self._show_status(problem)
            return
        self._busy = True
        self.btn_done.setEnabled(False)
        self._show_status(tr("Validating…"))

        # Collect core config from all pages
        core_cfg = self._core_cfg.copy()
        self._pages["anti-filter"].apply_to(core_cfg)
        self._pages["local-proxy"].apply_to(core_cfg)

        toggle_login = (
            self._pages["startup"].start_on_login.isChecked()
            != self._start_on_login_was
        )
        want_login = self._pages["startup"].start_on_login.isChecked()

        def work():
            # Render config for validation
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
            self.btn_done.setEnabled(True)
            if error:
                self._show_status(tr("Validation failed: {err}", err=str(error)))
                return
            check_result, startup_error = result
            if check_result:
                self._show_status(tr("Settings invalid: {err}", err=check_result))
                return
            if startup_error:
                self._show_status(tr("Startup setting failed: {err}", err=startup_error))
                return
            self._start_on_login_was = want_login
            self._apply_all()
            if self._pages["language"].language_changed():
                QMessageBox.information(
                    self, tr("Language"),
                    tr("Restart sushTun to apply the new language."))
            self.accept()

        self._run_async(work, done)

    def _apply_all(self) -> None:
        """Apply all pages' collected values to _settings."""
        self._pages["general"].apply_to(self._settings)
        core_cfg = self._core_cfg.copy()
        self._pages["anti-filter"].apply_to(core_cfg)
        self._pages["local-proxy"].apply_to(core_cfg)
        self._settings["core"] = core_cfg
        self._pages["geo-data"].apply_to(self._settings.setdefault("geo", {}))
        self._pages["startup"].apply_to(self._settings.setdefault("startup", {}))
        self._pages["language"].apply_to(self._settings)
        # updates extra fields are carried through
        self._settings["updates"] = {
            **self._settings.get("updates", {}),
            "check": self._pages["general"].check_updates.isChecked(),
        }

    def _run_async(self, fn, done) -> None:
        worker = Worker(fn)

        def finish(result=None, error=None):
            self._workers.discard(worker)
            done(result=result, error=error)

        worker.signals.finished.connect(lambda r: finish(result=r))
        worker.signals.error.connect(lambda e: finish(error=e))
        self._workers.add(worker)
        self.pool.start(worker)

    def values(self) -> dict:
        """Return the current candidate settings (same API as SettingsDialog)."""
        core_cfg = self._core_cfg.copy()
        self._pages["anti-filter"].apply_to(core_cfg)
        self._pages["local-proxy"].apply_to(core_cfg)

        return {
            "ping_target": self._pages["general"].ping_target.text().strip() or "1.1.1.1",
            "sample_seconds": self._pages["general"].sample_seconds.value(),
            "tun_mtu": self._pages["general"].tun_mtu.value(),
            "log_level": self._pages["general"].log_level.currentText(),
            "language": self._pages["language"].language.currentData() or "en",
            "geo": self._pages["geo-data"].collect(),
            "core": core_cfg,
            "startup": self._pages["startup"].collect(),
            "exits": self._pages["exits"].collect(),
            "forwards": self._pages["forwards"].collect(),
            "gateway": self._pages["hotspot"].collect(),
            "updates": {
                **self._settings.get("updates", {}),
                "check": self._pages["general"].check_updates.isChecked(),
            },
        }

    def geo_updated(self) -> bool:
        """Whether Update now succeeded while this window was open."""
        return self._pages["geo-data"].geo_updated_flag()

    def restored(self) -> bool:
        """Whether Restore… succeeded while this window was open."""
        return self._pages["backup"].restored_flag()

    def reject(self) -> None:
        """Discard changes on Cancel/Escape."""
        # Restore original settings if needed (for side effects like geo update)
        # Note: geo update and restore already persisted on disk immediately
        super().reject()

