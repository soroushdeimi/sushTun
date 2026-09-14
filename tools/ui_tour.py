"""A scripted tour of the real sushTun UI, offscreen, in en and fa, at two
window sizes -- for a human to eyeball and for a handful of automated
layout checks (clipping, overlap, off-window widgets, icon-only buttons
with no tooltip, an English string surviving into fa).

NOT shipped: nothing under xrayui/ imports this, and PyInstaller's
Analysis in tools/build.spec only walks from app_main.py, so this file
is already outside every build's dependency graph.

Run:
    QT_QPA_PLATFORM=offscreen .venv/bin/python tools/ui_tour.py [out_dir]

Writes <out_dir>/<lang>/<size>/NN_<name>.png plus <out_dir>/index.txt and
<out_dir>/findings.txt. Every widget in the tour is fake: Connection,
network, metrics and xraycheck are all stubbed before the first window is
built, so this never touches real routes, DNS, or a system tray, and
needs no bundled xray binary.
"""
from __future__ import annotations

import copy
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QRect, Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QWidget,
)

SIZES = [("1040x700", 1040, 700), ("820x560", 820, 560)]
LANGS = ["en", "fa"]
_FA_FONTS = '"Vazirmatn", "Noto Sans Arabic", "Segoe UI", "Tahoma", "Geeza Pro"'


# -- stubs: nothing here may touch the real system --------------------------
def install_stubs() -> None:
    from xrayui.core import connection as connection_mod
    from xrayui.core import hotspot, metrics, network, xraycheck
    from xrayui.core.xray import is_xray_running as _unused  # noqa: F401
    from xrayui.ui import main_window as mw

    class FakeConnection:
        def __init__(self, on_step=None) -> None:
            self._log = on_step or (lambda _m: None)
            self._connected = False
            self.state = _FakeState()

        def is_connected(self) -> bool:
            return self._connected

        def connect(self, profile) -> None:
            self._connected = True

        def disconnect(self) -> None:
            self._connected = False

        def cleanup(self) -> None:
            self._connected = False

        def recover_if_stale(self, dns_retries: int = 8) -> bool:
            return False

        def repair_route_if_needed(self):
            return None

        def repair_dns_if_needed(self):
            return None

        def stop_gateway(self):
            return None

    class _FakeState:
        alias = "Ethernet"
        ipv4 = "10.10.0.2"
        gateway = "10.10.0.1"
        tun_index = None  # keeps _sample_live() from firing

        def is_connected(self) -> bool:
            return False

    connection_mod.Connection = FakeConnection
    mw.Connection = FakeConnection
    mw.is_xray_running = lambda: False
    network.detect_interface = lambda: None
    hotspot.supported = lambda: False
    xraycheck.check_config = lambda *a, **k: None
    xraycheck.check_rules = lambda *a, **k: None
    metrics.ping = lambda *a, **k: "(stubbed)"
    metrics.tcp_connect_delay = lambda *a, **k: {"results": [], "avg": None, "min": None,
                                                 "max": None}
    metrics.throughput_sample = lambda *a, **k: None
    metrics.query_stats = lambda *a, **k: None
    metrics.baseline_sample = lambda *a, **k: None
    metrics.diagnostics = lambda *a, **k: "(stubbed)"


