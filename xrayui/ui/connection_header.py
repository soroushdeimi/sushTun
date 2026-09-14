"""The Servers page's status card: a macOS-style connection header with the
status tile, session timer, throughput/usage figures and the Connect /
Disconnect controls. Keeps StatusCard's old set()/set_connected() API so
MainWindow's wiring barely changes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from ..i18n import tr
from .icons import icon
from .theme import ERR, MUTED, OK


class ConnectionHeader(QFrame):
    def __init__(
        self,
        btn_connect: QPushButton,
        btn_disconnect: QPushButton,
        btn_cleanup: QPushButton,
        btn_reconnect: QPushButton,
        step_label: QLabel,
    ) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._connected = False
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
        self._state_label = QLabel(tr("Disconnected"))
        self._state_label.setObjectName("H1")
        self._timer_pill = QLabel("")
        self._timer_pill.setObjectName("PillOn")
        self._timer_pill.setVisible(False)
        title_row.addWidget(self._state_label)
        title_row.addWidget(self._timer_pill)
        title_row.addStretch(1)
        mid.addLayout(title_row)
        self._subtitle = QLabel("—")
        self._subtitle.setObjectName("Muted")
        mid.addWidget(self._subtitle)
        top.addLayout(mid, 1)

        figures = QHBoxLayout()
        figures.setSpacing(22)
        self._throughput_col = self._figure(tr("Down / Up"))
        self._used_col = self._figure(tr("This session"))
        figures.addLayout(self._throughput_col[0])
        figures.addLayout(self._used_col[0])
        top.addLayout(figures)

        btn_connect.setObjectName("Primary")
        btn_disconnect.setObjectName("Danger")
        self.btn_more = QToolButton()
        self.btn_more.setText("⋯")
        self.btn_more.setToolTip(tr("More connection actions"))
        self.btn_more.setAccessibleName(tr("More connection actions"))
        self.btn_more.setPopupMode(QToolButton.InstantPopup)
        more_menu = QMenu(self.btn_more)
        more_menu.addAction(tr("Restore network"), btn_cleanup.click)
        self.btn_more.setMenu(more_menu)
        top.addWidget(btn_connect)
        top.addWidget(btn_disconnect)
        top.addWidget(self.btn_more)
        outer.addLayout(top)

        notice = QHBoxLayout()
        step_label.setObjectName("Muted")
        notice.addWidget(step_label, 1)
        notice.addWidget(btn_reconnect)
        outer.addLayout(notice)

        self._vals: dict[str, str] = {}

    @staticmethod
    def _figure(label_text: str) -> tuple[QVBoxLayout, QLabel]:
        col = QVBoxLayout()
        col.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setObjectName("Muted")
        lbl.setAlignment(Qt.AlignRight)
        val = QLabel("—")
        val.setAlignment(Qt.AlignRight)
        col.addWidget(lbl)
        col.addWidget(val)
        return col, val

    # -- StatusCard-compatible API -------------------------------------
    def set(self, key: str, value: str) -> None:
        self._vals[key] = value or "—"
        if key == "throughput":
            self._throughput_col[1].setText(self._vals[key])
        elif key == "used":
            self._used_col[1].setText(self._vals[key])
        elif key == "endpoint":
            pass  # superseded by set_subtitle(); kept for API compatibility

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text or "—")

    def set_timer(self, text: str) -> None:
        self._timer_pill.setText(text)
        self._timer_pill.setVisible(bool(text))

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._state_label.setText(tr("Connected") if connected else tr("Disconnected"))
        color = OK if connected else MUTED
        bg = "rgba(48,209,88,.14)" if connected else "rgba(152,152,157,.12)"
        self._tile.setStyleSheet(
            f"background:{bg}; border-radius:12px; color:{color};"
        )
        self._tile.setPixmap(icon("connected", color, 22).pixmap(22, 22))
        if not connected:
            self.set_timer("")


def status_tile_error(header: ConnectionHeader) -> None:
    """Paints the tile as an error state (e.g. a failed reconnect)."""
    header._tile.setStyleSheet(f"background:rgba(255,69,58,.14); border-radius:12px; color:{ERR};")
