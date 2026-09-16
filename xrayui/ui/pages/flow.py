"""A QLayout subclass that wraps its widgets onto new rows when the parent
gets too narrow for all of them -- the preset button rows on the Routing and
DNS pages would otherwise clip or force the window wider than its content
width at the sidebar's narrower sizes."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(self._layout(QRect(0, 0, width, 0), True),
                   self.minimumSize().height())

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout(rect, False)

    def _layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        y = rect.y() + margins.top()
        row_height = 0
        # QLayout.layoutDirection() is not reliably exposed in PySide; read
        # it from the parent widget (always set before the layout activates).
        parent = self.parentWidget()
        rtl = parent is not None and parent.layoutDirection() == Qt.RightToLeft
        limit_left = rect.x() + margins.left()
        limit_right = rect.right() - margins.right()
        # cursor tracks the leading edge of the next item -- its left edge in
        # LTR, its right edge in RTL -- so a row starts at the leading border
        # and grows toward the trailing one. Without the RTL mirroring the
        # preset rows would still start at the left edge, leaving a gap beside
        # the right-aligned label the page's parent lays the flow next to.
        cursor = limit_right if rtl else limit_left
        for item in self._items:
            hint = item.sizeHint()
            if rtl:
                overflow = cursor - hint.width() < limit_left
            else:
                overflow = cursor + hint.width() > limit_right
            if overflow and row_height > 0:
                cursor = limit_right if rtl else limit_left
                y += row_height + self._spacing
                row_height = 0
            if not test_only:
                if rtl:
                    x = cursor - hint.width()
                else:
                    x = cursor
                item.setGeometry(QRect(QPoint(x, y), hint))
            if rtl:
                cursor -= hint.width() + self._spacing
            else:
                cursor += hint.width() + self._spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y()
