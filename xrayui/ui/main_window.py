"""Main window: sidebar window with toolbar, pages, and status."""
from __future__ import annotations

import copy
import sys
import threading
import time

from PySide6.QtCore import QEvent, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core import alerts, hotspot, importer, metrics, network, speedtest
from ..core import autostart as autostart_mod
from ..core import geo as geo_mod
from ..core import settings as app_settings
from ..core import subscription as sub_mod
from ..core import updates as updates_mod
from ..core.alerts import human_bytes
from ..core.connection import Connection, _resolve
from ..core.profiles import Profile, ProfileStore
from ..core.xray import is_xray_running
from ..i18n import ltr, tr
from .dialogs import ImportDialog, ProfileEditDialog, SubscriptionEditDialog
from .dns_dialog import DnsDialog
from .icons import icon
from .log_tailer import LogTailer
from .mac import PopupButton
from .pages.dns_page import DnsPage
from .pages.leave import confirm_leave
from .pages.routing_page import RoutingPage
from .pages.servers_page import ServersPage
from .routing_dialog import RoutingDialog
from .settings_window import SettingsWindow
from .sidebar import Sidebar
from .subscription_panel import SubscriptionPanel
from .theme import ERR, HAIRLINE, MUTED, TEXT
from .titlebar import TitleBar
from .tools_panel import ToolsPanel
from .widgets import AlertBanner, LogView

# how far in from the border a press starts a resize on the frameless window
_RESIZE_MARGIN = 6
_MAX_TRAY_SERVERS = 20
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

PAGE_SERVERS = 0
PAGE_SUBS = 1
PAGE_ROUTING = 2
PAGE_DNS = 3
PAGE_ACTIVITY = 4

_MIN_W, _MIN_H = 820, 560


# ── toolbar ──────────────────────────────────────────────────────────────

class _Toolbar(QWidget):
    """52px top toolbar with title/subtitle, routing popup, toggles, filter."""

    def __init__(self, win: MainWindow) -> None:
        super().__init__()
        self._win = win
        self.setFixedHeight(52)
        self.setObjectName("Toolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#Toolbar{{background:transparent; border-bottom:1px solid {HAIRLINE};}}")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 0, 16, 0)
        outer.setSpacing(10)

        # title + subtitle
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        self.title = QLabel(tr("Servers"))
        self.title.setStyleSheet("font-size:13px; font-weight:600; background:transparent;")
        self.subtitle = QLabel(tr("Disconnected"))
        self.subtitle.setStyleSheet(
            f"font-size:11px; color:{MUTED}; background:transparent;")
        title_col.addWidget(self.title)
        title_col.addWidget(self.subtitle)
        outer.addLayout(title_col)

        outer.addStretch(1)

        # trailing: routing popup, anti-filter, low-usage, filter
        self.btn_routing_popup = PopupButton(tr("Routing"), tr("Simple"))
        self.btn_fragment = QPushButton(tr("Anti-filter"))
        self.btn_fragment.setCheckable(True)
        # Initial state set before the toggled hookup so a startup value that
        # matches the button's default fires no change event (toggled only
        # emits on an actual state flip).
        self.btn_fragment.setChecked(
            self._win.settings["core"]["fragment"]["enabled"])
        self.btn_fragment.setToolTip(tr(
            "Splits the TLS handshake into small pieces so filtering can't "
            "read it — try this if servers connect but sites won't load."))
        self.btn_fragment.setIcon(icon("anti-filter", TEXT))
        self.btn_fragment.setIconSize(self.btn_fragment.iconSize())
        self.btn_fragment.toggled.connect(self._win._toggle_fragment)
        self.btn_low = QPushButton()
        self.btn_low.setIcon(icon("leaf", TEXT))
        self.btn_low.setCheckable(True)
        self.btn_low.setChecked(self._win.settings["routing"]["low_usage"])
        self.btn_low.setToolTip(tr("Low usage"))
        self.btn_low.setAccessibleName(tr("Low usage"))
        self.btn_low.toggled.connect(self._win._toggle_low_usage)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(tr("Filter…"))
        self.filter_edit.setMaximumWidth(150)
        self.filter_edit.setVisible(False)
        self.filter_edit.setStyleSheet(
            "font-size:12px; padding:4px 8px; border-radius:6px;")

        for w in (self.btn_routing_popup, self.btn_fragment,
                  self.btn_low, self.filter_edit):
            outer.addWidget(w)

    # ── drag / zoom ───────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        handle = self._win.windowHandle()
        if handle is not None and handle.startSystemMove():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if self._win.isMaximized():
                self._win.showNormal()
            else:
                self._win.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