# -- seed data ----------------------------------------------------------------
def seed_data(base_dir: Path, language: str) -> None:
    from xrayui import paths
    from xrayui.core import settings as app_settings
    from xrayui.core.profiles import Profile, ProfileStore
    from xrayui.core.speedtest import ResultStore
    from xrayui.core.subscription import Subscription, SubscriptionStore, Usage

    paths.base_dir = lambda: base_dir
    paths.state_dir = lambda: base_dir / "state"
    paths.profiles_dir = lambda: base_dir / "profiles"
    paths.ensure_dirs()

    settings = copy.deepcopy(app_settings.DEFAULTS)
    settings["language"] = language
    settings["routing"]["sets"] = [
        {
            "id": "set-1", "name": "Work rules", "domain_strategy": "",
            "rules": [
                {"remarks": "Ads blocked", "enabled": True, "outbound": "block",
                 "domain": ["geosite:category-ads-all"], "ip": [], "port": "",
                 "network": "", "protocol": [], "process": []},
                {"remarks": "LAN direct", "enabled": True, "outbound": "direct",
                 "domain": ["geosite:private"], "ip": ["geoip:private"], "port": "",
                 "network": "", "protocol": [], "process": []},
            ],
        },
        {
            "id": "set-2", "name": "Streaming", "domain_strategy": "IPIfNonMatch",
            "rules": [
                {"remarks": "Force proxy", "enabled": True, "outbound": "proxy",
                 "domain": ["netflix.com"], "ip": [], "port": "", "network": "",
                 "protocol": [], "process": []},
            ],
        },
    ]
    app_settings.save(settings)

    store = ProfileStore()
    profiles = {}
    profiles["reality"] = store.save(Profile(
        name="Frankfurt Reality", protocol="vless", address="de.example.com", port=443,
        id="11111111-1111-1111-1111-111111111111", network="tcp", security="reality",
        sni="www.microsoft.com", fp="chrome", pbk="MjJyOOxAQ0m9MJp368E7lLKmXQz0GBBpuF12E-B6H1Q",
        sid="ab",
    ))
    profiles["trojan"] = store.save(Profile(
        name="Amsterdam WS", protocol="trojan", address="nl.example.com", port=443,
        id="hunter2-password", network="ws", security="tls", sni="nl.example.com",
        path="/ws", host="nl.example.com",
    ))
    profiles["vmess"] = store.save(Profile(
        name="Tokyo gRPC", protocol="vmess", address="jp.example.com", port=443,
        id="22222222-2222-2222-2222-222222222222", network="grpc", security="tls",
        sni="jp.example.com", service_name="grpc-svc", vmess_security="auto",
    ))
    profiles["shadowsocks"] = store.save(Profile(
        name="Singapore SS", protocol="shadowsocks", address="sg.example.com", port=8388,
        id="s3cret-password", ss_method="2022-blake3-aes-256-gcm",
    ))
    profiles["hysteria2"] = store.save(Profile(
        name="London Hy2", protocol="hysteria2", address="uk.example.com", port=443,
        id="hy2-password", hy2_obfs_password="obfs-pw", hy2_ports="20000-30000",
    ))
    profiles["wireguard"] = store.save(Profile(
        name="Home WG", protocol="wireguard", address="1.2.3.4", port=51820,
        id="cHJpdmF0ZWtleWV4YW1wbGUxMjM0NTY3ODkwMTI=",
        pbk="cHVibGlja2V5ZXhhbXBsZTEyMzQ1Njc4OTAxMg==", wg_local_address="10.0.0.2/32",
    ))
    store.set_active(profiles["reality"].uid)

    results = ResultStore()
    results.set(profiles["reality"].uid, delay_ms=85.0, error=None, skipped=False)
    results.set(profiles["trojan"].uid, delay_ms=650.0, error=None, skipped=False)
    results.set(profiles["vmess"].uid, delay_ms=None, error="connection refused", skipped=False)
    results.set(profiles["shadowsocks"].uid, delay_ms=None, error="n/a (UDP)", skipped=True)
    # hysteria2 stays untested: no result recorded at all.
    results.set(profiles["wireguard"].uid, delay_ms=45.0, error=None, skipped=False)

    subs = SubscriptionStore()
    subs.save(Subscription(
        name="Main plan", url="https://sub.example.com/main", enabled=True,
        usage=Usage(upload=2_000_000_000, download=78_000_000_000, total=100_000_000_000,
                   expire=0),
        updated=time.time(),
    ))
    subs.save(Subscription(
        name="Old plan", url="https://sub.example.com/old", enabled=False,
    ))


