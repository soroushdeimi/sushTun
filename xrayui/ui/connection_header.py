"""The macOS-style connection header card, rebuilt as a standalone widget
(not yet placed in MainWindow). It keeps the old status card's public API --
set(key, value) and set_connected(bool) -- but owns its own buttons and
emits intent signals instead of reaching into MainWindow's widget graph.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from ..i18n import ltr, tr
from .icons import icon
from .mac import IconButton
from .theme import ERR, MUTED, OK


class ConnectionHeader(QFrame):
    connectRequested = Signal()
    disconnectRequested = Signal()
    restoreNetworkRequested = Signal()
    reconnectRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(16)

        self._tile = QLabel()
        self._tile.setObjectName("StatusTile")
        self._tile.setFixedSize(44, 44)
        self._tile.setAlignment(Qt.AlignCenter)
        top.addWidget(self._tile)

        mid = QVBoxLayout()
        mid.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self._state = QLabel()
        self._state.setObjectName("H1")
        self._timer_pill = QLabel("")
        self._timer_pill.setObjectName("PillOn")
        self._timer_pill.setVisible(False)
        title_row.addWidget(self._state)
        title_row.addWidget(self._timer_pill)
        title_row.addStretch(1)
        mid.addLayout(title_row)
        self._meta = QLabel("—")
        self._meta.setObjectName("Muted")
        mid.addWidget(self._meta)
        top.addLayout(mid, 1)

        figures = QHBoxLayout()
        figures.setSpacing(22)
        self._down_up = self._figure(figures, tr("Down / Up"))
        self._session = self._figure(figures, tr("This session"))
        top.addLayout(figures)

        self.btn_connect = QPushButton(tr("Connect"))
        self.btn_connect.setObjectName("Primary")
        self.btn_connect.clicked.connect(self.connectRequested)
        self.btn_disconnect = QPushButton(tr("Disconnect"))
        self.btn_disconnect.setObjectName("Danger")
        self.btn_disconnect.clicked.connect(self.disconnectRequested)
        top.addWidget(self.btn_connect)
        top.addWidget(self.btn_disconnect)
        self.btn_more = self._more_button()
        top.addWidget(self.btn_more)
        outer.addLayout(top)

        # Inline "Reconnect now" notice, hidden until show_reconnect().
        self._notice_label = QLabel("")
        self._notice_label.setObjectName("Muted")
        self.btn_reconnect = QPushButton(tr("Reconnect now"))
        self.btn_reconnect.setObjectName("Primary")
        self.btn_reconnect.clicked.connect(self.reconnectRequested)
        notice = QHBoxLayout()
        notice.addWidget(self._notice_label, 1)
        notice.addWidget(self.btn_reconnect)
        outer.addLayout(notice)
        self.hide_reconnect()

        self._meta_parts: dict[str, str] = {}
        self.set_connected(False)

    @staticmethod
    def _figure(layout: QHBoxLayout, label_text: str) -> QLabel:
        col = QVBoxLayout()
        col.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setObjectName("Muted")
        lbl.setAlignment(Qt.AlignRight)
        val = QLabel("—")
        val.setAlignment(Qt.AlignRight)
        col.addWidget(lbl)
        col.addWidget(val)
        layout.addLayout(col)
        return val

    def _more_button(self) -> QToolButton:
        more = IconButton("ellipsis", tr("More connection actions"))
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        # A signal, not a callback, so MainWindow wires it once.
        menu.addAction(tr("Restore network"), self.restoreNetworkRequested.emit)
        more.setMenu(menu)
        return more

    # -- StatusCard-compatible API -------------------------------------
    def set(self, key: str, value: str) -> None:
        text = (value or "").strip()
        if key == "throughput":
            self._down_up.setText(ltr(text) if text else "—")
        elif key == "used":
            self._session.setText(ltr(text) if text else "—")
        elif key == "endpoint":
            self._set_meta("relay", text)
        elif key == "protocol":
            self._set_meta("protocol", text)
        elif key == "delay":
            self._set_meta("delay", text)
        elif key in ("iface", "tun"):
            self._set_meta("iface", text)
        # ip/process/gateway and other StatusCard keys have no home here;
        # ignored rather than stored so a future caller can't build a
        # cluttered meta line by accident.

    def _set_meta(self, slot: str, text: str) -> None:
        if text:
            self._meta_parts[slot] = text
        else:
            self._meta_parts.pop(slot, None)
        parts = [ltr(p) for p in self._meta_parts.values()]
        self._meta.setText(" · ".join(parts) if parts else "—")

    def set_timer(self, text: str) -> None:
        self._timer_pill.setText(text)
        self._timer_pill.setVisible(bool(text))

    def set_connected(self, connected: bool) -> None:
        self._state.setText(tr("Connected") if connected else tr("Disconnected"))
        color = OK if connected else MUTED
        bg = "rgba(48,209,88,.14)" if connected else "rgba(152,152,157,.12)"
        self._tile.setStyleSheet(
            f"background:{bg}; border-radius:12px; color:{color};"
        )
        self._tile.setPixmap(icon("shield-check", color, 22).pixmap(22, 22))
        # Connecting while connected (or disconnecting while idle) is never
        # useful, so each button only offers the action that applies now.
        self.btn_connect.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        if not connected:
            self.set_timer("")

    def show_reconnect(self, text: str) -> None:
        self._notice_label.setText(ltr(text) if text else "")
        self._notice_label.setVisible(True)
        self.btn_reconnect.setVisible(True)

    def hide_reconnect(self) -> None:
        self._notice_label.clear()
        self._notice_label.setVisible(False)
        self.btn_reconnect.setVisible(False)


def status_tile_error(header: ConnectionHeader) -> None:
    """Paints the tile as an error state (e.g. a failed reconnect)."""
    header._tile.setStyleSheet(
        f"background:rgba(255,69,58,.14); border-radius:12px; color:{ERR};"
    )
    header._tile.setPixmap(icon("shield-check", ERR, 22).pixmap(22, 22))
