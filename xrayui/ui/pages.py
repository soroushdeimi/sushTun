"""Shared helpers for embeddable settings pages (the sidebar window's
in-place Routing and DNS editors). The one piece of behaviour both pages
need from the outside is asked-permission-to-leave with unsaved changes.
"""
from __future__ import annotations

import time

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from ..i18n import tr


def _wait_for_apply(page: QWidget) -> bool:
    """Block the caller's event loop until the page's async apply settles,
    on either side (applied or refused). Returns whether it applied."""
    result = {"value": False, "done": False}

    def on_applied(_cfg) -> None:
        result["value"] = True
        result["done"] = True

    def on_finished(_applied: bool) -> None:
        result["done"] = True

    page.applied.connect(on_applied)
    page.applyFinished.connect(on_finished)
    try:
        deadline = time.time() + 30.0
        while not result["done"] and time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        return result["value"]
    finally:
        page.applied.disconnect(on_applied)
        page.applyFinished.disconnect(on_finished)


def confirm_leave(page: QWidget, parent: QWidget | None = None) -> bool:
    """Ask before switching away from a page with uncommitted edits.

    Returns True when leaving is safe (nothing changed, edits were applied,
    or the user chose to discard them); False to stay on the page. A refused
    apply counts as staying -- the page still holds the user's edits and the
    reason is visible on it.
    """
    if not page.is_dirty():
        return True
    box = QMessageBox(parent)
    box.setWindowTitle(tr("Apply changes?"))
    box.setText(tr("You have unsaved changes."))
    btn_apply = box.addButton(tr("Apply"), QMessageBox.AcceptRole)
    btn_discard = box.addButton(tr("Discard"), QMessageBox.DestructiveRole)
    box.addButton(tr("Cancel"), QMessageBox.RejectRole)
    box.setDefaultButton(btn_apply)
    box.exec()
    clicked = box.clickedButton()
    if clicked is btn_discard:
        return True
    if clicked is not btn_apply:
        return False  # Cancel or Escape
    if page.is_dirty():
        page.apply()
        return _wait_for_apply(page)
    return True
