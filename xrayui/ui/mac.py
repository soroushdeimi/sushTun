"""Reusable macOS-style widgets for the sidebar window (direction A) and the
Settings sheet. All colours/radii come from theme.py; the few fixed shades
below are lifted from the mockup's `.mac` block (theme has no token for them
yet and the task forbids inventing tokens that duplicate the mockup).
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import ltr
from .icons import icon
from .theme import ACCENT, MUTED, TEXT

# Mockup `.mac` fixed shades with no theme token yet.
_ITEM_TEXT = "#dcdce0"        # .sb-item idle text/icon
_SIDEBAR_HEAD = "#7c7c82"     # .sb-head
_SWITCH_OFF = "#4a4a4e"       # .switch track when off
_POPUP_BG = "#3a3a3d"         # .popup / .tbtn.box background
_POPUP_LINE = "#48484c"       # .popup / .tbtn.box border
_SELECTED_BG = QColor(255, 255, 255, 26)   # rgba(255,255,255,0.10) checked row
_HOVER_BG = QColor(255, 255, 255, 15)      # rgba(255,255,255,0.06) hover row


class Switch(QAbstractButton):
    """A 32x19 macOS toggle. The knob slides from the leading edge (off) to
    the trailing edge (on), so in an RTL window it moves to the other side
    just like a real Mac switch."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        # The track has a fixed shape; layout must not stretch it.
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(32, 19)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track = QColor(ACCENT) if self.isChecked() else QColor(_SWITCH_OFF)
        if not self.isEnabled():
            track = QColor("#2255a3") if self.isChecked() else QColor("#3a3a3d")
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        knob = 15
        margin = 2
        rtl = self.layoutDirection() == Qt.RightToLeft
        # The knob sits at the leading edge off, the trailing edge on; RTL
        # mirrors that so a checked switch reads flipped, like the mockup's
        # Persian note about the switch moving to the other side.
        if self.isChecked():
            x = margin if rtl else w - margin - knob
        else:
            x = w - margin - knob if rtl else margin
        p.setBrush(QColor("#ffffff") if self.isEnabled() else QColor("#7a7a7f"))
        p.drawEllipse(x, (h - knob) / 2, knob, knob)


class InsetGroup(QFrame):
    """A macOS inset list: surface background, 1px line border, radius 10,
    rows separated by hairline lines. add_row() appends a row whose label
    sits on the leading side and whose widget on the trailing side."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("InsetGroup")
        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(0)

    def add_row(
        self,
        label: str,
        widget: QWidget | None = None,
        footnote: str | None = None,
    ) -> QWidget:
        """Append a row (>=38px) to the group. *footnote* renders as a
        muted 11.5px line under the label. Returns the row widget so callers
        can reach the trailing widget's state."""
        if self._rows.count():
            sep = QFrame(self)
            sep.setObjectName("InsetGroupSeparator")
            sep.setFixedHeight(1)
            self._rows.addWidget(sep)

        row = QWidget(self)
        row.setObjectName("InsetGroupRow")
        row.setMinimumHeight(38)
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        lbl = QLabel(label, row)
        lbl.setObjectName("GroupRowLabel")
        text_col.addWidget(lbl)
        if footnote:
            note = QLabel(footnote, row)
            note.setObjectName("GroupRowFootnote")
            text_col.addWidget(note)
        h.addLayout(text_col, 0)

        if widget is not None:
            # Trailing side in both directions: the layout mirrors the
            # widget to the leading edge under RTL automatically.
            # stretch 1 lets the widget fill remaining space (e.g. a
            # PopupButton grows up to its maxWidth to show full text,
            # while a Switch with Fixed policy ignores the stretch).
            h.addWidget(widget, 1, Qt.AlignVCenter)

        self._rows.addWidget(row)
        return row


class SidebarItem(QAbstractButton):
    """A 28px sidebar nav row: icon + text, optional trailing count, 6px
    radius. Checked rows get a subtle white backdrop and an accent icon."""

    def __init__(self, text: str, icon_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self._icon_name = icon_name
        self._count: str | None = None
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(text)

    def set_count(self, count: str | None) -> None:
        """Show a muted trailing count; None hides it."""
        self._count = count
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(0, 28)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.isChecked() and self.isEnabled():
            p.setPen(Qt.NoPen)
            p.setBrush(_SELECTED_BG)
            p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        elif self.underMouse() and self.isEnabled():
            p.setPen(Qt.NoPen)
            p.setBrush(_HOVER_BG)
            p.drawRoundedRect(QRectF(self.rect()), 6, 6)

        rtl = self.layoutDirection() == Qt.RightToLeft
        w, h = self.width(), self.height()
        margin = 8
        icon_size = 16
        icon_pix = icon(
            self._icon_name,
            ACCENT if self.isChecked() else _ITEM_TEXT,
            icon_size,
        ).pixmap(icon_size, icon_size)

        count_w = 0
        count_font = QFont(self.font())
        count_font.setPixelSize(11)
        c_fm = QFontMetrics(count_font)
        if self._count:
            count_w = c_fm.horizontalAdvance(self._count)

        if rtl:
            icon_x = w - margin - icon_size
            count_x = margin
        else:
            icon_x = margin
            count_x = w - margin - count_w

        p.drawPixmap(int(icon_x), int((h - icon_size) / 2), icon_pix)

        if self._count:
            p.setFont(count_font)
            p.setPen(QColor(MUTED))
            count_rect = QRect(count_x, (h - c_fm.height()) / 2, count_w, c_fm.height())
            align = Qt.AlignLeft if rtl else Qt.AlignRight
            p.drawText(count_rect, align | Qt.AlignVCenter, self._count)

        gap = 8
        text_color = QColor("#ffffff") if self.isChecked() else QColor(_ITEM_TEXT)
        text_x = 0
        if rtl:
            right_edge = icon_x - gap
        else:
            text_x = icon_x + icon_size + gap
        avail = (
            w
            if rtl
            else w - text_x - margin - (count_w + gap if self._count else 0)
        )
        fm = self.fontMetrics()
        elided = fm.elidedText(self.text(), Qt.ElideRight, max(avail, 0))
        p.setFont(self.font())
        p.setPen(text_color)
        if rtl:
            text_w = min(avail, fm.horizontalAdvance(elided))
            text_rect = QRect(right_edge - text_w, (h - fm.height()) / 2,
                              text_w, fm.height())
            p.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, elided)
        else:
            text_rect = QRect(text_x, (h - fm.height()) / 2,
                              min(avail, fm.horizontalAdvance(elided)), fm.height())
            p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)