# -- capture helpers ------------------------------------------------------
class Tour:
    def __init__(self, app: QApplication, out_dir: Path, lang: str, size_name: str) -> None:
        self.app = app
        self.dir = out_dir / lang / size_name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lang = lang
        self.size_name = size_name
        self._n = 0
        self.index_lines: list[str] = []
        self.findings: list[str] = []

    def shot(self, widget: QWidget, name: str, note: str = "") -> Path:
        self._n += 1
        fname = f"{self._n:02d}_{name}.png"
        path = self.dir / fname
        self.app.processEvents()
        widget.grab().save(str(path))
        self.index_lines.append(f"{self.lang}/{self.size_name}/{fname} — {note or name}")
        self.check_widget(widget, f"{self.lang}/{self.size_name}/{fname}")
        return path

    def finding(self, severity: str, where: str, text: str) -> None:
        self.findings.append(f"[{severity}] {where}: {text}")

    # -- automated UX checks --------------------------------------------
    def check_widget(self, top: QWidget, shot_name: str) -> None:
        self._check_clipping(top, shot_name)
        self._check_off_window(top, shot_name)
        self._check_overlap(top, shot_name)
        self._check_icon_only_buttons(top, shot_name)
        if self.lang == "fa":
            self._check_english_leak(top, shot_name)

    def _visible_labels_and_buttons(self, top: QWidget):
        for w in _find_children_of(top, QLabel, QPushButton, QCheckBox):
            if w.isVisible() and w.text().strip():
                yield w

    def _check_clipping(self, top: QWidget, shot_name: str) -> None:
        for w in self._visible_labels_and_buttons(top):
            if isinstance(w, QLabel) and w.wordWrap():
                continue  # wrapping labels are allowed to be narrower than sizeHint
            fm = QFontMetrics(w.font())
            text_w = fm.horizontalAdvance(w.text())
            avail = w.width()
            # Buttons/checkboxes need room for their own chrome (box, padding);
            # a small margin avoids flagging normal padding as clipping.
            margin = 24 if not isinstance(w, QLabel) else 4
            if avail > 0 and text_w > avail + margin:
                self.finding("clipping", shot_name,
                            f"{w.__class__.__name__} {w.objectName()!r} text={w.text()!r} "
                            f"needs ~{text_w}px, has {avail}px "
                            f"(source: {_widget_source(w)})")

    def _check_off_window(self, top: QWidget, shot_name: str) -> None:
        bounds = QRect(0, 0, top.width(), top.height())
        for w in top.findChildren(QWidget):
            if not w.isVisible() or w is top:
                continue
            if _inside_scroll_area(w, top):
                # Scrolled content legitimately extends past the viewport;
                # that's what the scrollbar is for, not a layout bug.
                continue
            r = QRect(w.mapTo(top, w.rect().topLeft()), w.size())
            if not bounds.contains(r):
                self.finding("off-window", shot_name,
                            f"{w.__class__.__name__} {w.objectName()!r} at {r} "
                            f"exceeds {bounds} (source: {_widget_source(w)})")

    def _check_overlap(self, top: QWidget, shot_name: str) -> None:
        # Only compare siblings (same direct parent): a child legitimately
        # sits "inside" its parent's rect, which isn't overlap.
        seen: dict[int, list[tuple[QWidget, QRect]]] = {}
        for w in top.findChildren(QWidget):
            if not w.isVisible() or w.width() <= 0 or w.height() <= 0:
                continue
            parent = w.parentWidget()
            if parent is None:
                continue
            r = QRect(w.pos(), w.size())
            seen.setdefault(id(parent), []).append((w, r))
        for siblings in seen.values():
            for i in range(len(siblings)):
                wi, ri = siblings[i]
                for j in range(i + 1, len(siblings)):
                    wj, rj = siblings[j]
                    inter = ri.intersected(rj)
                    if inter.width() > 2 and inter.height() > 2:
                        self.finding("overlap", shot_name,
                                    f"{wi.__class__.__name__} {wi.objectName()!r} overlaps "
                                    f"{wj.__class__.__name__} {wj.objectName()!r} by "
                                    f"{inter.width()}x{inter.height()}px")

    def _check_icon_only_buttons(self, top: QWidget, shot_name: str) -> None:
        for b in top.findChildren(QPushButton):
            if not b.isVisible():
                continue
            text = b.text().strip()
            if text and len(text) <= 2 and not text.isalnum():
                # A symbol-only button (✎ ↻ ✕ ↑ ↓ ⋯): needs a tooltip.
                if not b.toolTip().strip():
                    self.finding("no-tooltip", shot_name,
                                f"icon-only QPushButton {b.objectName()!r} text={text!r} "
                                f"has no tooltip (source: {_widget_source(b)})")

    def _check_english_leak(self, top: QWidget, shot_name: str) -> None:
        for w in self._visible_labels_and_buttons(top):
            text = w.text()
            if _looks_like_untranslated_english(text):
                self.finding("fa-leak", shot_name,
                            f"{w.__class__.__name__} {w.objectName()!r} shows {text!r} "
                            f"in fa (source: {_widget_source(w)})")

    def check_focus_order(self, dlg: QWidget, shot_name: str) -> None:
        expected = [w for w in _find_children_of(dlg, QLineEdit, QComboBox, QCheckBox,
                                                 QSpinBox, QPlainTextEdit)
                   if w.isVisible() and w.isEnabled() and w.focusPolicy() != Qt.NoFocus
                   # A QSpinBox's internal line edit is not a separate tab stop --
                   # Tab lands on the QSpinBox, which owns it as a focus proxy.
                   and w.objectName() != "qt_spinbox_lineedit"]
        if not expected:
            return
        reached: set[int] = set()
        first = expected[0]
        first.setFocus(Qt.OtherFocusReason)
        for _ in range(len(expected) * 3 + 5):
            self.app.processEvents()
            fw = self.app.focusWidget()
            if fw is not None:
                reached.add(id(fw))
            QTest.keyClick(dlg, Qt.Key_Tab)
        missing = [w for w in expected if id(w) not in reached]
        for w in missing:
            self.finding("tab-order", shot_name,
                        f"{w.__class__.__name__} {w.objectName()!r} never received focus "
                        f"by Tab (source: {_widget_source(w)})")

    def check_default_button_and_escape(self, dlg_factory, shot_name: str) -> None:
        dlg = dlg_factory()
        buttons = [b for b in dlg.findChildren(QPushButton) if b.isVisible()]
        default_btns = [b for b in buttons if b.isDefault()]
        if not default_btns:
            self.finding("no-default-button", shot_name,
                        "no QPushButton isDefault() -- Enter may do nothing")
        dlg.show()
        self.app.processEvents()
        QTest.keyClick(dlg, Qt.Key_Escape)
        self.app.processEvents()
        if dlg.isVisible():
            self.finding("esc-does-not-close", shot_name,
                        f"{dlg.__class__.__name__} is still visible after Esc")
        dlg.close()
        dlg.deleteLater()


