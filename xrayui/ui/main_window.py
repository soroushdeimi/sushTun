"""Main window: status, profiles, subscriptions, bypass, connect, log and tools."""
from __future__ import annotations

import copy
import sys
import threading
import time

from PySide6.QtCore import QEvent, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
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

from ..core import alerts, hotspot, importer, metrics, network, speedtest
from ..core import settings as app_settings
from ..core import subscription as sub_mod
from ..core.alerts import human_bytes
from ..core.connection import Connection, _resolve
from ..core.profiles import Profile, ProfileStore
from ..core.xray import is_xray_running
from .dialogs import ImportDialog, ProfileEditDialog, SettingsDialog
from .dns_dialog import DnsDialog
from .log_tailer import LogTailer
from .routing_dialog import RoutingDialog
from .subscription_panel import SubscriptionPanel
from .titlebar import TitleBar
from .tools_panel import ToolsPanel
from .widgets import AlertBanner, LogView, ProfilePanel, StatusCard

# How far in from the border a press starts a resize on the frameless window.
_RESIZE_MARGIN = 6
_EDGE_CURSORS = {
    Qt.LeftEdge: Qt.SizeHorCursor,
    Qt.RightEdge: Qt.SizeHorCursor,
    Qt.TopEdge: Qt.SizeVerCursor,
    Qt.BottomEdge: Qt.SizeVerCursor,
    Qt.LeftEdge | Qt.TopEdge: Qt.SizeFDiagCursor,
    Qt.RightEdge | Qt.BottomEdge: Qt.SizeFDiagCursor,
    Qt.RightEdge | Qt.TopEdge: Qt.SizeBDiagCursor,
    Qt.LeftEdge | Qt.BottomEdge: Qt.SizeBDiagCursor,
}