class SidebarSection(QLabel):
    """An 11px/600 slate sidebar subsection header."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("SidebarSection")
        self.setContentsMargins(8, 14, 8, 4)


class IconButton(QToolButton):
    """A 28x28 icon-only button. The tooltip is mandatory -- it also becomes
    the accessible name, so screen readers announce the same text."""

    def __init__(self, icon_name: str, tooltip: str, parent=None) -> None:
        if not tooltip:
            raise TypeError("IconButton() requires a tooltip")
        super().__init__(parent)
        self.setObjectName("IconButton")
        self.setFixedSize(28, 28)
        self.setIcon(icon(icon_name, TEXT, 16))
        self.setIconSize(QSize(16, 16))
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setAutoRaise(True)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)

    def sizeHint(self) -> QSize:
        # Always a square icon button; the QSS hides the menu-indicator that
        # a QToolButton with a menu would otherwise add to this hint.
        return QSize(28, 28)


class PopupButton(QToolButton):
    """A 26px macOS popup: a muted label, a normal-coloured value and a
    chevron, opening an InstantPopup QMenu. set_menu() attaches the menu;
    set_value() restyles it. Grows to fit the full text up to 240px, then
    elides and shows a tooltip holding the full value."""

    _MAX_WIDTH = 240

    def __init__(self, label: str, value: str = "", parent=None) -> None:
        super().__init__(parent)
        self._label = label
        self._value = value
        self.setPopupMode(QToolButton.InstantPopup)
        self.setCursor(Qt.PointingHandCursor)
        self.setMaximumWidth(self._MAX_WIDTH)
        self._sync_accessible()

    def set_value(self, text: str) -> None:
        self._value = text
        self._sync_accessible()
        self.updateGeometry()
        self.update()

    def set_menu(self, menu: QMenu) -> None:
        self.setMenu(menu)

    def _sync_accessible(self) -> None:
        self.setAccessibleName(f"{self._label}: {self._value}".strip(": ") or self._label)

    def resizeEvent(self, event) -> None:  # noqa: N802 – Qt convention
        super().resizeEvent(event)
        # Any elision in paintEvent means the value no longer fits; the
        # tooltip then carries the full label/value instead of clipping it.
        fm = self.fontMetrics()
        avail = max(self.width() - 2 * 10 - 12 - 6, 0)
        full = self._full_text()
        if fm.elidedText(full, Qt.ElideRight, avail) != full:
            self.setToolTip(full)
        else:
            self.setToolTip("")

    def sizeHint(self) -> QSize:
        # Same geometry the painter uses: leading pad + chevron + gap (+8 for
        # slack) on the leading side and trailing pad, so the full text fits
        # at its natural size and the paint code need not elide a Pixel early.
        w = self.fontMetrics().horizontalAdvance(self._full_text()) + 10 + 12 + 8 + 10
        return QSize(min(w, self._MAX_WIDTH), 26)

    def _full_text(self) -> str:
        text = self._value
        return f"{self._label}: {text}" if self._label else text

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        hovered = self.underMouse() and self.isEnabled()
        bg = QColor("#434347") if hovered else QColor(_POPUP_BG)
        line = QColor("#55555a") if hovered else QColor(_POPUP_LINE)
        p.setPen(QPen(line, 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)

        rtl = self.layoutDirection() == Qt.RightToLeft
        pad = 10
        chev = icon("chevron-down", MUTED, 12).pixmap(12, 12)
        chev_x = pad if rtl else w - pad - 12
        p.drawPixmap(int(chev_x), int((h - 12) / 2), chev)

        label = f"{self._label}: " if self._label else ""
        value = ltr(self._value) if self._value else ""
        fm = self.fontMetrics()
        head_w = fm.horizontalAdvance(label) if label else 0
        tail_w = fm.horizontalAdvance(value) if value else 0
        max_text = max(w - 2 * pad - 12 - 6, 0)
        if tail_w and head_w + tail_w > max_text:
            tail_w = max(max_text - head_w, 0)
            value = fm.elidedText(value, Qt.ElideRight, tail_w)
        text_w = head_w + tail_w

        y = (h - fm.height()) / 2
        if rtl:
            x0 = w - pad - text_w
        else:
            x0 = pad + 12 + 6
        if label:
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(x0, y, head_w, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, label)
        if tail_w:
            p.setPen(QColor(TEXT))
            p.drawText(QRectF(x0 + head_w, y, tail_w, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, value)
