"""First-run spotlight tour: dims the window, lights one real control at a time
and explains it in a small bubble beside it."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..i18n import current, ltr, tr
from .theme import ACCENT, MUTED, TEXT

PAD = 6
RADIUS = 10
_MARGIN = 12
_ARROW = 9
_GAP = 14
_BUBBLE_W = 340
_BUBBLE_BG = "#2c2c30"
_DIM = QColor(0, 0, 0, 166)


@dataclass
class Step:
    title: str
    text: str
    target: Callable[[], QWidget | list[QWidget] | None] | None = None
    page: int | None = None


class SpotlightTour(QWidget):
    finished = Signal()

    def __init__(self, window: QWidget, steps: list[Step],
                 show_page: Callable[[int], None] | None = None) -> None:
        super().__init__(window)
        self._win = window
        self._steps = steps
        self._show_page = show_page
        self._index = 0
        self._cut: QRect | None = None
        self._arrow: QPolygonF | None = None
        self._done = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self._build_bubble()
        window.installEventFilter(self)
        self.setGeometry(window.rect())

    def _build_bubble(self) -> None:
        rtl = current() == "fa"
        direction = Qt.RightToLeft if rtl else Qt.LeftToRight
        self.bubble = QFrame(self)
        self.bubble.setObjectName("TourBubble")
        self.bubble.setLayoutDirection(direction)
        self.bubble.setStyleSheet(
            f"QFrame#TourBubble{{background:{_BUBBLE_BG}; border-radius:12px;}}"
            f"QFrame#TourBubble QLabel{{background:transparent;}}")
        lay = QVBoxLayout(self.bubble)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(6)

        self.counter_label = QLabel()
        self.counter_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.title_label = QLabel()
        self.title_label.setStyleSheet(
            f"color:{TEXT}; font-size:16px; font-weight:700;")
        self.title_label.setWordWrap(True)
        self.text_label = QLabel()
        self.text_label.setStyleSheet(f"color:{TEXT}; font-size:13px;")
        self.text_label.setWordWrap(True)
        for label in (self.counter_label, self.title_label, self.text_label):
            label.setAlignment(Qt.AlignLeading | Qt.AlignTop)
        lay.addWidget(self.counter_label)
        lay.addWidget(self.title_label)
        lay.addWidget(self.text_label)
        lay.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.skip_button = QPushButton(tr("Skip"))
        self.skip_button.setFlat(True)
        self.skip_button.setStyleSheet(
            f"QPushButton{{color:{MUTED}; background:transparent; border:none;"
            "padding:6px 4px;}"
            f"QPushButton:hover{{color:{TEXT};}}")
        self.back_button = QPushButton(tr("Back"))
        self.next_button = QPushButton(tr("Next"))
        self.next_button.setObjectName("Primary")
        for button in (self.skip_button, self.back_button, self.next_button):
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
        self.skip_button.clicked.connect(self.skip)
        self.back_button.clicked.connect(self.back)
        self.next_button.clicked.connect(self.next)
        row.addWidget(self.skip_button)
        row.addStretch(1)
        row.addWidget(self.back_button)
        row.addWidget(self.next_button)
        lay.addLayout(row)

    # ── state ─────────────────────────────────────────────────────────────

    def step_count(self) -> int:
        return len(self._steps)

    def index(self) -> int:
        return self._index

    def is_last(self) -> bool:
        return self._index == len(self._steps) - 1

    def cutout(self) -> QRect | None:
        return self._cut

    def bubble_rect(self) -> QRect:
        return self.bubble.geometry()

    def start(self) -> None:
        self.setGeometry(self._win.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.go_to(0)

    def next(self) -> None:
        if self.is_last():
            self._finish()
        else:
            self.go_to(self._index + 1)

    def back(self) -> None:
        if self._index > 0:
            self.go_to(self._index - 1)

    def skip(self) -> None:
        self._finish()

    def go_to(self, index: int) -> None:
        if self._done:
            return
        try:
            self._index = max(0, min(index, len(self._steps) - 1))
            step = self._steps[self._index]
            if step.page is not None and self._show_page is not None:
                self._show_page(step.page)
            self.counter_label.setText(
                ltr(f"{self._index + 1} / {len(self._steps)}"))
            self.title_label.setText(step.title)
            self.text_label.setText(step.text)
            last = self.is_last()
            self.next_button.setText(tr("Done") if last else tr("Next"))
            self.back_button.setVisible(self._index > 0)
            self.skip_button.setVisible(not last)
            self._layout_step()
            QTimer.singleShot(0, self._relayout)
        except Exception:
            self._finish()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._win.removeEventFilter(self)
        self.hide()
        self.finished.emit()

    # ── geometry ──────────────────────────────────────────────────────────

    def _relayout(self) -> None:
        if self._done:
            return
        try:
            self.setGeometry(self._win.rect())
            self._layout_step()
        except Exception:
            self._finish()

    def _target_rect(self) -> QRect | None:
        step = self._steps[self._index]
        if step.target is None:
            return None
        targets = step.target()
        if targets is None:
            return None
        if isinstance(targets, QWidget):
            targets = [targets]
        union = QRect()
        for widget in targets:
            if not widget.isVisible() or widget.width() <= 0 or widget.height() <= 0:
                return None
            union = union.united(
                QRect(widget.mapTo(self._win, QPoint(0, 0)), widget.size()))
        return union if not union.isEmpty() else None

    def _layout_step(self) -> None:
        bounds = self.rect()
        width = min(_BUBBLE_W, bounds.width() - 2 * _MARGIN)
        self.bubble.setFixedWidth(width)
        height = self.bubble.layout().totalHeightForWidth(width)
        height = max(height, self.bubble.layout().sizeHint().height())
        height = min(height, bounds.height() - 2 * _MARGIN)
        self.bubble.setFixedHeight(height)

        target = self._target_rect()
        self._arrow = None
        if target is None:
            self._cut = None
            self.bubble.move(bounds.center().x() - width // 2,
                             bounds.center().y() - height // 2)
        else:
            self._cut = target.adjusted(-PAD, -PAD, PAD, PAD)
            self._place(width, height)
        self.update()

    def _place(self, w: int, h: int) -> None:
        bounds = self.rect()
        cut = self._cut
        left_edge, right_edge = _MARGIN, bounds.width() - _MARGIN - w
        top_edge, bottom_edge = _MARGIN, bounds.height() - _MARGIN - h

        def clamp(value: int, low: int, high: int) -> int:
            return max(low, min(value, max(low, high)))

        x_mid = clamp(cut.center().x() - w // 2, left_edge, right_edge)
        y_mid = clamp(cut.center().y() - h // 2, top_edge, bottom_edge)
        below = (x_mid, cut.bottom() + 1 + _GAP, "down")
        above = (x_mid, cut.top() - _GAP - h, "up")
        right = (cut.right() + 1 + _GAP, y_mid, "right")
        left = (cut.left() - _GAP - w, y_mid, "left")
        order = [below, above, left, right] if current() == "fa" \
            else [below, above, right, left]
        for x, y, side in order:
            if (left_edge <= x <= right_edge and top_edge <= y <= bottom_edge):
                self.bubble.move(x, y)
                self._arrow = self._arrow_for(QRect(x, y, w, h), side)
                return
        # The target fills most of the window; sit inside it with no arrow.
        self.bubble.move(clamp(cut.center().x() - w // 2, left_edge, right_edge),
                         clamp(cut.center().y() - h // 2, top_edge, bottom_edge))

    def _arrow_for(self, box: QRect, side: str) -> QPolygonF:
        cut = self._cut
        half = 9
        if side in ("down", "up"):
            x = max(box.left() + 22, min(cut.center().x(), box.right() - 22))
            if side == "down":
                base, tip = box.top() + 1, box.top() - _ARROW
            else:
                base, tip = box.bottom(), box.bottom() + _ARROW
            return QPolygonF([QPointF(x - half, base), QPointF(x + half, base),
                              QPointF(x, tip)])
        y = max(box.top() + 22, min(cut.center().y(), box.bottom() - 22))
        if side == "right":
            base, tip = box.left() + 1, box.left() - _ARROW
        else:
            base, tip = box.right(), box.right() + _ARROW
        return QPolygonF([QPointF(base, y - half), QPointF(base, y + half),
                          QPointF(tip, y)])

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRect(QRectF(self.rect()))
            if self._cut is not None:
                hole = QPainterPath()
                hole.addRoundedRect(QRectF(self._cut), RADIUS, RADIUS)
                path = path.subtracted(hole)
            painter.fillPath(path, _DIM)
            if self._cut is not None:
                ring = QColor(ACCENT)
                ring.setAlpha(70)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(ring, 6))
                painter.drawRoundedRect(QRectF(self._cut), RADIUS, RADIUS)
                painter.setPen(QPen(QColor(ACCENT), 2))
                painter.drawRoundedRect(QRectF(self._cut), RADIUS, RADIUS)
            if self._arrow is not None:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(_BUBBLE_BG))
                painter.drawPolygon(self._arrow)
            painter.end()
        except Exception:
            QTimer.singleShot(0, self._finish)

    # ── input ─────────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter):
            self.next()
        elif key == Qt.Key_Left:
            self.back()
        elif key == Qt.Key_Escape:
            self.skip()
        else:
            event.ignore()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()
        self.setFocus()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self._win and event.type() in (QEvent.Resize, QEvent.Move):
            self.setGeometry(self._win.rect())
            QTimer.singleShot(0, self._relayout)
        return False
