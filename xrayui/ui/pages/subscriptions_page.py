"""Subscriptions page (full-width list with icon buttons) and the compact
sidebar subscription list used by the traffic overview."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.alerts import human_bytes
from ...core.subscription import Subscription
from ...i18n import ltr, tr
from ..mac import IconButton
from ..subscription_panel import _ago, _bar_color


class _PageSubscriptionRow(QFrame):
    """Like SubscriptionRow but with real IconButtons -- the panel's bare
    text glyphs carry no tooltips, so they fail the icon-button a11y rule."""

    refreshRequested = Signal(str)
    deleteRequested = Signal(str)
    editRequested = Signal(str)

    def __init__(self, sub: Subscription) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.uid = sub.uid
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        name = QLabel(sub.name)
        # A disabled sub is still fully clickable (edit/enable it again) --
        # only the name reads muted, rather than disabling the whole row.
        name.setObjectName("Muted" if not sub.enabled else "H1")
        edit = IconButton("pencil", tr("Edit subscription"))
        refresh = IconButton("refresh", tr("Update now"))
        delete = IconButton("close", tr("Delete subscription"))
        edit.clicked.connect(lambda: self.editRequested.emit(self.uid))
        refresh.clicked.connect(lambda: self.refreshRequested.emit(self.uid))
        delete.clicked.connect(lambda: self.deleteRequested.emit(self.uid))
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(edit)
        top.addWidget(refresh)
        top.addWidget(delete)
        layout.addLayout(top)

        u = sub.usage
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        if u.total:
            bar.setValue(min(int(u.used / u.total * 100), 100))
        else:
            bar.setValue(0)
        color = _bar_color(u.percent_left)
        bar.setStyleSheet(
            f"QProgressBar{{background:#0c0f14;border:none;border-radius:4px;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:4px;}}"
        )
        layout.addWidget(bar)

        parts = []
        if not sub.enabled:
            parts.append(tr("disabled"))
        if u.total:
            # Numbers tied to Latin units must stay in order inside the RTL
            # (fa) line, not get scrambled into "GB 18.6 / 46.6".
            parts.append(ltr(f"{human_bytes(u.used)} / {human_bytes(u.total)}"))
            parts.append(ltr(tr("{amount} left", amount=human_bytes(u.remaining))))
        else:
            parts.append(tr("usage unknown"))
        if u.days_left is not None:
            parts.append(ltr(tr("expires in {n}d", n=f"{max(u.days_left, 0):.0f}")))
        parts.append(ltr(tr("updated {ago}", ago=_ago(sub.updated))))
        meta = QLabel(ltr("  •  ".join(parts)))
        meta.setObjectName("Muted")
        layout.addWidget(meta)

    def mouseDoubleClickEvent(self, event) -> None:
        self.editRequested.emit(self.uid)
        super().mouseDoubleClickEvent(event)


class SubscriptionsPage(QWidget):
    addRequested = Signal()
    refreshRequested = Signal(str)
    deleteRequested = Signal(str)
    editRequested = Signal(str)
    updateAllRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        head = QHBoxLayout()
        title = QLabel(tr("Subscriptions"))
        title.setObjectName("H1")
        update_all = QPushButton(tr("Update all"))
        update_all.clicked.connect(self.updateAllRequested)
        add = QPushButton(tr("Add"))
        add.setObjectName("Primary")
        add.clicked.connect(self.addRequested)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(update_all)
        head.addWidget(add)
        outer.addLayout(head)

        self._rows = QVBoxLayout()
        self._rows.setSpacing(8)
        outer.addLayout(self._rows)
        self._empty = QLabel(tr("No subscriptions yet."))
        self._empty.setObjectName("Muted")
        outer.addWidget(self._empty)
        outer.addStretch(1)

    def set_subscriptions(self, subs: list[Subscription]) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._empty.setVisible(not subs)
        for sub in subs:
            row = _PageSubscriptionRow(sub)
            row.refreshRequested.connect(self.refreshRequested)
            row.deleteRequested.connect(self.deleteRequested)
            row.editRequested.connect(self.editRequested)
            self._rows.addWidget(row)


class _SidebarSubRow(QWidget):
    """One enabled subscription in the sidebar: name, remaining bytes and a
    5px usage bar. Clicking the row activates that subscription."""

    activated = Signal(str)

    def __init__(self, sub: Subscription) -> None:
        super().__init__()
        self.uid = sub.uid
        self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 2, 4, 2)
        v.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(sub.name)
        amount = QLabel(ltr(tr("{amount} left", amount=human_bytes(sub.usage.remaining))))
        amount.setObjectName("Muted")
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(amount)
        v.addLayout(top)

        bar = QFrame()
        bar.setFixedHeight(5)
        color = _bar_color(sub.usage.percent_left)
        bar.setStyleSheet(
            f"QFrame{{background:{color};border:none;border-radius:2px;}}"
        )
        v.addWidget(bar)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.uid)
        super().mouseReleaseEvent(event)


class SidebarSubscriptionList(QWidget):
    """Enabled subscriptions only -- a disabled sub must not keep its daily
    traffic visible in the sidebar's per-subscription usage."""

    activated = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        self._empty = QLabel(tr("No subscriptions yet."))
        self._empty.setObjectName("Muted")
        self._rows.addWidget(self._empty)
        self._rows.addStretch(1)

    def set_subscriptions(self, subs: list[Subscription]) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            # The empty-state label shares this layout; deleting it made the
            # next refresh touch a dead QLabel and crash.
            if widget is not None and widget is not self._empty:
                widget.deleteLater()
        enabled = [s for s in subs if s.enabled]
        self._rows.addWidget(self._empty)
        self._empty.setVisible(not enabled)
        for sub in enabled:
            row = _SidebarSubRow(sub)
            row.activated.connect(self.activated)
            self._rows.addWidget(row)
        self._rows.addStretch(1)
