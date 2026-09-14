"""Shared helpers for embeddable settings pages (the sidebar window's
in-place Routing and DNS editors). The one piece of behaviour both pages
need from the outside is asked-permission-to-leave with unsaved changes.
"""
from __future__ import annotations

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QMessageBox, QWidget

from ...i18n import tr


def _wait_for_apply(page: QWidget, timeout_ms: int = 30_000) -> bool:
    """Wait for the page's async apply to settle, on either side (applied or
    refused). Returns whether it applied. A synchronous refusal also settles
    inside apply() itself, so nothing is left to wait for here."""
    if not getattr(page, "_busy", True):
        return False
    result = {"value": False}
    loop = QEventLoop()

    def on_applied(_cfg) -> None:
        result["value"] = True
        loop.quit()

    page.applied.connect(on_applied)
    page.applyFinished.connect(loop.quit)
    timer = QTimer(loop)
    timer.setSingleShot(True)
    timer.setInterval(timeout_ms)
    timer.timeout.connect(loop.quit)
    timer.start()
    loop.exec()
    timer.stop()
    page.applied.disconnect(on_applied)
    page.applyFinished.disconnect(loop.quit)
    return result["value"]


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
    if not page.is_dirty():
        return True
    page.apply()
    return _wait_for_apply(page)
