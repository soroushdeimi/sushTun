"""Main window: status, profiles, subscriptions, bypass, connect, log and tools."""
from __future__ import annotations

import copy
import time

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import alerts, metrics
from ..core import settings as app_settings
from ..core import subscription as sub_mod
from ..core.alerts import human_bytes
from ..core.connection import Connection, _resolve
from ..core.profiles import Profile, ProfileStore
from ..core.xray import is_xray_running
from .dialogs import ImportDialog, ProfileEditDialog, SettingsDialog
from .log_tailer import LogTailer
from .routing_dialog import RoutingDialog
from .subscription_panel import SubscriptionPanel
from .tools_panel import ToolsPanel
from .widgets import AlertBanner, LogView, ProfilePanel, StatusCard


class MainWindow(QMainWindow):
    stepReceived = Signal(str)

    def __init__(self, elevated: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("Xray Portable")
        self.resize(1040, 680)

        self.store = ProfileStore()
        self.subs = sub_mod.SubscriptionStore()
        self.settings = app_settings.load()
        self.throttle = alerts.Throttle()
        self.pool = QThreadPool.globalInstance()
        self.conn = Connection(on_step=self.stepReceived.emit)
        self._busy = False
        self._sampling = False
        self._workers: set = set()

        self.stepReceived.connect(self._on_step)
        self._build_ui(elevated)
        self._build_tray()

        self.tailer = LogTailer()
        self.tailer.lines.connect(self.log.append_lines)
        self.tailer.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_status)
        self.timer.start(2000)
        self.alert_timer = QTimer(self)
        self.alert_timer.timeout.connect(self._check_alerts)
        self.alert_timer.start(60_000)
        self.autorefresh_timer = QTimer(self)
        self.autorefresh_timer.timeout.connect(self._auto_refresh_subs)
        self.autorefresh_timer.start(30 * 60_000)

        self._reload_profiles()
        self._reload_subs()
        self._refresh_status()
        self._check_alerts()

    # UI construction -------------------------------------------------------
    def _build_ui(self, elevated: bool) -> None:
        self.status_card = StatusCard()
        self.profiles = ProfilePanel()
        self.subs_panel = SubscriptionPanel()
        self.tools = ToolsPanel()
        self.log = LogView()
        self.alert_banner = AlertBanner()

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setObjectName("Primary")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setObjectName("Danger")
        self.btn_cleanup = QPushButton("Restore network")
        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.btn_cleanup.clicked.connect(self._cleanup)

        actions = QHBoxLayout()
        actions.addWidget(self.btn_connect, 2)
        actions.addWidget(self.btn_disconnect, 1)
        actions.addWidget(self.btn_cleanup, 1)

        self.btn_low = QPushButton("Low usage")
        self.btn_low.setCheckable(True)
        self.btn_low.setChecked(self.settings["routing"]["low_usage"])
        self.btn_low.toggled.connect(self._toggle_low_usage)
        self.btn_bypass = QPushButton("Bypass…")
        self.btn_bypass.clicked.connect(self._open_routing)
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self._open_settings)
        self.btn_gateway = QPushButton("Share via hotspot")
        self.btn_gateway.setCheckable(True)
        self.btn_gateway.setToolTip(
            "Route devices on this PC's Windows hotspot through the tunnel, "
            "so phones need no setup of their own."
        )
        self.btn_gateway.setChecked(self.settings["gateway"]["enabled"])
        self.btn_gateway.toggled.connect(self._toggle_gateway)

        actions2 = QHBoxLayout()
        actions2.addWidget(self.btn_low)
        actions2.addWidget(self.btn_gateway)
        actions2.addWidget(self.btn_bypass)
        actions2.addWidget(self.btn_settings)

        self.step_label = QLabel("")
        self.step_label.setObjectName("Muted")

        tabs = QTabWidget()
        tabs.addTab(self.log, "Live log")
        tabs.addTab(self.tools, "Tools")

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.alert_banner)
        rl.addWidget(self.status_card)
        rl.addLayout(actions)
        rl.addLayout(actions2)
        rl.addWidget(self.step_label)
        rl.addWidget(tabs, 1)
        if not elevated:
            warn = QLabel("Not running as administrator — connecting will fail.")
            warn.setStyleSheet("color:#ff6b6b;")
            rl.insertWidget(0, warn)

        left_split = QSplitter(Qt.Vertical)
        left_split.addWidget(self._wrap(self.profiles))
        left_split.addWidget(self._wrap(self.subs_panel))
        left_split.setSizes([400, 260])

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_split)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 720])

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
        self.subs_panel.addRequested.connect(self._add_sub)
        self.subs_panel.refreshRequested.connect(self._refresh_sub)
        self.subs_panel.deleteRequested.connect(self._delete_sub)
        self.tools.pingRequested.connect(lambda: self._run_tool(self._ping_fn))
        self.tools.delayRequested.connect(lambda: self._run_tool(self._delay_fn))
        self.tools.throughputRequested.connect(lambda: self._run_tool(self._throughput_fn))
        self.tools.diagnosticsRequested.connect(lambda: self._run_tool(self._diag_fn))

    @staticmethod
    def _wrap(widget: QWidget) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(widget)
        return w

    def _build_tray(self) -> None:
        from .icon import app_icon
        icon = app_icon()
        self.setWindowIcon(icon)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
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
        clone.sub_uid = ""
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

    # Subscriptions ---------------------------------------------------------
    def _reload_subs(self) -> None:
        self.subs_panel.set_subscriptions(self.subs.list())

    def _add_sub(self) -> None:
        url, ok = QInputDialog.getText(self, "Add subscription", "Subscription URL:")
        url = url.strip()
        if not ok or not url:
            return
        name = url.split("//", 1)[-1].split("/", 1)[0] or url[:40]
        sub = sub_mod.Subscription(url=url, name=name)
        self.subs.save(sub)
        self._reload_subs()
        self._refresh_sub(sub.uid)

    def _refresh_sub(self, uid: str) -> None:
        sub = next((s for s in self.subs.list() if s.uid == uid), None)
        if not sub:
            return
        self.step_label.setText(f"Refreshing {sub.name}…")

        def done(result=None, error=None):
            if error:
                self.step_label.setText(f"Subscription refresh failed: {error}")
            else:
                self.step_label.setText("Subscription updated.")
            self._reload_subs()
            self._reload_profiles()
            self._check_alerts()

        self._run_async(lambda: sub_mod.refresh(sub, self.store, self.subs), done)

    def _delete_sub(self, uid: str) -> None:
        if QMessageBox.question(self, "Delete", "Delete subscription and its profiles?") == \
                QMessageBox.Yes:
            self.subs.delete(uid, self.store)
            self._reload_subs()
            self._reload_profiles()

    def _auto_refresh_subs(self) -> None:
        hours = self.settings.get("alerts", {}).get("auto_refresh_hours", 6)
        cutoff = time.time() - hours * 3600
        for sub in self.subs.list():
            if sub.updated < cutoff:
                self._refresh_sub(sub.uid)

    # Alerts ----------------------------------------------------------------
    def _check_alerts(self) -> None:
        cfg = self.settings.get("alerts", {})
        triggered = []
        for sub in self.subs.list():
            for alert in alerts.evaluate(sub, cfg):
                if self.throttle.allow(alert.key):
                    triggered.append(alert)
        if not triggered:
            return
        level = "critical" if any(a.level == "critical" for a in triggered) else "warning"
        message = "  •  ".join(a.message for a in triggered)
        self.alert_banner.show_alert(level, message)
        if self.tray:
            icon = QSystemTrayIcon.Critical if level == "critical" else QSystemTrayIcon.Warning
            self.tray.showMessage("Xray Portable", message, icon, 8000)

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
            self._sample_live(st.tun_index)

    def _sample_live(self, tun: int) -> None:
        self._sampling = True

        def work():
            return {"rate": metrics.throughput_sample(tun, 1), "stats": metrics.query_stats()}

        def done(result=None, error=None):
            self._sampling = False
            if not result:
                return
            rate = result.get("rate")
            stats = result.get("stats")
            if rate:
                self.status_card.set("throughput",
                                     f"↓ {rate['rx_mbps']}  ↑ {rate['tx_mbps']} Mbit/s")
            if stats:
                self.status_card.set(
                    "used",
                    f"↓ {human_bytes(stats['down'])}  ↑ {human_bytes(stats['up'])}",
                )

        self._run_async(work, done)

    # Settings / routing ----------------------------------------------------
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings.update(dlg.values())
            app_settings.save(self.settings)

    def _open_routing(self) -> None:
        dlg = RoutingDialog(self.settings["routing"], self)
        if dlg.exec():
            self.settings["routing"] = dlg.result_routing()
            app_settings.save(self.settings)
            self.btn_low.setChecked(self.settings["routing"]["low_usage"])
            self.step_label.setText("Routing saved — applies on next connect.")

    def _toggle_low_usage(self, checked: bool) -> None:
        self.settings["routing"]["low_usage"] = checked
        app_settings.save(self.settings)
        self.step_label.setText(
            f"Low usage {'on' if checked else 'off'} — applies on next connect."
        )

    def _toggle_gateway(self, checked: bool) -> None:
        self.settings["gateway"]["enabled"] = checked
        app_settings.save(self.settings)
        if not checked and self.conn.is_connected():
            self._run_async(self.conn.stop_gateway, lambda result=None, error=None: None)
            self.step_label.setText("Hotspot sharing off.")
            return
        self.step_label.setText(
            "Hotspot sharing on — applies on next connect."
            if checked else "Hotspot sharing off."
        )

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
        for t in (self.timer, self.alert_timer, self.autorefresh_timer):
            t.stop()
        self.tailer.stop()
        self.pool.waitForDone(2000)
        super().closeEvent(event)
