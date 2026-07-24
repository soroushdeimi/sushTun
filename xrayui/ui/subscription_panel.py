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
        return "never"
    mins = (time.time() - ts) / 60
    if mins < 60:
        return f"{mins:.0f}m ago"
    if mins < 1440:
        return f"{mins / 60:.0f}h ago"
    return f"{mins / 1440:.0f}d ago"


class SubscriptionRow(QFrame):
    refreshRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, sub: Subscription) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.uid = sub.uid
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        name = QLabel(sub.name)
        name.setObjectName("H1")
        refresh = QPushButton("↻")
        delete = QPushButton("✕")
        for b in (refresh, delete):
            b.setFixedWidth(34)
        refresh.clicked.connect(lambda: self.refreshRequested.emit(self.uid))
        delete.clicked.connect(lambda: self.deleteRequested.emit(self.uid))
        top.addWidget(name)
        top.addStretch(1)
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
        if u.total:
            parts.append(f"{human_bytes(u.used)} / {human_bytes(u.total)}")
            parts.append(f"{human_bytes(u.remaining)} left")
        else:
            parts.append("usage unknown")
        if u.days_left is not None:
            parts.append(f"expires in {max(u.days_left, 0):.0f}d")
        parts.append(f"updated {_ago(sub.updated)}")
        meta = QLabel("  •  ".join(parts))
        meta.setObjectName("Muted")
        layout.addWidget(meta)


class SubscriptionPanel(QWidget):
    addRequested = Signal()
    refreshRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        head = QHBoxLayout()
        title = QLabel("Subscriptions")
        title.setObjectName("H1")
        add = QPushButton("Add")
        add.clicked.connect(self.addRequested)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(add)
        outer.addLayout(head)

        self._rows = QVBoxLayout()
        self._rows.setSpacing(8)
        outer.addLayout(self._rows)
        self._empty = QLabel("No subscriptions yet.")
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
            self._rows.addWidget(row)
