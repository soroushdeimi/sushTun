"""Sidebar for the macOS-style sidebar window (Direction A)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core.alerts import human_bytes
from ..i18n import ltr, tr
from .icons import icon
from .mac import SidebarItem, SidebarSection, Switch
from .theme import MUTED, SIDEBAR, SIDEBAR_EDGE


class PlaceholderSubscriptionList(QWidget):
    """Minimal subscription list shown under the Subscriptions section."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 8, 8)
        self._layout.setSpacing(5)

    def set_subscriptions(self, subs: list) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for sub in subs:
            name = sub.name or "Unnamed"
            remaining = sub.usage.remaining if sub.usage.total else 0
            row = QWidget(self)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(10)
            lbl = QLabel(name)
            lbl.setObjectName("GroupRowLabel" if sub.enabled else "Muted")
            rl.addWidget(lbl, 1)
            if sub.enabled and remaining > 0:
                left_lbl = QLabel(ltr("{amount} left", amount=human_bytes(remaining)))
                left_lbl.setObjectName("GroupRowFootnote")
                left_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                rl.addWidget(left_lbl)
            elif not sub.enabled:
                off_lbl = QLabel(tr("off"))
                off_lbl.setObjectName("GroupRowFootnote")
                off_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                rl.addWidget(off_lbl)
            self._layout.addWidget(row)
        self._layout.addStretch(1)


class Sidebar(QFrame):
    """Full-height sidebar with navigation items, subscription list, and bottom actions."""

    pageSelected = Signal(int)   # 0=Servers … 4=Activity
    settingsRequested = Signal()
    hotspotToggled = Signal(bool)

    def __init__(self, traffic_lights: QWidget | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(212)
        # A selector keeps the edge line on the sidebar itself; an unscoped
        # rule gave every child label and row its own vertical line. In RTL
        # the sidebar sits on the right, so its edge faces left.
        edge = "border-left" if self.layoutDirection() == Qt.RightToLeft else "border-right"
        # The theme paints every plain QWidget in the window colour; inside the
        # sidebar that drew grey boxes behind the rows, so they stay clear.
        self.setStyleSheet(
            f"QFrame#Sidebar{{background:{SIDEBAR}; {edge}:1px solid {SIDEBAR_EDGE};}}"
            "QFrame#Sidebar QWidget{background:transparent;}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 16, 10, 12)
        outer.setSpacing(0)

        # ── traffic lights (frameless Win/Linux only) ──────────────────
        if traffic_lights is not None:
            outer.addWidget(traffic_lights)
            outer.addSpacing(18)

        # ── nav items ──────────────────────────────────────────────────
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_items: list[SidebarItem] = []

        self.item_servers = self._add_nav(tr("Servers"), "servers")
        self.item_subs = self._add_nav(tr("Subscriptions"), "subscriptions")
        self.item_routing = self._add_nav(tr("Routing"), "routing")
        self.item_dns = self._add_nav(tr("DNS"), "dns")
        self.item_activity = self._add_nav(tr("Activity"), "activity")
        self.item_servers.setChecked(True)

        # ── subscriptions section ──────────────────────────────────────
        outer.addSpacing(4)
        self.section_subs = SidebarSection(tr("Subscriptions"))
        outer.addWidget(self.section_subs)

        self.sub_list_host: QWidget = PlaceholderSubscriptionList(self)
        outer.addWidget(self.sub_list_host, 1)

        # ── bottom: hotspot row + settings ─────────────────────────────
        outer.addSpacing(2)

        self._hotspot_row = QWidget(self)
        hr = QHBoxLayout(self._hotspot_row)
        hr.setContentsMargins(8, 6, 8, 6)
        hr.setSpacing(10)
        hotspot_icon = QLabel()
        hotspot_icon.setPixmap(icon("hotspot", MUTED).pixmap(16, 16))
        hr.addWidget(hotspot_icon)
        hotspot_label = QLabel(tr("Hotspot"))
        hotspot_label.setObjectName("GroupRowLabel")
        hr.addWidget(hotspot_label, 1)
        self.btn_gateway = Switch()
        self.btn_gateway.setAccessibleName(tr("Share via hotspot"))
        self.btn_gateway.toggled.connect(self.hotspotToggled)
        hr.addWidget(self.btn_gateway)
        outer.addWidget(self._hotspot_row)

        self.hotspot_detail = QLabel("")
        self.hotspot_detail.setObjectName("GroupRowFootnote")
        self.hotspot_detail.setWordWrap(True)
        self.hotspot_detail.setVisible(False)
        outer.addWidget(self.hotspot_detail)

        outer.addSpacing(6)

        self._settings_row = QWidget(self)
        sr = QHBoxLayout(self._settings_row)
        sr.setContentsMargins(8, 6, 8, 6)
        sr.setSpacing(10)
        settings_icon = QLabel()
        settings_icon.setPixmap(icon("settings", MUTED).pixmap(16, 16))
        sr.addWidget(settings_icon)
        settings_label = QLabel(tr("Settings"))
        settings_label.setObjectName("GroupRowLabel")
        sr.addWidget(settings_label, 1)
        self._settings_row.mousePressEvent = lambda _: self.settingsRequested.emit()
        self._settings_row.setCursor(QCursor(Qt.PointingHandCursor))
        outer.addWidget(self._settings_row)

    # ── helpers ───────────────────────────────────────────────────────────

    def _add_nav(self, text: str, icon_name: str) -> SidebarItem:
        item = SidebarItem(text, icon_name, self)
        idx = len(self._nav_items)
        self._nav_group.addButton(item, idx)
        item.clicked.connect(lambda _c, i=idx: self.pageSelected.emit(i))
        self._nav_items.append(item)
        self.layout().addWidget(item)
        return item

    # ── public API ────────────────────────────────────────────────────────

    def set_subscription_count(self, count: int) -> None:
        self.item_subs.set_count(str(count) if count else None)

    def set_subscription_list(self, widget: QWidget) -> None:
        """Replace the placeholder (or any previous) list under Subscriptions."""
        old = self.sub_list_host
        lay = self.layout()
        idx = lay.indexOf(old)
        if idx >= 0:
            lay.removeWidget(old)
            old.hide()
            old.deleteLater()
            # Stretch 1, like the placeholder: the list takes the free space so
            # Hotspot and Settings stay pinned to the bottom.
            lay.insertWidget(idx, widget, 1)
        self.sub_list_host = widget

    def set_hotspot_state(self, on: bool, ssid: str = "",
                          password: str = "") -> None:
        self.btn_gateway.blockSignals(True)
        self.btn_gateway.setChecked(on)
        self.btn_gateway.blockSignals(False)
        if on and ssid:
            self.hotspot_detail.setText(
                tr("SSID: {ssid} · Password: {pwd}",
                   ssid=ssid, pwd=password))
            self.hotspot_detail.setVisible(True)
        else:
            self.hotspot_detail.setVisible(False)

    def set_hotspot_supported(self, supported: bool,
                              reason: str = "") -> None:
        self.btn_gateway.setEnabled(supported)
        if not supported and reason:
            self.btn_gateway.setToolTip(reason)

    def set_current_page(self, index: int) -> None:
        if 0 <= index < len(self._nav_items):
            self._nav_items[index].setChecked(True)
