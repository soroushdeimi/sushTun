"""Mac-style window chrome: traffic-light buttons and a draggable title bar.

Used on Windows and Linux, where the window is frameless. macOS keeps its own
native title bar, which already looks like this.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QWidget

# (fill, rim) per button, taken from macOS.
_COLORS = {
    "close": ("#ff5f57", "#e14640"),
    "minimize": ("#febc2e", "#dfa123"),
    "zoom": ("#28c840", "#1dad2b"),
}
_INACTIVE = ("#4b4e54", "#3f4247")
_TIPS = {"close": "Close", "minimize": "Minimize", "zoom": "Zoom"}
_DIAMETER = 12.0


class TrafficLight(QAbstractButton):
    """One of the three round buttons. Its glyph shows only while the group is hovered."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setObjectName(f"Light_{kind}")
        self.setFixedSize(QSize(14, 14))
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip(_TIPS[kind])
        self._glyph = False
        self._active = True

    def set_glyph(self, on: bool) -> None:
        self._glyph = on
        self.update()

    def set_active(self, on: bool) -> None:
        self._active = on
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Like macOS: an unfocused window greys its lights until they are hovered.
        fill, rim = _COLORS[self.kind] if (self._active or self._glyph) else _INACTIVE
        color = QColor(fill)
        if self.isDown():
            color = color.darker(120)
        off = (self.width() - _DIAMETER) / 2
        p.setPen(QPen(QColor(rim), 0.8))
        p.setBrush(color)
        p.drawEllipse(QRectF(off, off, _DIAMETER, _DIAMETER))
        if self._glyph:
            self._paint_glyph(p, self.width() / 2)

    def _paint_glyph(self, p: QPainter, c: float) -> None:
        ink = QColor(0, 0, 0, 150)
        if self.kind == "zoom":
            # Two corner triangles, as on macOS.
            p.setPen(Qt.NoPen)
            p.setBrush(ink)
            for pts in (((-2.9, -2.9), (0.9, -2.9), (-2.9, 0.9)),
                        ((2.9, 2.9), (-0.9, 2.9), (2.9, -0.9))):
                path = QPainterPath(QPointF(c + pts[0][0], c + pts[0][1]))
                for x, y in pts[1:]:
                    path.lineTo(c + x, c + y)
                path.closeSubpath()
                p.drawPath(path)
            return
        p.setPen(QPen(ink, 1.3, Qt.SolidLine, Qt.RoundCap))
        if self.kind == "close":
            d = 2.6
            p.drawLine(QPointF(c - d, c - d), QPointF(c + d, c + d))
            p.drawLine(QPointF(c - d, c + d), QPointF(c + d, c - d))
        else:
            p.drawLine(QPointF(c - 3.2, c), QPointF(c + 3.2, c))


class _LightGroup(QWidget):
    """Hovering anywhere over the three lights reveals all three glyphs, as on macOS."""

    def __init__(self, lights: list[TrafficLight]) -> None:
        super().__init__()
        self.lights = lights
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for light in lights:
            row.addWidget(light)

    def enterEvent(self, event) -> None:
        for light in self.lights:
            light.set_glyph(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        for light in self.lights:
            light.set_glyph(False)
        super().leaveEvent(event)


class TitleBar(QWidget):
    """Traffic lights on the left, the window title centred; drag to move, double-click to zoom."""

    HEIGHT = 40

    def __init__(self, window: QWidget) -> None:
        super().__init__()
        self.setObjectName("TitleBar")
        self.setFixedHeight(self.HEIGHT)
        self._win = window
        self._drag_offset = None

        self.btn_close = TrafficLight("close")
        self.btn_minimize = TrafficLight("minimize")
        self.btn_zoom = TrafficLight("zoom")
        self.btn_close.clicked.connect(window.close)
        self.btn_minimize.clicked.connect(window.showMinimized)
        self.btn_zoom.clicked.connect(self.toggle_zoom)
        self.lights = _LightGroup([self.btn_close, self.btn_minimize, self.btn_zoom])

        self.title = QLabel(window.windowTitle())
        self.title.setObjectName("WindowTitle")
        self.title.setAlignment(Qt.AlignCenter)
        window.windowTitleChanged.connect(self.title.setText)

        # An empty twin of the lights on the right keeps the title truly centred.
        balance = QWidget()
        balance.setFixedWidth(self.lights.sizeHint().width())

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 14, 0)
        row.addWidget(self.lights)
        row.addWidget(self.title, 1)
        row.addWidget(balance)

    def toggle_zoom(self) -> None:
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def set_active(self, active: bool) -> None:
        for light in self.lights.lights:
            light.set_active(active)
        self.title.setProperty("inactive", not active)
        self.title.style().unpolish(self.title)
        self.title.style().polish(self.title)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        # Let the compositor move the window: the only way on Wayland, and it
        # gets edge snapping on Windows and X11 for free.
        handle = self._win.windowHandle()
        if handle is not None and handle.startSystemMove():
            event.accept()
            return
        self._drag_offset = event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            if self._win.isMaximized():
                return
            self._win.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.toggle_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