class MainWindow(QMainWindow):
    stepReceived = Signal(str)
    # speedtest.real_delay_all/tcping_all call on_result from worker threads;
    # emitting through a Qt Signal queues delivery onto the UI thread instead
    # of touching the table model off it.
    testResultReceived = Signal(str, object, object)

    def __init__(self, elevated: bool = True) -> None:
        super().__init__()
        self.titlebar = None  # changeEvent fires from here on, before the UI is built
        self.setWindowTitle("sushTun")
        self.resize(1040, 700)
        # macOS draws real traffic lights; elsewhere we draw our own.
        self._frameless = sys.platform != "darwin"
        if self._frameless:
            self.setObjectName("Frameless")
            self.setWindowFlag(Qt.FramelessWindowHint)
            self.setAttribute(Qt.WA_TranslucentBackground)
        self._handle = None
        self._edge_cursor = False
        self._quitting = False
        self._told_about_tray = False

        self.store = ProfileStore()
        self.subs = sub_mod.SubscriptionStore()
        self.results = speedtest.ResultStore()
        self.settings = app_settings.load()
        self.throttle = alerts.Throttle()
        self.pool = QThreadPool.globalInstance()
        self.conn = Connection(on_step=self.stepReceived.emit)
        self._busy = False
        self._sampling = False
        self._repairing = False
        self._workers: set = set()
        self._test_cancel: threading.Event | None = None

        self.stepReceived.connect(self._on_step)
        self.testResultReceived.connect(self._on_test_result)
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
        self.route_timer = QTimer(self)
        self.route_timer.timeout.connect(self._check_route_health)
        self.route_timer.start(15_000)

        self._reload_profiles()
        self._reload_subs()
        self._refresh_status()
        self._check_alerts()
        try:
            if self.conn.recover_if_stale(dns_retries=3):
                self._on_step("Restored leftover network settings from a previous session.")
        except Exception as exc:
            self._on_step(f"Could not restore leftover network settings: {exc}")
        self._refresh_status()

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
        self.btn_dns = QPushButton("DNS…")
        self.btn_dns.setToolTip("Choose which resolvers the tunnel uses.")
        self.btn_dns.clicked.connect(self._open_dns)
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self._open_settings)
        self.btn_gateway = QPushButton("Share via hotspot")
        self.btn_gateway.setCheckable(True)
        if not hotspot.supported():
            tip = "Not available on this platform yet."
        elif hotspot.IS_WIN:
            tip = ("Route devices on this PC's Windows hotspot through the tunnel, "
                   "so phones need no setup of their own.")
        else:
            tip = ("Start a Wi-Fi hotspot whose devices use the tunnel, so phones need "
                   "no setup of their own. Its name and password appear in the log.")
        self.btn_gateway.setToolTip(tip)
        self.btn_gateway.setEnabled(hotspot.supported())
        self.btn_gateway.setChecked(self.settings["gateway"]["enabled"])
        self.btn_gateway.toggled.connect(self._toggle_gateway)

        actions2 = QHBoxLayout()
        actions2.addWidget(self.btn_low)
        actions2.addWidget(self.btn_gateway)
        actions2.addWidget(self.btn_bypass)
        actions2.addWidget(self.btn_dns)
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

        body = QWidget()
        body.setObjectName("WindowBody")
        cl = QHBoxLayout(body)
        cl.addWidget(splitter)
        if self._frameless:
            cl.setContentsMargins(14, 2, 14, 14)
            self.frame = QWidget()
            self.frame.setObjectName("WindowFrame")
            fl = QVBoxLayout(self.frame)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(0)
            self.titlebar = TitleBar(self)
            fl.addWidget(self.titlebar)
            fl.addWidget(body, 1)
            self.setCentralWidget(self.frame)
        else:
            cl.setContentsMargins(14, 14, 14, 14)
            self.titlebar = None
            self.setCentralWidget(body)

        # The shortcuts a Mac user reaches for; Ctrl stands in for Cmd off macOS.
        QShortcut(QKeySequence.Close, self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.showMinimized)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self._quit)
        # A focused text field (e.g. the filter box) claims Ctrl+V for its own
        # paste via ShortcutOverride before this ever fires, so normal typing
        # is unaffected; this only fires when nothing text-editable has focus.
        QShortcut(QKeySequence.Paste, self, activated=self._paste_import)

        self.profiles.importRequested.connect(self._import)
        self.profiles.editRequested.connect(self._edit)
        self.profiles.duplicateRequested.connect(self._duplicate)
        self.profiles.deleteRequested.connect(self._delete)
        self.profiles.deleteManyRequested.connect(self._delete_many)
        self.profiles.activated.connect(self._set_active)
        self.profiles.testRealDelayRequested.connect(lambda uids: self._start_test(uids, True))
        self.profiles.tcpPingRequested.connect(lambda uids: self._start_test(uids, False))
        self.profiles.cancelTestRequested.connect(self._cancel_test)
        self.profiles.useFastestRequested.connect(self._use_fastest)
        self.profiles.removeFailedRequested.connect(self._remove_failed)
        self.profiles.removeDuplicatesRequested.connect(self._remove_duplicates)
        self.subs_panel.addRequested.connect(self._add_sub)
        self.subs_panel.refreshRequested.connect(self._refresh_sub)
        self.subs_panel.deleteRequested.connect(self._delete_sub)
        self.tools.pingRequested.connect(lambda: self._run_tool(self._ping_fn))
        self.tools.delayRequested.connect(lambda: self._run_tool(self._delay_fn))
        self.tools.throughputRequested.connect(lambda: self._run_tool(self._throughput_fn))
        self.tools.baselineRequested.connect(lambda: self._run_tool(self._baseline_fn))
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
        self.tray.setToolTip("sushTun")
        menu = QMenu()
        menu.addAction("Show", self._show_window)
        menu.addAction("Connect", self._connect)
        menu.addAction("Disconnect", self._disconnect)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_window()
            if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()
        # Closing the window only hides it now; the app ends through Quit alone.
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        # Qt 6 asks every window to close before quitting; this lets ours agree.
        self._quitting = True
        QApplication.instance().quit()

    # Profiles --------------------------------------------------------------
    def _reload_profiles(self) -> None:
        profiles = self.store.list()
        self.results.prune([p.uid for p in profiles])
        self.profiles.set_results(self.results.load())
        self.profiles.set_sub_names({s.uid: s.name for s in self.subs.list()})
        self.profiles.set_profiles(profiles, self.store.active_uid())

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

    def _delete_many(self, uids: list) -> None:
        if QMessageBox.question(self, "Delete", f"Delete {len(uids)} server(s)?") == \
                QMessageBox.Yes:
            for uid in uids:
                self.store.delete(uid)
            self._reload_profiles()

    def _set_active(self, uid: str) -> None:
        self.store.set_active(uid)
        self._reload_profiles()
        self._refresh_status()

    def _paste_import(self) -> None:
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        profiles = importer.parse_share_text(text)
        if not profiles:
            self.step_label.setText("Clipboard has no importable server link.")
            return
        for p in profiles:
            self.store.save(p)
        if not self.store.active_uid():
            self.store.set_active(profiles[0].uid)
        self._reload_profiles()
        self.step_label.setText(f"Imported {len(profiles)} server(s).")

    # Speed test --------------------------------------------------------------
    def _start_test(self, uids: list, real: bool) -> None:
        if self._test_cancel is not None:
            return  # only one test run at a time
        profiles = [p for uid in uids if (p := self.store.get(uid))]
        if not profiles:
            return
        cancel = threading.Event()
        self._test_cancel = cancel
        self.profiles.set_testing(True)
        cfg = self.settings.get("speedtest", {})

        def work():
            if real:
                iface = network.detect_interface()
                if iface is None:
                    raise ValueError("no active internet interface")
                speedtest.real_delay_all(
                    profiles, self._emit_test_result, cancel,
                    url=cfg.get("url", "https://www.google.com/generate_204"),
                    timeout=cfg.get("timeout_s", 10),
                    batch_size=cfg.get("batch_size", 50),
                    iface_alias=iface.alias,
                    connected=self.conn.is_connected(),
                )
            else:
                speedtest.tcping_all(profiles, self._emit_test_result, cancel)

        def done(result=None, error=None):
            self._test_cancel = None
            self.profiles.set_testing(False)
            self.step_label.setText(f"Test failed: {error}" if error else "Test finished.")

        self._run_async(work, done)

    def _emit_test_result(self, uid: str, delay, error) -> None:
        # Called from speedtest's own worker threads; emitting queues
        # delivery onto the UI thread instead of touching widgets here.
        self.testResultReceived.emit(uid, delay, error)

    def _cancel_test(self) -> None:
        if self._test_cancel is not None:
            self._test_cancel.set()

    def _on_test_result(self, uid: str, delay, error) -> None:
        self.results.set(uid, delay_ms=delay, error=error)
        self.profiles.update_result(uid, delay, error)

    def _use_fastest(self, uid: str) -> None:
        profile = self.store.get(uid)
        self.store.set_active(uid)
        self._reload_profiles()
        name = profile.name if profile else ""
        if self.conn.is_connected():
            self.step_label.setText(f"Reconnect to switch to {name}.")
        else:
            self.step_label.setText(f"Active server set to {name}.")

    def _remove_failed(self) -> None:
        active = self.store.active_uid()
        failed = [p for p in self.store.list()
                  if p.uid != active and (self.results.get(p.uid) or {}).get("error")]
        if not failed:
            self.step_label.setText("No failed servers to remove.")
            return
        if QMessageBox.question(
            self, "Remove failed", f"Remove {len(failed)} failed server(s)?"
        ) == QMessageBox.Yes:
            for p in failed:
                self.store.delete(p.uid)
            self._reload_profiles()

    def _remove_duplicates(self) -> None:
        active = self.store.active_uid()
        seen: dict[tuple, Profile] = {}
        to_delete: list[str] = []
        for p in self.store.list():
            key = ((p.protocol or "").lower(), p.address, p.port, p.id)
            keeper = seen.get(key)
            if keeper is None:
                seen[key] = p
                continue
            if p.uid == active:
                # Never delete the active profile: keep it, drop the one
                # that was kept in its place instead.
                to_delete.append(keeper.uid)
                seen[key] = p
            else:
                to_delete.append(p.uid)
        if not to_delete:
            self.step_label.setText("No duplicate servers to remove.")
            return
        if QMessageBox.question(
            self, "Remove duplicates", f"Remove {len(to_delete)} duplicate server(s)?"
        ) == QMessageBox.Yes:
            for uid in to_delete:
                self.store.delete(uid)
            self._reload_profiles()

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
            self.tray.showMessage("sushTun", message, icon, 8000)

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

    def _baseline_fn(self) -> str:
        tun = self.conn.state.tun_index
        if tun is None:
            return "Not connected (no tunnel)."
        seconds = int(self.settings.get("sample_seconds", 5))
        s = metrics.baseline_sample(tun, self.conn.state.alias, seconds)
        if not s:
            return "Sampling failed (Windows only)."
        return metrics.format_baseline(s)

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

    def _check_route_health(self) -> None:
        if self._repairing or not self.conn.is_connected():
            return
        self._repairing = True

        def work():
            # DNS too: another program can silently clear the tunnel's resolver.
            fixed = (self.conn.repair_route_if_needed(), self.conn.repair_dns_if_needed())
            return [m for m in fixed if m]

        def done(result=None, error=None):
            self._repairing = False
            if result:
                self._refresh_status()

        self._run_async(work, done)

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

    def _open_dns(self) -> None:
        dlg = DnsDialog(self.settings["dns"], self)
        if dlg.exec():
            self.settings["dns"] = dlg.result_dns()
            app_settings.save(self.settings)
            self.step_label.setText("DNS saved — applies on next connect.")

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

    # Frameless window chrome ----------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._frameless and self._handle is None:
            # The native window only exists once shown. Its events arrive before any
            # child widget's, so the border stays resizable whatever sits under it.
            self._handle = self.windowHandle()
            if self._handle is not None:
                self._handle.installEventFilter(self)

    def _edges_at(self, pos) -> Qt.Edge:
        edges = Qt.Edge(0)
        if self.isMaximized() or self.isFullScreen():
            return edges
        m = _RESIZE_MARGIN
        if pos.x() < m:
            edges |= Qt.LeftEdge
        elif pos.x() >= self.width() - m:
            edges |= Qt.RightEdge
        if pos.y() < m:
            edges |= Qt.TopEdge
        elif pos.y() >= self.height() - m:
            edges |= Qt.BottomEdge
        return edges

    def eventFilter(self, obj, event) -> bool:
        if obj is not self._handle or self._handle is None:
            return super().eventFilter(obj, event)
        kind = event.type()
        if kind == QEvent.MouseMove and event.buttons() == Qt.NoButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self.setCursor(_EDGE_CURSORS[edges])
                self._edge_cursor = True
            elif self._edge_cursor:
                self.unsetCursor()
                self._edge_cursor = False
        elif kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges and self._handle.startSystemResize(edges):
                return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if self.titlebar is None:
            return
        if event.type() == QEvent.ActivationChange:
            self.titlebar.set_active(self.isActiveWindow())
        elif event.type() == QEvent.WindowStateChange:
            # Square, borderless corners when maximized, as on macOS.
            self.frame.setProperty("maximized", self.isMaximized() or self.isFullScreen())
            self.frame.style().unpolish(self.frame)
            self.frame.style().polish(self.frame)

    def closeEvent(self, event) -> None:
        # As on macOS, the red button closes the window but not the app: the
        # tunnel keeps running and the tray brings the window back.
        if self.tray is not None and not self._quitting:
            event.ignore()
            self.hide()
            if not self._told_about_tray:
                self._told_about_tray = True
                self.tray.showMessage(
                    "sushTun",
                    "Still running here. Quit from this icon's menu, or press Ctrl+Q.",
                    QSystemTrayIcon.Information, 5000,
                )
            return
        for t in (self.timer, self.alert_timer, self.autorefresh_timer, self.route_timer):
            t.stop()
        self.tailer.stop()
        if self._test_cancel is not None:
            self._test_cancel.set()  # don't leave a speed-test xray process behind
        self.pool.waitForDone(2000)
        super().closeEvent(event)
