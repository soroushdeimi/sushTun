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
from ..i18n import tr
from .theme import ERR, MUTED, OK, WARN

COLUMNS = ["", "Name", "Delay", "Transport", "Subscription", "Type"]
COL_ACTIVE, COL_NAME, COL_DELAY, COL_TRANSPORT, COL_SUB, COL_TYPE = range(len(COLUMNS))
# Optional columns a viewer can hide from the header's right-click menu.
OPTIONAL_COLUMNS = ((COL_TRANSPORT, "Transport"), (COL_SUB, "Subscription"), (COL_TYPE, "Type"))

# Thresholds match v2rayN's rough real-delay bands.
_OK_MS = 300
_WARN_MS = 800

_ROOT = QModelIndex()  # a fresh QModelIndex() per call is a ruff B008 default-arg smell


def _transport_text(p: Profile) -> str:
    if (p.protocol or "").lower() == "wireguard":
        return "wg"
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

    def _redraw(self) -> None:
        # A plain data refresh, not a structural change: dataChanged (not a
        # begin/endResetModel pair) so the view's selection survives it.
        # _reload_profiles() calls set_results/set_sub_names before
        # set_profiles, and a reset here would clear the selection set_
        # profiles later tries to preserve, before it ever gets a chance to.
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(self.rowCount() - 1, self.columnCount() - 1))

    def set_results(self, results: dict) -> None:
        self._results = dict(results)
        self._redraw()

    def set_sub_names(self, names: dict) -> None:
        self._sub_names = dict(names)
        self._redraw()

    def set_active_uid(self, uid: str | None) -> None:
        # Only the ● column of the old and new active rows changes -- no
        # reset, so a multi-selection made for Test/Delete survives.
        old = self._active_uid
        self._active_uid = uid
        for u in (old, uid):
            if not u:
                continue
            row = self.row_of_uid(u)
            if row is not None:
                idx = self.index(row, COL_ACTIVE)
                self.dataChanged.emit(idx, idx)

    def update_result(
        self, uid: str, delay_ms: float | None, error: str | None, skipped: bool = False,
    ) -> None:
        self._results[uid] = {"delay_ms": delay_ms, "error": error, "skipped": skipped}
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
        # Skipped and failed profiles both have delay_ms=None, so they're
        # already excluded here without checking "skipped" separately.
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
            return tr(COLUMNS[section])
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
                if result.get("skipped"):
                    return tr("n/a")
                return tr("Failed") if result.get("error") else "—"
            return None

        if role == Qt.ToolTipRole and col == COL_DELAY:
            return result.get("error") or None

        if role == Qt.ForegroundRole and col == COL_DELAY:
            if result.get("skipped"):
                return QColor(MUTED)
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
        self.setWindowTitle(tr("QR — {name}", name=name))
        self._link = link

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        buf = io.BytesIO()
        segno.make(link, error="m").save(buf, kind="png", scale=8, border=2)
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        self.image_label.setPixmap(pix)

        copy_btn = QPushButton(tr("Copy link"))
        copy_btn.clicked.connect(self._copy)
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(copy_btn)
        row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.image_label)
        layout.addLayout(row)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._link)
