"""Subscriptions list with per-sub quota/expiry usage bars."""
from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.alerts import human_bytes
from ..core.subscription import Subscription
from ..i18n import ltr, tr
from .theme import ERR, OK, WARN


def _bar_color(percent_left: float | None) -> str:
    if percent_left is None:
        return OK
    if percent_left <= 0.05:
        return ERR
    if percent_left <= 0.20:
        return WARN
    return OK


def _ago(ts: float) -> str:
    if not ts:
        return tr("never")
    mins = (time.time() - ts) / 60
    if mins < 60:
        return tr("{n}m ago", n=f"{mins:.0f}")
    if mins < 1440:
        return tr("{n}h ago", n=f"{mins / 60:.0f}")
    return tr("{n}d ago", n=f"{mins / 1440:.0f}")


class SubscriptionRow(QFrame):
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
        name = QLabel(sub.name)
        # A disabled sub is still fully clickable (edit/enable it again) --
        # only the name reads muted, rather than disabling the whole row.
        name.setObjectName("Muted" if not sub.enabled else "H1")
        edit = QPushButton("✎")
        refresh = QPushButton("↻")
        delete = QPushButton("✕")
        for b in (edit, refresh, delete):
            b.setFixedWidth(34)
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
        meta = QLabel("  •  ".join(parts))
        meta.setObjectName("Muted")
        layout.addWidget(meta)

    def mouseDoubleClickEvent(self, event) -> None:
        self.editRequested.emit(self.uid)
        super().mouseDoubleClickEvent(event)


class SubscriptionPanel(QWidget):
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
            row = SubscriptionRow(sub)
            row.refreshRequested.connect(self.refreshRequested)
            row.deleteRequested.connect(self.deleteRequested)
            row.editRequested.connect(self.editRequested)
            self._rows.addWidget(row)
