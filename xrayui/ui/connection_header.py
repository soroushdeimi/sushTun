"""The macOS-style connection header card, rebuilt as a standalone widget
(not yet placed in MainWindow). It keeps the old status card's public API --
set(key, value) and set_connected(bool) -- but owns its own buttons and
emits intent signals instead of reaching into MainWindow's widget graph.

Layout (LTR shown; RTL mirrors the whole thing):
  Row 1: [tile 44px] [title + timer pill]    ─── [action button] [⋯]
  Row 2: [meta line · elide middle]           [Down / Up] [This session]
                                               (stats move to row 3 below
                                                when the header is < 640 px)
  Row 3 (invisible until narrow):             [Down / Up] [This session]

  Row 4: [reconnect notice + Reconnect now]
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import ltr, tr
from .icons import icon
from .mac import IconButton
from .theme import MUTED, OK

_NARROW_THRESHOLD = 640


class ConnectionHeader(QFrame):
    connectRequested = Signal()
    disconnectRequested = Signal()
    restoreNetworkRequested = Signal()
    reconnectRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._narrow: bool | None = None  # unknown at init
        self._meta_full: str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        # ── Row 1: tile · title+pill · ─── [action] [⋯] ──
        row1 = QHBoxLayout()
        row1.setSpacing(16)

        self._tile = QLabel()
        self._tile.setObjectName("StatusTile")
        self._tile.setFixedSize(44, 44)
        self._tile.setAlignment(Qt.AlignCenter)
        row1.addWidget(self._tile)

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
        row1.addLayout(mid, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_connect = QPushButton(tr("Connect"))
        self.btn_connect.setObjectName("Primary")
        self.btn_connect.clicked.connect(self.connectRequested)
        self.btn_disconnect = QPushButton(tr("Disconnect"))
        self.btn_disconnect.setObjectName("HeaderAction")
        self.btn_disconnect.clicked.connect(self.disconnectRequested)
        actions.addWidget(self.btn_connect)
        actions.addWidget(self.btn_disconnect)
        self.btn_more = self._build_more_button()
        # Square and as tall as Connect, so the pair lines up in every font.
        side = max(self.btn_connect.sizeHint().height(), self.btn_more.sizeHint().height())
        self.btn_more.setFixedSize(side, side)
        actions.addWidget(self.btn_more)
        row1.addLayout(actions)
        outer.addLayout(row1)

        # ── Row 2: meta line · ─── stats ──
        self._row2 = QHBoxLayout()
        self._row2.setSpacing(16)

        # Empty until something is known; a lone "—" read as a stray mark.
        self._meta = QLabel("")
        self._meta.setObjectName("Muted")
        # Ignored lets the meta shrink below its full text so it never forces
        # the header wide; _elide_meta keeps it readable and truthful instead.
        self._meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._row2.addWidget(self._meta, 1)

        self._stats_box = QWidget(self)
        self._stats_box.setObjectName("HeaderStats")
        stats_layout = QHBoxLayout(self._stats_box)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(22)
        self._down_up_col = self._build_stat_fig(stats_layout, tr("Down / Up"))
        self._session_col = self._build_stat_fig(stats_layout, tr("This session"))
        self._row2.addWidget(self._stats_box)
        outer.addLayout(self._row2)

        # Row 3 (narrow): a permanently-present empty slot between the meta
        # row and the notice row. Wide it holds nothing (0 height); narrow
        # the stats box is moved here, under the meta line.
        self._row3 = QHBoxLayout()
        outer.addLayout(self._row3)

        # ── Row 4: reconnect notice ──
        self._notice_label = QLabel("")
        self._notice_label.setObjectName("Muted")
        self._notice_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._notice_full = ""
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

    # ── helpers ──────────────────────────────────────────────────────────

    def _build_stat_fig(
        self, layout: QHBoxLayout, label_text: str,
    ) -> tuple[QLabel, QLabel]:
        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label_text)
        lbl.setObjectName("Muted")
        lbl.setAlignment(Qt.AlignRight)
        val = QLabel("—")
        val.setAlignment(Qt.AlignRight)
        col.addWidget(lbl)
        col.addWidget(val)
        layout.addLayout(col)
        return lbl, val

    def _build_more_button(self) -> QToolButton:
        more = IconButton("ellipsis", tr("More connection actions"))
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction(tr("Restore network"), self.restoreNetworkRequested.emit)
        more.setMenu(menu)
        return more

    # ── resizeEvent: narrow/wide swap + meta elide ───────────────────────

    def showEvent(self, event) -> None:  # noqa: N802 – Qt convention
        super().showEvent(event)
        self._elide_meta()
        self._elide_notice()

    def resizeEvent(self, event) -> None:  # noqa: N802 – Qt convention
        super().resizeEvent(event)
        narrow = self.width() < _NARROW_THRESHOLD
        if narrow != self._narrow:
            self._narrow = narrow
            self._place_stats(narrow)
        self._elide_meta()
        self._elide_notice()

    def _place_stats(self, narrow: bool) -> None:
        if narrow:
            self._row2.removeWidget(self._stats_box)
            self._row3.addWidget(self._stats_box, 0, Qt.AlignRight)
        else:
            self._row3.removeWidget(self._stats_box)
            self._row2.addWidget(self._stats_box)
        self._stats_box.show()

    def _elide_meta(self) -> None:
        _elide_to_fit(self._meta, self._meta_full, Qt.ElideMiddle)

    def _elide_notice(self) -> None:
        _elide_to_fit(self._notice_label, self._notice_full, Qt.ElideRight)

    # ── public API (StatusCard-compatible) ───────────────────────────────

    def set(self, key: str, value: str) -> None:
        text = (value or "").strip()
        # Callers pass "—" for "unknown"; joined with " · " that read as
        # "— · —", so an unknown part is simply left out of the meta line.
        if text == "—":
            text = ""
        if key == "throughput":
            self._down_up_col[1].setText(ltr(text) if text else "—")
        elif key == "used":
            self._session_col[1].setText(ltr(text) if text else "—")
        elif key == "endpoint":
            self._set_meta("relay", text)
        elif key == "protocol":
            self._set_meta("protocol", text)
        elif key == "delay":
            self._set_meta("delay", text)
        elif key == "iface":
            # Only the interface name: the TUN index ("12") used to overwrite
            # it in the same slot and meant nothing to the user.
            self._set_meta("iface", text)

    def _set_meta(self, slot: str, text: str) -> None:
        if text:
            self._meta_parts[slot] = ltr(text)
        else:
            self._meta_parts.pop(slot, None)
        self._meta_full = (
            " · ".join(self._meta_parts.values()) if self._meta_parts else ""
        )
        self._elide_meta()

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
        # Exactly one of Connect/Disconnect is visible, so the card never
        # offers an action that cannot apply to the current state.
        self.btn_connect.setVisible(not connected)
        self.btn_disconnect.setVisible(connected)
        if not connected:
            self.set_timer("")

    def show_reconnect(self, text: str) -> None:
        self._notice_full = ltr(text) if text else ""
        _elide_to_fit(self._notice_label, self._notice_full, Qt.ElideRight)
        self._notice_label.setVisible(True)
        self.btn_reconnect.setVisible(True)

    def hide_reconnect(self) -> None:
        self._notice_full = ""
        self._notice_label.clear()
        self._notice_label.setToolTip("")
        self._notice_label.setVisible(False)
        self.btn_reconnect.setVisible(False)


def _elide_to_fit(label: QLabel, full: str, mode: Qt.TextElideMode) -> None:
    fm = label.fontMetrics()
    w = label.width()
    if w <= 0:
        label.setText(full)
        label.setToolTip("")
        return
    elided = fm.elidedText(full, mode, w)
    label.setText(elided)
    label.setToolTip(full if elided != full else "")


def status_tile_error(header: ConnectionHeader) -> None:
    """Paints the tile as an error state (e.g. a failed reconnect)."""
    from .theme import ERR

    header._tile.setStyleSheet(
        f"background:rgba(255,69,58,.14); border-radius:12px; color:{ERR};"
    )
    header._tile.setPixmap(icon("shield-check", ERR, 22).pixmap(22, 22))
