"""Main application window: status, profiles, connect, log and tools."""
from __future__ import annotations

import copy
import json

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..core import metrics
from ..core.connection import Connection, _resolve
from ..core.profiles import Profile, ProfileStore
from ..core.xray import is_xray_running
from .dialogs import ImportDialog, ProfileEditDialog, SettingsDialog
from .log_tailer import LogTailer
from .tools_panel import ToolsPanel
from .widgets import LogView, ProfilePanel, StatusCard


def _load_settings() -> dict:
    p = paths.base_dir() / "settings.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"ping_target": "1.1.1.1", "sample_seconds": 5}


def _save_settings(data: dict) -> None:
    (paths.base_dir() / "settings.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


class MainWindow(QMainWindow):
    stepReceived = Signal(str)

    def __init__(self, elevated: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("Xray Portable")
        self.resize(980, 640)

        self.store = ProfileStore()
        self.settings = _load_settings()
        self.pool = QThreadPool.globalInstance()
        self.conn = Connection(on_step=self.stepReceived.emit)
        self._busy = False
        self._sampling = False
        self._workers: set = set()

        self.stepReceived.connect(self._on_step)
        self._build_ui(elevated)
        self._build_tray()

        self.tailer = LogTailer()
        self.tailer.line.connect(self.log.append_line)
        self.tailer.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_status)
        self.timer.start(2000)

        self._reload_profiles()
        self._refresh_status()

    # UI construction -------------------------------------------------------
    def _build_ui(self, elevated: bool) -> None:
        self.status_card = StatusCard()
        self.profiles = ProfilePanel()
        self.tools = ToolsPanel()
        self.log = LogView()

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setObjectName("Primary")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setObjectName("Danger")
        self.btn_cleanup = QPushButton("Restore network")
        self.btn_settings = QPushButton("Settings")
        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.btn_cleanup.clicked.connect(self._cleanup)
        self.btn_settings.clicked.connect(self._open_settings)

        actions = QHBoxLayout()
        actions.addWidget(self.btn_connect, 2)
        actions.addWidget(self.btn_disconnect, 1)
        actions.addWidget(self.btn_cleanup, 1)
        actions.addWidget(self.btn_settings, 1)

        self.step_label = QLabel("")
        self.step_label.setObjectName("Muted")

        tabs = QTabWidget()
        tabs.addTab(self.log, "Live log")
        tabs.addTab(self.tools, "Tools")

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.status_card)
        rl.addLayout(actions)
        rl.addWidget(self.step_label)
        rl.addWidget(tabs, 1)
        if not elevated:
            warn = QLabel("Not running as administrator — connecting will fail.")
            warn.setStyleSheet("color:#ff6b6b;")
            rl.insertWidget(0, warn)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.profiles)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 680])

        container = QWidget()
        cl = QHBoxLayout(container)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.addWidget(splitter)
        self.setCentralWidget(container)

        self.profiles.importRequested.connect(self._import)
        self.profiles.editRequested.connect(self._edit)
        self.profiles.duplicateRequested.connect(self._duplicate)
        self.profiles.deleteRequested.connect(self._delete)
        self.profiles.activated.connect(self._set_active)
        self.tools.pingRequested.connect(lambda: self._run_tool(self._ping_fn))
        self.tools.delayRequested.connect(lambda: self._run_tool(self._delay_fn))
        self.tools.throughputRequested.connect(lambda: self._run_tool(self._throughput_fn))
        self.tools.diagnosticsRequested.connect(lambda: self._run_tool(self._diag_fn))

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Xray Portable")
        menu = QMenu()
        menu.addAction("Show", self.showNormal)
        menu.addAction("Connect", self._connect)
        menu.addAction("Disconnect", self._disconnect)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.showNormal()
            if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    # Profiles --------------------------------------------------------------
    def _reload_profiles(self) -> None:
        self.profiles.set_profiles(self.store.list(), self.store.active_uid())

    def _active_profile(self) -> Profile | None:
        uid = self.profiles.current_uid() or self.store.active_uid()
        return self.store.get(uid) if uid else None

    def _import(self) -> None:
        dlg = ImportDialog(self)
        if not dlg.exec():
            return
        first = None
        for p in dlg.profiles:
            self.store.save(p)
            first = first or p
        if first and not self.store.active_uid():
            self.store.set_active(first.uid)
        self._reload_profiles()

    def _edit(self, uid: str) -> None:
        profile = self.store.get(uid)
        if not profile:
            return
        dlg = ProfileEditDialog(profile, self)
        if dlg.exec():
            self.store.save(dlg.result_profile())
            self._reload_profiles()

    def _duplicate(self, uid: str) -> None:
        profile = self.store.get(uid)
        if not profile:
            return
        clone = copy.deepcopy(profile)
        clone.uid = Profile().uid
        clone.name = f"{profile.name} copy"
        self.store.save(clone)
        self._reload_profiles()

    def _delete(self, uid: str) -> None:
        profile = self.store.get(uid)
        if not profile:
            return
        if QMessageBox.question(self, "Delete", f"Delete '{profile.name}'?") == \
                QMessageBox.Yes:
            self.store.delete(uid)
            self._reload_profiles()

    def _set_active(self, uid: str) -> None:
        self.store.set_active(uid)
        self._reload_profiles()
        self._refresh_status()

    # Connection ------------------------------------------------------------
    def _connect(self) -> None:
        if self._busy:
            return
        profile = self._active_profile()
        if not profile:
            QMessageBox.information(self, "No profile", "Import or select a profile first.")
            return
        self.store.set_active(profile.uid)
        self._set_busy(True)
        self.log.append_line(f"Connecting to {profile.name} ({profile.endpoint})…")
        self._run_async(lambda: self.conn.connect(profile), self._on_conn_done)

    def _disconnect(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._run_async(self.conn.disconnect, self._on_conn_done)

    def _cleanup(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._run_async(self.conn.cleanup, self._on_conn_done)

    def _on_conn_done(self, result=None, error: str | None = None) -> None:
        self._set_busy(False)
        if error:
            self.step_label.setText(error)
            QMessageBox.warning(self, "Connection", error)
        self._refresh_status()

    def _on_step(self, msg: str) -> None:
        self.step_label.setText(msg)
        self.log.append_line(f">> {msg}")

    # Tools -----------------------------------------------------------------
    def _run_tool(self, fn) -> None:
        if self._busy:
            return
        self.tools.set_busy(True)
        self.tools.set_result("Working…")

        def done(result=None, error=None):
            self.tools.set_busy(False)
            self.tools.set_result(error if error else str(result))

        self._run_async(fn, done)

    def _ping_fn(self) -> str:
        profile = self._active_profile()
        target = self.settings.get("ping_target", "1.1.1.1")
        parts = []
        if profile and profile.address:
            parts.append(f"--- Relay ping ({profile.address}) ---")
            parts.append(metrics.ping(profile.address, 4))
        parts.append(f"--- Internet ping ({target}) ---")
        parts.append(metrics.ping(target, 4))
        return "\n".join(parts)

    def _delay_fn(self) -> str:
        profile = self._active_profile()
        if not profile:
            return "No active profile."
        d = metrics.tcp_connect_delay(profile.address, profile.port)
        lines = [f"TCP connect to {profile.endpoint}"]
        for i, r in enumerate(d["results"], 1):
            lines.append(f"Attempt {i}: {round(r)} ms" if r is not None else f"Attempt {i}: failed")
        if d["avg"] is not None:
            lines.append(f"\nAvg {round(d['avg'])} ms  Min {round(d['min'])} ms  Max {round(d['max'])} ms")
        return "\n".join(lines)

    def _throughput_fn(self) -> str:
        tun = self.conn.state.tun_index
        if tun is None:
            return "Not connected (no tunnel)."
        seconds = int(self.settings.get("sample_seconds", 5))
        s = metrics.throughput_sample(tun, seconds)
        if not s:
            return "Sampling failed."
        return (f"Adapter {s['name']} (ifIndex {tun})\n"
                f"RX {s['rx']:,} bytes  ~{s['rx_mbps']} Mbit/s\n"
                f"TX {s['tx']:,} bytes  ~{s['tx_mbps']} Mbit/s")

    def _diag_fn(self) -> str:
        profile = self._active_profile()
        server_ip = self.conn.state.server_ip
        if not server_ip and profile:
            try:
                server_ip = _resolve(profile.address)
            except OSError:
                server_ip = None
        return metrics.diagnostics(server_ip, self.conn.state.alias, self.conn.state.tun_index)

    # Status ----------------------------------------------------------------
    def _refresh_status(self) -> None:
        connected = self.conn.is_connected()
        self.status_card.set_connected(connected)
        profile = self._active_profile()
        self.status_card.set("endpoint", profile.endpoint if profile else "—")
        self.status_card.set("process", "RUNNING" if is_xray_running() else "STOPPED")
        st = self.conn.state
        self.status_card.set("iface", st.alias or "—")
        self.status_card.set("ip", st.ipv4 or "—")
        self.status_card.set("gateway", st.gateway or "—")
        self.status_card.set("tun", str(st.tun_index) if st.tun_index else "—")
        self.btn_connect.setEnabled(not connected and not self._busy)
        self.btn_disconnect.setEnabled(connected and not self._busy)
        if connected and not self._sampling and st.tun_index is not None:
            self._sample_throughput(st.tun_index)

    def _sample_throughput(self, tun: int) -> None:
        self._sampling = True

        def done(result=None, error=None):
            self._sampling = False
            if result:
                self.status_card.set("throughput",
                                     f"↓ {result['rx_mbps']}  ↑ {result['tx_mbps']} Mbit/s")

        self._run_async(lambda: metrics.throughput_sample(tun, 1), done)

    # Settings --------------------------------------------------------------
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings.update(dlg.values())
            _save_settings(self.settings)

    # Worker plumbing -------------------------------------------------------
    def _run_async(self, fn, done) -> None:
        from .workers import Worker
        worker = Worker(fn)

        def finish(result=None, error=None):
            self._workers.discard(worker)
            done(result=result, error=error)

        worker.signals.finished.connect(lambda r: finish(result=r))
        worker.signals.error.connect(lambda e: finish(error=e))
        self._workers.add(worker)  # hold a reference so PySide won't GC it mid-run
        self.pool.start(worker)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_connect.setEnabled(not busy)
        self.btn_disconnect.setEnabled(not busy)
        self.btn_cleanup.setEnabled(not busy)

    def closeEvent(self, event) -> None:
        self.tailer.stop()
        super().closeEvent(event)
