"""Server table: model, filter/sort proxy, and the share-link QR dialog.

ProfilePanel (ui/widgets.py) wires these into the actual widget.
"""
from __future__ import annotations

import io
from math import inf

import segno
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core.profiles import Profile
from .theme import ERR, MUTED, OK, WARN

COLUMNS = ["", "Name", "Type", "Transport", "Subscription", "Delay"]
COL_ACTIVE, COL_NAME, COL_TYPE, COL_TRANSPORT, COL_SUB, COL_DELAY = range(len(COLUMNS))

# Thresholds match v2rayN's rough real-delay bands.
_OK_MS = 300
_WARN_MS = 800

_ROOT = QModelIndex()  # a fresh QModelIndex() per call is a ruff B008 default-arg smell


def _transport_text(p: Profile) -> str:
    if (p.protocol or "").lower() == "wireguard":
        return "—"
    return f"{p.network}/{p.security}"


class ProfileTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._profiles: list[Profile] = []
        self._active_uid: str | None = None
        self._results: dict[str, dict] = {}
        self._sub_names: dict[str, str] = {}

    # -- population ----------------------------------------------------
    def set_profiles(self, profiles: list[Profile], active_uid: str | None) -> None:
        self.beginResetModel()
        self._profiles = list(profiles)
        self._active_uid = active_uid
        self.endResetModel()

    def set_results(self, results: dict) -> None:
        self.beginResetModel()
        self._results = dict(results)
        self.endResetModel()

    def set_sub_names(self, names: dict) -> None:
        self.beginResetModel()
        self._sub_names = dict(names)
        self.endResetModel()

    def update_result(self, uid: str, delay_ms: float | None, error: str | None) -> None:
        self._results[uid] = {"delay_ms": delay_ms, "error": error}
        row = self.row_of_uid(uid)
        if row is not None:
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    # -- lookups ---------------------------------------------------------
    def profile_at(self, row: int) -> Profile | None:
        return self._profiles[row] if 0 <= row < len(self._profiles) else None

    def row_of_uid(self, uid: str) -> int | None:
        for i, p in enumerate(self._profiles):
            if p.uid == uid:
                return i
        return None

    def _delay_value(self, uid: str) -> float | None:
        r = self._results.get(uid)
        return r.get("delay_ms") if r else None

    def fastest_uid(self) -> str | None:
        best_uid, best = None, inf
        for p in self._profiles:
            v = self._delay_value(p.uid)
            if v is not None and v < best:
                best, best_uid = v, p.uid
        return best_uid

    # -- Qt model interface ------------------------------------------------
    def rowCount(self, parent=_ROOT) -> int:
        return 0 if parent.isValid() else len(self._profiles)

    def columnCount(self, parent=_ROOT) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        p = self._profiles[index.row()]
        col = index.column()
        result = self._results.get(p.uid) or {}

        if role == Qt.UserRole:
            if col == COL_DELAY:
                v = self._delay_value(p.uid)
                return v if v is not None else inf
            return None

        if role == Qt.DisplayRole:
            if col == COL_ACTIVE:
                return "●" if p.uid == self._active_uid else ""
            if col == COL_NAME:
                return p.name
            if col == COL_TYPE:
                return p.protocol
            if col == COL_TRANSPORT:
                return _transport_text(p)
            if col == COL_SUB:
                return (self._sub_names.get(p.sub_uid) or "—") if p.sub_uid else "—"
            if col == COL_DELAY:
                delay = self._delay_value(p.uid)
                if delay is not None:
                    return f"{round(delay)} ms"
                return "Failed" if result.get("error") else "—"
            return None

        if role == Qt.ToolTipRole and col == COL_DELAY:
            return result.get("error") or None

        if role == Qt.ForegroundRole and col == COL_DELAY:
            delay = self._delay_value(p.uid)
            if delay is None:
                return QColor(ERR if result.get("error") else MUTED)
            if delay < _OK_MS:
                return QColor(OK)
            if delay < _WARN_MS:
                return QColor(WARN)
            return QColor(ERR)

        if role == Qt.TextAlignmentRole and col in (COL_ACTIVE, COL_DELAY):
            return Qt.AlignCenter

        return None


class ProfileFilterProxy(QSortFilterProxyModel):
    """Matches name or address (case-insensitive); sorts Delay numerically
    with untested/failed profiles last."""

    def __init__(self) -> None:
        super().__init__()
        self._needle = ""

    def set_needle(self, text: str) -> None:
        self._needle = text.strip().lower()
        self.invalidate()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        if not self._needle:
            return True
        model = self.sourceModel()
        p = model.profile_at(source_row)
        if p is None:
            return False
        return self._needle in p.name.lower() or self._needle in (p.address or "").lower()

    def lessThan(self, left, right) -> bool:
        if left.column() == COL_DELAY:
            lv = self.sourceModel().data(left, Qt.UserRole)
            rv = self.sourceModel().data(right, Qt.UserRole)
            return (inf if lv is None else lv) < (inf if rv is None else rv)
        return super().lessThan(left, right)


class QrDialog(QDialog):
    """A share link rendered as a QR code, with a Copy link button."""

    def __init__(self, name: str, link: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"QR — {name}")
        self._link = link

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        buf = io.BytesIO()
        segno.make(link, error="m").save(buf, kind="png", scale=8, border=2)
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        self.image_label.setPixmap(pix)

        copy_btn = QPushButton("Copy link")
        copy_btn.clicked.connect(self._copy)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(copy_btn)
        row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.image_label)
        layout.addLayout(row)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._link)