def _show_menu_at(menu: QMenu, global_pos) -> None:
    # menu.popup()/.exec() try to grab the keyboard/mouse for interactive
    # navigation, which the offscreen platform can't satisfy and which then
    # wedges the event loop waiting for a grab release that never comes.
    # A plain move()+show() renders the same thing without that dance.
    menu.move(global_pos)
    menu.show()


def _find_children_of(top: QWidget, *types: type) -> list[QWidget]:
    # PySide6's findChildren() takes exactly one type, not a tuple.
    out: list[QWidget] = []
    for t in types:
        out.extend(top.findChildren(t))
    return out


def _widget_source(w: QWidget) -> str:
    return f"{w.__class__.__module__}.{w.__class__.__qualname__}"


def _inside_scroll_area(w: QWidget, top: QWidget) -> bool:
    p = w.parentWidget()
    while p is not None and p is not top:
        if isinstance(p, QScrollArea):
            return True
        p = p.parentWidget()
    return False


_EN_WORDS = {
    "the", "and", "with", "your", "server", "servers", "connect", "disconnect",
    "settings", "routing", "subscription", "delete", "cancel", "save", "import",
    "export", "test", "edit", "add", "enabled", "disabled", "port", "address",
}


def _looks_like_untranslated_english(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    # Technical/proper nouns and units are allowed in fa by design (see
    # CLAUDE.md / the i18n coverage tests' own allowlist) -- only flag text
    # that reads as ordinary English prose a translator would recognize.
    words = [w.strip(".,:;()…—-").lower() for w in lower.split()]
    hits = sum(1 for w in words if w in _EN_WORDS)
    return hits >= 2


# -- the tour itself --------------------------------------------------------
def run_tour(out_dir: Path) -> list[str]:
    from xrayui import i18n
    from xrayui.core.profiles import ProfileStore
    from xrayui.core.subscription import Subscription
    from xrayui.ui import theme
    from xrayui.ui.dialogs import (
        ImportDialog,
        ProfileEditDialog,
        SettingsDialog,
        SubscriptionEditDialog,
    )
    from xrayui.ui.dns_dialog import DnsDialog
    from xrayui.ui.routing_dialog import RoutingDialog
    from xrayui.ui.rule_editor import CollapsibleSection, RuleEditorDialog, default_rule
    from xrayui.ui.server_table import QrDialog

    app = QApplication.instance() or QApplication([])
    all_findings: list[str] = []
    index_lines: list[str] = []

    for lang in LANGS:
        for size_name, w, h in SIZES:
            base_dir = Path(tempfile.mkdtemp(prefix=f"ui_tour_{lang}_{size_name}_"))
            seed_data(base_dir, lang)
            i18n.set_language(lang)
            if lang == "fa":
                app.setLayoutDirection(Qt.RightToLeft)
                app.setStyleSheet(theme.build_stylesheet(f"{_FA_FONTS}, {theme._FONT}"))
            else:
                app.setLayoutDirection(Qt.LeftToRight)
                app.setStyleSheet(theme.STYLESHEET)

            from xrayui.ui.main_window import MainWindow
            win = MainWindow(elevated=True)
            win.resize(w, h)
            win.show()
            app.processEvents()

            tour = Tour(app, out_dir, lang, size_name)

            # -- main window states -----------------------------------------
            win.alert_banner.setVisible(False)
            tour.shot(win, "main_disconnected", "Main window, disconnected")

            win.conn._connected = True
            win._needs_reconnect("Routing changed")
            win._refresh_status()
            tour.shot(win, "main_connected_reconnect", "Fake-connected, Reconnect now visible")
            win.conn._connected = False
            win.btn_reconnect.setVisible(False)
            win._refresh_status()

            win._check_alerts()
            if not win.alert_banner.isVisible():
                win.alert_banner.show_alert("warning", "Low data: 22.0 GB left (22%)")
            tour.shot(win, "main_alert_banner", "Quota alert banner")

            win.alert_banner.show_alert(
                "warning", i18n.tr("sushTun {tag} is available", tag="v9.9.9"),
                action_label=i18n.tr("Copy download link"), action=lambda: None,
            )
            tour.shot(win, "main_update_banner", "Update-available banner")
            win.alert_banner.setVisible(False)

            # -- server table interactions ------------------------------------
            win.profiles.table.selectRow(0)
            win.profiles.table.selectRow(2)
            sel_model = win.profiles.table.selectionModel()
            idx0 = win.profiles.proxy.index(0, 0)
            idx2 = win.profiles.proxy.index(2, 0)
            sel = QItemSelection(idx0, idx0)
            sel.select(idx2, idx2)
            sel_model.select(sel, QItemSelectionModel.Select | QItemSelectionModel.Rows)
            app.processEvents()
            tour.shot(win.profiles, "server_table_multiselect", "Server table, two rows selected")

            ctx_menu = win.profiles._build_context_menu(win.profiles.selected_uids())
            if ctx_menu is not None:
                _show_menu_at(ctx_menu, win.profiles.table.viewport().mapToGlobal(
                    win.profiles.table.viewport().rect().center()))
                app.processEvents()
                tour.shot(ctx_menu, "server_table_context_menu",
                         "Right-click menu on selected servers")
                ctx_menu.hide()

            test_menu = win.profiles.btn_test.menu()
            if test_menu is not None:
                _show_menu_at(test_menu, win.profiles.btn_test.mapToGlobal(
                    win.profiles.btn_test.rect().bottomLeft()))
                app.processEvents()
                tour.shot(test_menu, "server_table_test_menu", "Test ▾ menu")
                test_menu.hide()

            more_menu = win.profiles.btn_more.menu()
            if more_menu is not None:
                _show_menu_at(more_menu, win.profiles.btn_more.mapToGlobal(
                    win.profiles.btn_more.rect().bottomLeft()))
                app.processEvents()
                tour.shot(more_menu, "server_table_more_menu", "⋯ menu")
                more_menu.hide()

            header_menu = win.profiles._build_header_menu()
            _show_menu_at(header_menu, win.profiles.table.mapToGlobal(
                win.profiles.table.rect().topLeft()))
            app.processEvents()
            tour.shot(header_menu, "server_table_header_menu", "Column visibility menu")
            header_menu.hide()

            sel_model.clearSelection()
            QTest.keyClicks(win.profiles.filter_edit, "Frankfurt")
            app.processEvents()
            tour.shot(win.profiles, "server_table_filter", "Filter text typed")
            win.profiles.filter_edit.clear()
            app.processEvents()

            # -- tray menus (offscreen has no real tray; rebuild the menu
            # objects directly, the same pattern tests/test_ui.py uses) ------
            win.servers_menu = QMenu()
            win.routing_menu = QMenu()
            win._rebuild_servers_tray_menu()
            win._rebuild_routing_tray_menu()
            top_tray_menu = QMenu()
            top_tray_menu.addAction(i18n.tr("Show"))
            top_tray_menu.addAction(i18n.tr("Connect"))
            top_tray_menu.addAction(i18n.tr("Disconnect"))
            top_tray_menu.addSeparator()
            servers_sub = top_tray_menu.addMenu(i18n.tr("Servers"))
            for a in win.servers_menu.actions():
                servers_sub.addAction(a)
            routing_sub = top_tray_menu.addMenu(i18n.tr("Routing"))
            for a in win.routing_menu.actions():
                routing_sub.addAction(a)
            top_tray_menu.addSeparator()
            top_tray_menu.addAction(i18n.tr("Quit"))
            _show_menu_at(top_tray_menu, win.mapToGlobal(win.rect().topLeft()))
            app.processEvents()
            tour.shot(top_tray_menu, "tray_menu", "Tray icon menu")
            _show_menu_at(servers_sub, win.mapToGlobal(win.rect().topLeft()))
            app.processEvents()
            tour.shot(servers_sub, "tray_servers_submenu", "Tray Servers submenu")
            _show_menu_at(routing_sub, win.mapToGlobal(win.rect().topLeft()))
            app.processEvents()
            tour.shot(routing_sub, "tray_routing_submenu", "Tray Routing submenu")
            top_tray_menu.hide()

            # -- dialogs ------------------------------------------------------
            def expand_advanced(dlg) -> None:
                for section in dlg.findChildren(CollapsibleSection):
                    section.set_expanded(True)
                app.processEvents()

            import_dlg = ImportDialog(win)
            import_dlg.resize(w - 100, h - 150)
            import_dlg.show()
            for i in range(import_dlg.tabs.count()):
                import_dlg.tabs.setCurrentIndex(i)
                app.processEvents()
                tour.shot(import_dlg, f"import_dialog_tab{i}",
                         f"Import dialog, tab {import_dlg.tabs.tabText(i)}")
            tour.check_focus_order(import_dlg, "import_dialog")
            import_dlg.close()

            store = ProfileStore()
            for profile in store.list():
                dlg = ProfileEditDialog(profile, win)
                dlg.resize(w - 100, h - 80)
                dlg.show()
                expand_advanced(dlg)
                tour.shot(dlg, f"profile_edit_{profile.protocol}",
                         f"Profile editor, {profile.protocol}, Advanced expanded")
                if profile.protocol == "vless":
                    tour.check_focus_order(dlg, "profile_edit_vless")
                dlg.close()

            settings_dlg = SettingsDialog(win.settings, win)
            settings_dlg.resize(min(w - 100, 460), h - 60)
            settings_dlg.show()
            expand_advanced(settings_dlg)
            scroll = settings_dlg.findChild(QScrollArea)
            if scroll is not None:
                sb = scroll.verticalScrollBar()
                sb.setValue(sb.minimum())
                app.processEvents()
                tour.shot(settings_dlg, "settings_top", "Settings, scrolled to top")
                sb.setValue((sb.minimum() + sb.maximum()) // 2)
                app.processEvents()
                tour.shot(settings_dlg, "settings_middle", "Settings, scrolled to middle")
                sb.setValue(sb.maximum())
                app.processEvents()
                tour.shot(settings_dlg, "settings_bottom", "Settings, scrolled to bottom")
            else:
                tour.shot(settings_dlg, "settings", "Settings dialog")
            tour.check_focus_order(settings_dlg, "settings_dialog")
            settings_dlg.close()

            routing_dlg = RoutingDialog(win.settings["routing"], win)
            routing_dlg.resize(w - 60, h - 60)
            routing_dlg.show()
            routing_dlg.tabs.setCurrentIndex(0)
            app.processEvents()
            tour.shot(routing_dlg, "routing_simple", "Routing dialog, Simple tab")
            routing_dlg.tabs.setCurrentIndex(1)
            if routing_dlg.sets_list.count():
                routing_dlg.sets_list.setCurrentRow(0)
            app.processEvents()
            tour.shot(routing_dlg, "routing_rule_sets", "Routing dialog, Rule sets tab")
            tour.check_focus_order(routing_dlg, "routing_dialog")
            routing_dlg.close()

            rule_dlg = RuleEditorDialog(default_rule(), win)
            rule_dlg.resize(min(w - 100, 480), h - 100)
            rule_dlg.show()
            app.processEvents()
            tour.shot(rule_dlg, "rule_editor", "Rule editor")
            tour.check_focus_order(rule_dlg, "rule_editor")
            rule_dlg.close()

            dns_dlg = DnsDialog(win.settings["dns"], win.settings["routing"], win)
            dns_dlg.resize(min(w - 60, 560), h - 40)
            dns_dlg.show()
            expand_advanced(dns_dlg)
            app.processEvents()
            tour.shot(dns_dlg, "dns_dialog", "DNS dialog, Advanced expanded")
            tour.check_focus_order(dns_dlg, "dns_dialog")
            dns_dlg.close()

            sub_dlg = SubscriptionEditDialog(Subscription(name="Main plan",
                                                          url="https://sub.example.com/main"), win)
            sub_dlg.resize(min(w - 100, 420), 0)
            sub_dlg.show()
            app.processEvents()
            tour.shot(sub_dlg, "subscription_edit", "Subscription editor")
            tour.check_focus_order(sub_dlg, "subscription_edit")
            sub_dlg.close()

            qr_dlg = QrDialog("Frankfurt Reality",
                              "vless://11111111-1111-1111-1111-111111111111@de.example.com:"
                              "443?type=tcp&security=reality&sni=www.microsoft.com&fp=chrome"
                              "&pbk=MjJyOOxAQ0m9MJp368E7lLKmXQz0GBBpuF12E-B6H1Q&sid=ab#Frankfurt")
            qr_dlg.show()
            app.processEvents()
            tour.shot(qr_dlg, "qr_dialog", "Share-link QR dialog")
            qr_dlg.close()

            # -- default button / Esc, on throwaway instances ------------------
            tour.check_default_button_and_escape(
                lambda win=win: SettingsDialog(win.settings, win), "settings_dialog")
            tour.check_default_button_and_escape(
                lambda win=win: DnsDialog(win.settings["dns"], win.settings["routing"], win),
                "dns_dialog")
            tour.check_default_button_and_escape(
                lambda win=win: RoutingDialog(win.settings["routing"], win), "routing_dialog")
            tour.check_default_button_and_escape(
                lambda win=win: RuleEditorDialog(default_rule(), win), "rule_editor")
            tour.check_default_button_and_escape(
                lambda win=win, store=store: ProfileEditDialog(store.list()[0], win),
                "profile_edit")
            tour.check_default_button_and_escape(
                lambda win=win: SubscriptionEditDialog(Subscription(), win),
                "subscription_edit")
            tour.check_default_button_and_escape(
                lambda win=win: ImportDialog(win), "import_dialog")

            win.tailer.stop()
            win.close()
            app.processEvents()
            shutil.rmtree(base_dir, ignore_errors=True)

            index_lines.extend(tour.index_lines)
            all_findings.extend(tour.findings)

    (out_dir / "index.txt").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return all_findings


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("ui_tour_out")
    out_dir.mkdir(parents=True, exist_ok=True)
    install_stubs()
    findings = run_tour(out_dir)
    order = {"clipping": 0, "overlap": 1, "off-window": 2, "no-tooltip": 3,
            "fa-leak": 4, "tab-order": 5, "no-default-button": 6, "esc-does-not-close": 7}
    findings.sort(key=lambda f: order.get(f.split("]")[0].lstrip("["), 99))
    (out_dir / "findings.txt").write_text(
        ("\n".join(findings) if findings else "(no findings)") + "\n", encoding="utf-8")
    print(f"{len(findings)} findings written to {out_dir / 'findings.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