# ── main window ──────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    stepReceived = Signal(str)
    testResultReceived = Signal(str, object, object)

    def __init__(self, elevated: bool = True, autostart: bool = False) -> None:
        super().__init__()
        self._launched_via_autostart = autostart
        # changeEvent consults titlebar, so it must exist before any of the
        # window state setters below fire a Change event.
        self.titlebar = None
        self.setWindowTitle("sushTun")
        self.resize(1040, 700)
        self.setMinimumSize(_MIN_W, _MIN_H)
        self._frameless = sys.platform != "darwin"
        if self._frameless:
            self.setObjectName("Frameless")
            self.setWindowFlag(Qt.FramelessWindowHint)
            self.setAttribute(Qt.WA_TranslucentBackground)
        # Traffic lights: keep a TitleBar instance for test compat; we do NOT
        # show it here, we only add its .lights group into the sidebar.  Built
        # before _build_ui, which hands the lights group to the sidebar.  macOS
        # has its own native chrome, so it gets no TitleBar.
        self.titlebar = TitleBar(self) if self._frameless else None
        self._handle = None
        self._edge_cursor = False
        self._quitting = False
        self._told_about_tray = False
        self._current_page = PAGE_SERVERS

        # stores / core
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
        self._geo_updating = False

        self.stepReceived.connect(self._on_step)
        self.testResultReceived.connect(self._on_test_result)
        self._build_ui(elevated)
        self._build_tray()
        self._refresh_routing_combo()

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
        self.geo_timer = QTimer(self)
        self.geo_timer.timeout.connect(self._maybe_auto_update_geo)
        self.geo_timer.start(60 * 60_000)
        QTimer.singleShot(60_000, self._maybe_auto_update_geo)
        self.update_check_timer = QTimer(self)
        self.update_check_timer.timeout.connect(self._maybe_check_updates)
        self.update_check_timer.start(24 * 60 * 60_000)
        QTimer.singleShot(60_000, self._maybe_check_updates)

        self._reload_profiles()
        self._reload_subs()
        self._refresh_status()
        self._check_alerts()
        try:
            if self.conn.recover_if_stale(dns_retries=3):
                self._on_step(tr("Restored leftover network settings from a previous session."))
        except Exception as exc:
            self._on_step(tr("Could not restore leftover network settings: {error}", error=exc))
        self._refresh_status()
        self._reregister_autostart_if_enabled()
        self._auto_connect_on_startup()

    # ── autostart / auto-connect ──────────────────────────────────────────

    def _reregister_autostart_if_enabled(self) -> None:
        if sys.platform != "win32":
            return
        if not self.settings.get("startup", {}).get("start_on_login"):
            return
        try:
            autostart_mod.enable()
        except Exception as exc:
            self._on_step(tr("Could not refresh the login task: {error}", error=exc))

    def _auto_connect_on_startup(self) -> None:
        if not self.settings.get("startup", {}).get("auto_connect"):
            return
        profile = self._active_profile()
        if not profile:
            self._on_step(tr("Auto-connect skipped: no server selected."))
            return
        self._on_step(tr("Auto-connect: waiting for network to reach {name}…", name=profile.name))
        self._set_busy(True)

        def work():
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if network.detect_interface() is not None:
                    return self.conn.connect(profile)
                time.sleep(1)
            raise RuntimeError("no network interface found within 60s")

        def done(result=None, error=None):
            self._set_busy(False)
            if error:
                self._on_step(tr("Auto-connect failed: {error}", error=error))
                return
            self.btn_reconnect.setVisible(False)
            self._refresh_status()

        self._run_async(work, done)

    # ── UI construction ───────────────────────────────────────────────────

    @staticmethod
    def _scrolled(page: QWidget) -> QScrollArea:
        # A stacked widget is as tall as its tallest page; scrolling the long
        # Routing/DNS pages lets the whole window shrink to 820x560.
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(page)
        return area

    def _build_ui(self, elevated: bool) -> None:
        # --- core widgets used by test_ui ---------------------------------
        # The Servers page owns the connection header and the server table;
        # the old names stay as aliases because the wiring and tests use them.
        self.servers_page = ServersPage()
        self.status_card = self.servers_page.header
        self.profiles = self.servers_page.core
        # The toolbar's Filter field replaces the page's own filter row.
        self.profiles.filter_edit.hide()
        self.subs_panel = SubscriptionPanel()
        self.tools = ToolsPanel()
        self.log = LogView()
        self.log.setLayoutDirection(Qt.LeftToRight)
        self.alert_banner = AlertBanner()
        self.step_label = QLabel("")
        self.step_label.setObjectName("Muted")

        # alias for _on_conn_done / _reconnect_now / tests
        self.btn_connect = self.status_card.btn_connect
        self.btn_disconnect = self.status_card.btn_disconnect
        self.btn_reconnect = self.status_card.btn_reconnect

        # btn_cleanup: no longer a standalone button; menu-only in the ⋯
        # menu.  Keep a reference so _set_busy doesn't crash.
        self.btn_cleanup = None

        # routing combo: hidden, kept in sync with PopupButton
        self.routing_combo = QComboBox()
        self.routing_combo.setVisible(False)
        self.routing_combo.currentIndexChanged.connect(
            self._on_routing_combo_changed)

        # sidebar
        lights = (self.titlebar.lights
                  if self._frameless and self.titlebar is not None
                  else None)
        self.sidebar = Sidebar(traffic_lights=lights)
        self.sidebar.pageSelected.connect(self._show_page)
        self.sidebar.settingsRequested.connect(self._open_settings)
        self.sidebar.hotspotToggled.connect(self._toggle_gateway)

        if not hotspot.supported():
            tip = tr("Not available on this platform yet.")
        elif hotspot.IS_WIN:
            tip = tr("Route devices on this PC's Windows hotspot through "
                     "the tunnel, so phones need no setup of their own.")
        else:
            tip = tr("Start a Wi-Fi hotspot whose devices use the tunnel, "
                     "so phones need no setup of their own. Its name and "
                     "password appear in the log.")
        self.sidebar.set_hotspot_supported(hotspot.supported(), tip)
        self.sidebar.set_hotspot_state(
            self.settings["gateway"]["enabled"],
            self.settings["gateway"].get("ssid", ""),
            self.settings["gateway"].get("password", ""),
        )
        # btn_gateway is the Switch inside the sidebar
        self.btn_gateway = self.sidebar.btn_gateway

        # toolbar
        self.toolbar = _Toolbar(self)
        self.toolbar.filter_edit.textChanged.connect(
            self.profiles.proxy.set_needle)
        # aliases for tests / _set_busy-era slots
        self.btn_fragment = self.toolbar.btn_fragment
        self.btn_low = self.toolbar.btn_low

        # --- pages -------------------------------------------------------
        self._routing_page = RoutingPage(
            copy.deepcopy(self.settings["routing"]))
        self._routing_page.applied.connect(self._on_routing_applied)

        self._dns_page = DnsPage(
            copy.deepcopy(self.settings["dns"]),
            copy.deepcopy(self.settings["routing"]))
        self._dns_page.applied.connect(self._on_dns_applied)

        activity = QWidget()
        al = QVBoxLayout(activity)
        al.setContentsMargins(16, 12, 16, 12)
        tabs = QTabWidget()
        tabs.addTab(self.log, tr("Live log"))
        tabs.addTab(self.tools, tr("Tools"))
        al.addWidget(tabs)

        self._stack = QStackedWidget()
        # Servers: header + profile list
        servers_page = self.servers_page
        servers_page.layout().setContentsMargins(16, 12, 16, 12)
        # The real pages, by index; the stack may hold a scroll area instead.
        self._page_widgets = [servers_page, self.subs_panel,
                              self._routing_page, self._dns_page, activity]
        self._stack.addWidget(servers_page)                        # 0
        self._stack.addWidget(self.subs_panel)                     # 1
        self._stack.addWidget(self._scrolled(self._routing_page))  # 2
        self._stack.addWidget(self._scrolled(self._dns_page))      # 3
        self._stack.addWidget(activity)                            # 4

        # --- assemble central body ----------------------------------------
        content = QWidget()
        content.setObjectName("WindowBody")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.toolbar)
        cl.addWidget(self.alert_banner)
        cl.addWidget(self.step_label)
        cl.addWidget(self._stack, 1)

        if not elevated:
            warn = QLabel(tr("Not running as administrator — connecting will fail."))
            warn.setStyleSheet(f"color:{ERR}; padding:4px 16px;")
            cl.insertWidget(2, warn)

        body = QWidget()
        body.setObjectName("WindowBody")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(self.sidebar)
        bl.addWidget(content, 1)

        if self._frameless:
            self.frame = QWidget()
            self.frame.setObjectName("WindowFrame")
            fl = QVBoxLayout(self.frame)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(0)
            fl.addWidget(body, 1)
            self.setCentralWidget(self.frame)
            cl.setContentsMargins(0, 0, 0, 0)
        else:
            self.frame = None
            self.setCentralWidget(body)

        # --- shortcuts ---------------------------------------------------
        QShortcut(QKeySequence.Close, self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.showMinimized)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self._quit)
        QShortcut(QKeySequence.Paste, self, activated=self._paste_import)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self._open_settings)
        for _seq, idx in enumerate("12345"):
            QShortcut(QKeySequence(f"Ctrl+{idx}"), self,
                      activated=lambda _i=_seq: self._show_page(_i))

        # --- signal wiring -----------------------------------------------
        self.profiles.importRequested.connect(self._import)
        self.profiles.editRequested.connect(self._edit)
        self.profiles.duplicateRequested.connect(self._duplicate)
        self.profiles.deleteRequested.connect(self._delete)
        self.profiles.deleteManyRequested.connect(self._delete_many)
        self.profiles.activated.connect(self._set_active)
        self.profiles.testRealDelayRequested.connect(
            lambda uids: self._start_test(uids, True))
        self.profiles.tcpPingRequested.connect(
            lambda uids: self._start_test(uids, False))
        self.profiles.cancelTestRequested.connect(self._cancel_test)
        self.profiles.useFastestRequested.connect(self._use_fastest)
        self.profiles.removeFailedRequested.connect(self._remove_failed)
        self.profiles.removeDuplicatesRequested.connect(self._remove_duplicates)
        self.subs_panel.addRequested.connect(self._add_sub)
        self.subs_panel.refreshRequested.connect(self._refresh_sub)
        self.subs_panel.deleteRequested.connect(self._delete_sub)
        self.subs_panel.editRequested.connect(self._edit_sub)
        self.subs_panel.updateAllRequested.connect(self._update_all_subs)
        self.tools.pingRequested.connect(lambda: self._run_tool(self._ping_fn))
        self.tools.delayRequested.connect(lambda: self._run_tool(self._delay_fn))
        self.tools.throughputRequested.connect(
            lambda: self._run_tool(self._throughput_fn))
        self.tools.baselineRequested.connect(
            lambda: self._run_tool(self._baseline_fn))
        self.tools.diagnosticsRequested.connect(
            lambda: self._run_tool(self._diag_fn))
        self.status_card.restoreNetworkRequested.connect(self._cleanup)
        self.status_card.reconnectRequested.connect(self._reconnect_now)

        self._update_page_ui(self._current_page)

    # ── tray ──────────────────────────────────────────────────────────────

    def _build_tray(self) -> None:
        from .icon import app_icon as _app_icon
        _icon = _app_icon()
        self.setWindowIcon(_icon)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            self.routing_menu = None
            self.servers_menu = None
            return
        self.tray = QSystemTrayIcon(_icon, self)
        self.tray.setToolTip("sushTun")
        menu = QMenu()
        menu.addAction(tr("Show"), self._show_window)
        menu.addAction(tr("Connect"), self._connect)
        menu.addAction(tr("Disconnect"), self._disconnect)
        menu.addSeparator()
        self.servers_menu = menu.addMenu(tr("Servers"))
        self.routing_menu = menu.addMenu(tr("Routing"))
        menu.addSeparator()
        menu.addAction(tr("Quit"), self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_window()
            if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        QApplication.instance().quit()

    # ── page switching ────────────────────────────────────────────────────

    def _show_page(self, index: int) -> None:
        if index == self._current_page:
            return
        # dirty page guard for routing / dns
        # The stack holds a scroll area for Routing/DNS, not the page itself.
        old_page = self._page_widgets[self._current_page]
        if (hasattr(old_page, "is_dirty") and old_page.is_dirty()
                and not confirm_leave(old_page, self)):
            self.sidebar.set_current_page(self._current_page)
            return
        self._current_page = index
        self._stack.setCurrentIndex(index)
        self.sidebar.set_current_page(index)
        self._update_page_ui(index)

    def _update_page_ui(self, index: int) -> None:
        titles = {
            PAGE_SERVERS: tr("Servers"),
            PAGE_SUBS: tr("Subscriptions"),
            PAGE_ROUTING: tr("Routing"),
            PAGE_DNS: tr("DNS"),
            PAGE_ACTIVITY: tr("Activity"),
        }
        self.toolbar.title.setText(titles.get(index, ""))
        self.toolbar.filter_edit.setVisible(index == PAGE_SERVERS)
        self._refresh_status_subtitle()

    def _refresh_status_subtitle(self) -> None:
        connected = self.conn.is_connected()
        profile = self._active_profile()
        if connected and profile:
            self.toolbar.subtitle.setText(
                ltr(tr("Connected · {server}",
                       server=profile.name)))
        else:
            self.toolbar.subtitle.setText(tr("Disconnected"))

    # ── profiles ----------------------------------------------------------

    def _reload_profiles(self) -> None:
        profiles = self.store.list()
        self.results.prune([p.uid for p in profiles])
        self.profiles.set_results(self.results.load())
        self.profiles.set_sub_names(
            {s.uid: s.name for s in self.subs.list()})
        self.profiles.set_profiles(profiles, self.store.active_uid())
        self._rebuild_servers_tray_menu()

    def _active_profile(self) -> Profile | None:
        uid = self.store.active_uid() or self.profiles.current_uid()
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
        if QMessageBox.question(self, tr("Delete"),
                                tr("Delete '{name}'?", name=profile.name)) \
                == QMessageBox.Yes:
            self.store.delete(uid)
            self._reload_profiles()

    def _delete_many(self, uids: list) -> None:
        if QMessageBox.question(self, tr("Delete"),
                                tr("Delete {n} server(s)?", n=len(uids))) \
                == QMessageBox.Yes:
            for uid in uids:
                self.store.delete(uid)
            self._reload_profiles()

    def _set_active(self, uid: str) -> None:
        self.store.set_active(uid)
        self.profiles.set_active(uid)
        self._rebuild_servers_tray_menu()
        self._refresh_status()

    def _activate_from_tray(self, uid: str) -> None:
        self._set_active(uid)
        if self.conn.is_connected():
            self._needs_reconnect(tr("Active server changed"))

    def _paste_import(self) -> None:
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        profiles = importer.parse_share_text(text)
        if not profiles:
            self.step_label.setText(
                tr("Clipboard has no importable server link."))
            return
        for p in profiles:
            self.store.save(p)
        if not self.store.active_uid():
            self.store.set_active(profiles[0].uid)
        self._reload_profiles()
        self.step_label.setText(
            tr("Imported {n} server(s).", n=len(profiles)))

    # ── speed test --------------------------------------------------------

    def _start_test(self, uids: list, real: bool) -> None:
        if self._test_cancel is not None:
            return
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
                    raise ValueError(tr("no active internet interface"))
                speedtest.real_delay_all(
                    profiles, self._emit_test_result, cancel,
                    url=cfg.get("url", "https://www.google.com/generate_204"),
                    timeout=cfg.get("timeout_s", 10),
                    batch_size=cfg.get("batch_size", 50),
                    iface_alias=iface.alias,
                    connected=self.conn.is_connected())
            else:
                speedtest.tcping_all(profiles, self._emit_test_result, cancel)

        def done(result=None, error=None):
            self._test_cancel = None
            self.profiles.set_testing(False)
            self.step_label.setText(
                tr("Test failed: {error}", error=error)
                if error else tr("Test finished."))

        self._run_async(work, done)

    def _emit_test_result(self, uid: str, delay, error) -> None:
        self.testResultReceived.emit(uid, delay, error)

    def _cancel_test(self) -> None:
        if self._test_cancel is not None:
            self._test_cancel.set()

    def _on_test_result(self, uid: str, delay, error) -> None:
        skipped = speedtest.is_skipped(error)
        self.results.set(uid, delay_ms=delay, error=error, skipped=skipped)
        self.profiles.update_result(uid, delay, error, skipped)
        self._rebuild_servers_tray_menu()

    def _use_fastest(self, uid: str) -> None:
        profile = self.store.get(uid)
        self.store.set_active(uid)
        self._reload_profiles()
        name = profile.name if profile else ""
        if self.conn.is_connected():
            self._needs_reconnect(
                tr("Active server set to {name}", name=name))
        else:
            self.step_label.setText(
                tr("Active server set to {name}.", name=name))

    def _remove_failed(self) -> None:
        active = self.store.active_uid()
        failed = []
        for p in self.store.list():
            if p.uid == active:
                continue
            r = self.results.get(p.uid) or {}
            if r.get("error") and not r.get("skipped"):
                failed.append(p)
        if not failed:
            self.step_label.setText(tr("No failed servers to remove."))
            return
        if QMessageBox.question(
            self, tr("Remove failed"),
            tr("Remove {n} failed server(s)?", n=len(failed))) \
                == QMessageBox.Yes:
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
                to_delete.append(keeper.uid)
                seen[key] = p
            else:
                to_delete.append(p.uid)
        if not to_delete:
            self.step_label.setText(tr("No duplicate servers to remove."))
            return
        if QMessageBox.question(
            self, tr("Remove duplicates"),
            tr("Remove {n} duplicate server(s)?", n=len(to_delete))) \
                == QMessageBox.Yes:
            for uid in to_delete:
                self.store.delete(uid)
            self._reload_profiles()

    # ── subscriptions -----------------------------------------------------

    def _reload_subs(self) -> None:
        subs_list = self.subs.list()
        self.subs_panel.set_subscriptions(subs_list)
        self.sidebar.set_subscription_count(len(subs_list))

    def _add_sub(self) -> None:
        dlg = SubscriptionEditDialog(sub_mod.Subscription(), self)
        if not dlg.exec():
            return
        sub = dlg.result_subscription()
        self.subs.save(sub)
        self._reload_subs()
        self._refresh_sub(sub.uid)

    def _edit_sub(self, uid: str) -> None:
        sub = next((s for s in self.subs.list() if s.uid == uid), None)
        if not sub:
            return
        dlg = SubscriptionEditDialog(sub, self)
        if dlg.exec():
            self.subs.save(dlg.result_subscription())
            self._reload_subs()

    def _refresh_sub(self, uid: str) -> None:
        sub = next((s for s in self.subs.list() if s.uid == uid), None)
        if not sub:
            return
        self.step_label.setText(
            tr("Refreshing {name}…", name=sub.name))

        def done(result=None, error=None):
            if error:
                self.step_label.setText(
                    tr("Subscription refresh failed: {error}", error=error))
            else:
                self.step_label.setText(tr("Subscription updated."))
            self._reload_subs()
            self._reload_profiles()
            self._check_alerts()

        self._run_async(lambda: sub_mod.refresh(sub, self.store, self.subs),
                        done)

    def _delete_sub(self, uid: str) -> None:
        if QMessageBox.question(self, tr("Delete"),
                                tr("Delete subscription and its profiles?")) \
                == QMessageBox.Yes:
            self.subs.delete(uid, self.store)
            self._reload_subs()
            self._reload_profiles()

    def _update_all_subs(self) -> None:
        subs = [s for s in self.subs.list() if s.enabled]
        if not subs:
            self.step_label.setText(tr("No enabled subscriptions to update."))
            return
        self.step_label.setText(
            tr("Updating 0 of {n} subscriptions…", n=len(subs)))

        def work():
            updated = 0
            first_error: str | None = None
            for sub in subs:
                try:
                    sub_mod.refresh(sub, self.store, self.subs)
                    updated += 1
                except Exception as exc:
                    if first_error is None:
                        first_error = str(exc)
            return updated, len(subs), first_error

        def done(result=None, error=None):
            if error:
                self.step_label.setText(
                    tr("Update all failed: {error}", error=error))
            else:
                updated, total, first_error = result
                msg = tr("Updated {n} of {total} subscriptions.",
                         n=updated, total=total)
                if first_error:
                    msg += " " + tr("First error: {error}", error=first_error)
                self.step_label.setText(msg)
            self._reload_subs()
            self._reload_profiles()
            self._check_alerts()

        self._run_async(work, done)

    def _auto_refresh_subs(self) -> None:
        global_hours = self.settings.get("alerts", {}) \
            .get("auto_refresh_hours", 6)
        now = time.time()
        for sub in self.subs.list():
            if sub_mod.is_due(sub, global_hours, now):
                self._refresh_sub(sub.uid)

    # ── alerts / updates --------------------------------------------------

    def _check_alerts(self) -> None:
        cfg = self.settings.get("alerts", {})
        triggered = []
        for sub in self.subs.list():
            for alert in alerts.evaluate(sub, cfg):
                if self.throttle.allow(alert.key):
                    triggered.append(alert)
        if not triggered:
            return
        level = ("critical"
                 if any(a.level == "critical" for a in triggered)
                 else "warning")
        message = "  •  ".join(
            tr(a.template, **a.params) if a.template else a.message
            for a in triggered)
        self.alert_banner.show_alert(level, message)
        if self.tray:
            icon = (QSystemTrayIcon.Critical
                    if level == "critical"
                    else QSystemTrayIcon.Warning)
            self.tray.showMessage("sushTun", message, icon, 8000)

    def _maybe_check_updates(self) -> None:
        cfg = self.settings.get("updates", {})
        if not cfg.get("check", True):
            return
        last_check = cfg.get("last_check") or 0
        if time.time() - last_check < 24 * 60 * 60:
            return
        self._run_async(updates_mod.latest_release, self._on_update_checked)

    def _on_update_checked(self, result=None, error=None) -> None:
        self.settings.setdefault("updates", {})["last_check"] = time.time()
        app_settings.save(self.settings)
        if error or not result:
            return
        tag, url = result
        if not updates_mod.is_newer(tag, __version__):
            return
        self.alert_banner.show_alert(
            "warning", tr("sushTun {tag} is available", tag=tag),
            action_label=tr("Copy download link"),
            action=lambda: QApplication.clipboard().setText(url))
        if (self.tray
                and self.settings["updates"].get("notified_version") != tag):
            self.tray.showMessage(
                "sushTun",
                tr("sushTun {tag} is available", tag=tag),
                QSystemTrayIcon.Information, 8000)
            self.settings["updates"]["notified_version"] = tag
            app_settings.save(self.settings)

    # ── connection --------------------------------------------------------

    def _connect(self) -> None:
        if self._busy:
            return
        profile = self._active_profile()
        if not profile:
            QMessageBox.information(
                self, tr("No profile"),
                tr("Import or select a profile first."))
            return
        self.store.set_active(profile.uid)
        self._set_busy(True)
        self.log.append_line(
            f"Connecting to {profile.name} ({profile.endpoint})…")
        self._run_async(lambda: self.conn.connect(profile),
                        self._on_conn_done)

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
            QMessageBox.warning(self, tr("Connection"), error)
        self.btn_reconnect.setVisible(False)
        self._refresh_status()

    def _on_step(self, msg: str) -> None:
        self.step_label.setText(tr(msg))
        self.log.append_line(f">> {msg}")

    # ── tools -------------------------------------------------------------

    def _run_tool(self, fn) -> None:
        if self._busy:
            return
        self.tools.set_busy(True)
        self.tools.set_result(tr("Working…"))

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
            lines.append(
                f"Attempt {i}: {round(r)} ms"
                if r is not None else f"Attempt {i}: failed")
        if d["avg"] is not None:
            lines.append(
                f"\nAvg {round(d['avg'])} ms  "
                f"Min {round(d['min'])} ms  Max {round(d['max'])} ms")
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
        return metrics.diagnostics(
            server_ip, self.conn.state.alias, self.conn.state.tun_index)

    # ── status ------------------------------------------------------------

    def _refresh_status(self) -> None:
        connected = self.conn.is_connected()
        self.status_card.set_connected(connected)
        profile = self._active_profile()
        self.status_card.set("endpoint",
                             profile.endpoint if profile else "—")
        self.status_card.set(
            "process",
            tr("RUNNING") if is_xray_running() else tr("STOPPED"))
        st = self.conn.state
        self.status_card.set("iface", st.alias or "—")
        self.status_card.set("ip", st.ipv4 or "—")
        self.status_card.set("gateway", st.gateway or "—")
        self.status_card.set("tun",
                             str(st.tun_index) if st.tun_index else "—")
        self.btn_connect.setEnabled(not connected and not self._busy)
        self.btn_disconnect.setEnabled(connected and not self._busy)
        self._refresh_status_subtitle()
        if (connected and not self._sampling
                and st.tun_index is not None):
            self._sample_live(st.tun_index)

    def _check_route_health(self) -> None:
        if self._repairing or not self.conn.is_connected():
            return
        self._repairing = True

        def work():
            fixed = (self.conn.repair_route_if_needed(),
                     self.conn.repair_dns_if_needed())
            return [m for m in fixed if m]

        def done(result=None, error=None):
            self._repairing = False
            if result:
                self._refresh_status()

        self._run_async(work, done)

    def _sample_live(self, tun: int) -> None:
        self._sampling = True

        def work():
            return {
                "rate": metrics.throughput_sample(tun, 1),
                "stats": metrics.query_stats()}

        def done(result=None, error=None):
            self._sampling = False
            if not result:
                return
            rate = result.get("rate")
            stats = result.get("stats")
            if rate:
                self.status_card.set(
                    "throughput",
                    f"↓ {rate['rx_mbps']}  ↑ {rate['tx_mbps']} Mbit/s")
            if stats:
                self.status_card.set(
                    "used",
                    f"↓ {human_bytes(stats['down'])}  "
                    f"↑ {human_bytes(stats['up'])}")

        self._run_async(work, done)

    # ── settings / routing ------------------------------------------------

    def _needs_reconnect(self, what: str) -> None:
        self.step_label.setText(
            tr("{what} — reconnect to apply.", what=what))
        if self.conn.is_connected():
            self.status_card.show_reconnect(self.step_label.text())

    def _reconnect_now(self) -> None:
        if self._busy:
            return
        profile = self._active_profile()
        if not profile:
            return
        self._set_busy(True)

        def work():
            self.conn.disconnect()
            self.conn.connect(profile)

        self._run_async(work, self._on_conn_done)

    def _open_settings(self) -> None:
        old_mtu = self.settings.get("tun_mtu")
        old_log = self.settings.get("log_level")
        old_core = copy.deepcopy(self.settings.get("core"))
        dlg = SettingsWindow(self.settings, self)
        if dlg.exec():
            values = dlg.values()
            self.settings.update(values)
            app_settings.save(self.settings)
            self.toolbar.btn_fragment.setChecked(
                self.settings["core"]["fragment"]["enabled"])
            changed = [label for label, old, new in (
                (tr("MTU"), old_mtu, values["tun_mtu"]),
                (tr("Log level"), old_log, values["log_level"]),
                (tr("Core options"), old_core, values["core"]),
            ) if old != new]
            if changed:
                self._needs_reconnect(
                    tr("{items} changed", items=", ".join(changed)))
            elif dlg.geo_updated():
                self._needs_reconnect(tr("Geo data updated"))
        if dlg.restored():
            self.settings = app_settings.load()
            self._reload_profiles()
            self._reload_subs()
            self._refresh_routing_combo()
            if self.conn.is_connected():
                self._needs_reconnect(tr("Settings restored from backup"))

    def _open_routing(self) -> None:
        dlg = RoutingDialog(self.settings["routing"], self)
        if dlg.exec():
            self.settings["routing"] = dlg.result_routing()
            app_settings.save(self.settings)
            self.toolbar.btn_low.setChecked(
                self.settings["routing"]["low_usage"])
            self._refresh_routing_combo()
            self._needs_reconnect(tr("Routing saved"))
            self._routing_page.load(copy.deepcopy(self.settings["routing"]))

    def _open_dns(self) -> None:
        dlg = DnsDialog(self.settings["dns"],
                        self.settings["routing"], self)
        if dlg.exec():
            self.settings["dns"] = dlg.result_dns()
            app_settings.save(self.settings)
            self._needs_reconnect(tr("DNS saved"))
            self._dns_page.load(copy.deepcopy(self.settings["dns"]),
                                copy.deepcopy(self.settings["routing"]))

    def _on_routing_applied(self, cfg) -> None:
        self.settings["routing"] = cfg
        app_settings.save(self.settings)
        self.toolbar.btn_low.setChecked(
            self.settings["routing"]["low_usage"])
        self._refresh_routing_combo()
        self._needs_reconnect(tr("Routing saved"))

    def _on_dns_applied(self, cfg) -> None:
        self.settings["dns"] = cfg
        app_settings.save(self.settings)
        self._needs_reconnect(tr("DNS saved"))

    def _toggle_low_usage(self, checked: bool) -> None:
        self.settings["routing"]["low_usage"] = checked
        app_settings.save(self.settings)
        self._needs_reconnect(
            tr("Low usage on") if checked else tr("Low usage off"))

    def _toggle_fragment(self, checked: bool) -> None:
        self.settings["core"]["fragment"]["enabled"] = checked
        app_settings.save(self.settings)
        self._needs_reconnect(
            tr("Anti-filter on") if checked else tr("Anti-filter off"))

    # ── routing mode ──────────────────────────────────────────────────────

    def _refresh_routing_combo(self) -> None:
        routing_cfg = self.settings.get("routing", {})
        mode = routing_cfg.get("mode") or "simple"
        self.routing_combo.blockSignals(True)
        self.routing_combo.clear()
        self.routing_combo.addItem(tr("Simple"), "simple")
        for s in routing_cfg.get("sets") or []:
            self.routing_combo.addItem(
                s.get("name") or tr("Unnamed"), s.get("id"))
        idx = self.routing_combo.findData(mode)
        self.routing_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.routing_combo.blockSignals(False)
        self._rebuild_routing_tray_menu()
        # sync the PopupButton
        current_label = self.routing_combo.currentText()
        self.toolbar.btn_routing_popup.set_value(current_label)
        self._build_routing_popup_menu(routing_cfg, mode)

    def _build_routing_popup_menu(self, routing_cfg: dict,
                                  current_mode: str) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self.toolbar.btn_routing_popup)
        items = [(tr("Simple"), "simple")] + [
            (s.get("name") or tr("Unnamed"), s.get("id"))
            for s in routing_cfg.get("sets") or []]
        group = QActionGroup(menu)
        group.setExclusive(True)
        self._popup_routing_group = group
        for label, value in items:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == current_mode)
            action.triggered.connect(
                lambda _c=False, v=value: self._set_routing_mode(v))
            group.addAction(action)
        self.toolbar.btn_routing_popup.set_menu(menu)

    def _on_routing_combo_changed(self, _index: int) -> None:
        mode = self.routing_combo.currentData()
        if mode is not None:
            self._set_routing_mode(mode)

    def _rebuild_servers_tray_menu(self) -> None:
        if self.servers_menu is None:
            return
        self.servers_menu.clear()
        active_uid = self.store.active_uid()
        results = self.results.load()
        group = QActionGroup(self.servers_menu)
        group.setExclusive(True)
        self._servers_action_group = group
        for uid in self.profiles.visible_uids()[:_MAX_TRAY_SERVERS]:
            profile = self.store.get(uid)
            if not profile:
                continue
            delay = (results.get(uid) or {}).get("delay_ms")
            label = (f"{profile.name} · {delay:.0f} ms"
                     if isinstance(delay, (int, float))
                     else profile.name)
            action = self.servers_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(uid == active_uid)
            action.triggered.connect(
                lambda _c=False, u=uid: self._activate_from_tray(u))
            group.addAction(action)

    def _rebuild_routing_tray_menu(self) -> None:
        if self.routing_menu is None:
            return
        self.routing_menu.clear()
        routing_cfg = self.settings.get("routing", {})
        mode = routing_cfg.get("mode") or "simple"
        items = [(tr("Simple"), "simple")] + [
            (s.get("name") or tr("Unnamed"), s.get("id"))
            for s in routing_cfg.get("sets") or []]
        group = QActionGroup(self.routing_menu)
        group.setExclusive(True)
        self._routing_action_group = group
        for label, value in items:
            action = self.routing_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == mode)
            action.triggered.connect(
                lambda _c=False, v=value: self._set_routing_mode(v))
            group.addAction(action)

    def _set_routing_mode(self, mode: str) -> None:
        if mode == (self.settings["routing"].get("mode") or "simple"):
            return
        self.settings["routing"]["mode"] = mode
        app_settings.save(self.settings)
        idx = self.routing_combo.findData(mode)
        self.routing_combo.blockSignals(True)
        self.routing_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.routing_combo.blockSignals(False)
        self._rebuild_routing_tray_menu()
        label = self.routing_combo.currentText()
        self.toolbar.btn_routing_popup.set_value(label)
        self._build_routing_popup_menu(self.settings["routing"], mode)
        self._needs_reconnect(tr("Routing changed"))

    # ── geo data ----------------------------------------------------------

    def _maybe_auto_update_geo(self) -> None:
        if self._geo_updating:
            return
        geo_cfg = self.settings.get("geo", {})
        hours = geo_cfg.get("auto_update_hours", 0)
        last = geo_cfg.get("last_update", 0)
        if not geo_mod.is_due(last, hours):
            return
        self._geo_updating = True
        source = geo_cfg.get("source", "Loyalsoldier")

        def done(result=None, error=None):
            self._geo_updating = False
            if error:
                self.log.append_line(
                    f">> Geo auto-update failed: {error}")
                return
            self.settings["geo"]["last_update"] = time.time()
            app_settings.save(self.settings)
            if self.conn.is_connected():
                self._needs_reconnect(tr("Geo data updated"))
            else:
                self.step_label.setText(tr("Geo data updated."))

        self._run_async(lambda: geo_mod.update(source), done)

    def _toggle_gateway(self, checked: bool) -> None:
        self.settings["gateway"]["enabled"] = checked
        app_settings.save(self.settings)
        self.sidebar.set_hotspot_state(
            checked,
            self.settings["gateway"].get("ssid", ""),
            self.settings["gateway"].get("password", ""),
        )
        if not checked and self.conn.is_connected():
            self._run_async(
                self.conn.stop_gateway,
                lambda result=None, error=None: None)
            self.step_label.setText(tr("Hotspot sharing off."))
            return
        self.step_label.setText(
            tr("Hotspot sharing on — applies on next connect.")
            if checked else tr("Hotspot sharing off."))

    # ── worker plumbing ---------------------------------------------------

    def _run_async(self, fn, done) -> None:
        from .workers import Worker
        worker = Worker(fn)

        def finish(result=None, error=None):
            self._workers.discard(worker)
            done(result=result, error=error)

        worker.signals.finished.connect(lambda r: finish(result=r))
        worker.signals.error.connect(lambda e: finish(error=e))
        self._workers.add(worker)
        self.pool.start(worker)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_connect.setEnabled(not busy)
        self.btn_disconnect.setEnabled(not busy)
        if self.status_card.btn_more is not None:
            self.status_card.btn_more.setEnabled(not busy)

    # ── frameless window chrome -------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._frameless and self._handle is None:
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
        elif (kind == QEvent.MouseButtonPress
              and event.button() == Qt.LeftButton):
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
        if self.frame is not None and event.type() == QEvent.WindowStateChange:
            maximized = self.isMaximized() or self.isFullScreen()
            self.frame.setProperty("maximized", maximized)
            self.frame.style().unpolish(self.frame)
            self.frame.style().polish(self.frame)

    def closeEvent(self, event) -> None:
        if self.tray is not None and not self._quitting:
            event.ignore()
            self.hide()
            if not self._told_about_tray:
                self._told_about_tray = True
                self.tray.showMessage(
                    "sushTun",
                    tr("Still running here. Quit from this icon's menu, "
                       "or press Ctrl+Q."),
                    QSystemTrayIcon.Information, 5000)
            return
        for t in (self.timer, self.alert_timer, self.autorefresh_timer,
                  self.route_timer, self.geo_timer):
            t.stop()
        self.tailer.stop()
        if self._test_cancel is not None:
            self._test_cancel.set()
        self.pool.waitForDone(2000)
        super().closeEvent(event)
