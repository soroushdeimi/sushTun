"""confirm_leave(): asked before switching away from a dirty page, with
Apply / Discard / Cancel; a refused apply keeps the user on the page.
"""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from xrayui.core import xraycheck  # noqa: E402
from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.i18n import tr  # noqa: E402
from xrayui.ui.pages import leave as pages_mod  # noqa: E402
from xrayui.ui.pages.routing_page import RoutingPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Box:
    """QMessageBox stand-in that never blocks; the test picks which button
    looked clicked via .click_index (order: Apply, Discard, Cancel)."""

    last: _Box | None = None
    AcceptRole = QMessageBox.AcceptRole
    DestructiveRole = QMessageBox.DestructiveRole
    RejectRole = QMessageBox.RejectRole

    def __init__(self, parent=None):
        self.labels = []
        self.title = ""
        self.text = ""
        _Box.last = self

    def setWindowTitle(self, t) -> None:
        self.title = t

    def setText(self, t) -> None:
        self.text = t

    def addButton(self, label, role):
        self.labels.append(label)
        return label

    def setDefaultButton(self, button) -> None:
        self.default = button

    def exec(self) -> int:
        return 0

    def clickedButton(self):
        return self.labels[self.click_index]


@pytest.fixture
def box(monkeypatch):
    monkeypatch.setattr(pages_mod, "QMessageBox", _Box)
    return _Box


def test_clean_page_leaves_without_asking(qapp, box):
    page = RoutingPage(DEFAULTS["routing"])
    assert pages_mod.confirm_leave(page) is True
    assert box.last is None  # no dialog was ever constructed


def test_discard_leaves(qapp, box):
    page = RoutingPage(DEFAULTS["routing"])
    page.domains.setPlainText("example.com")
    box.click_index = 1  # Discard
    assert pages_mod.confirm_leave(page) is True
    assert box.last.title == tr("Apply changes?")
    assert box.last.text == tr("You have unsaved changes.")
    assert box.last.labels == [tr("Apply"), tr("Discard"), tr("Cancel")]


def test_cancel_stays(qapp, box):
    page = RoutingPage(DEFAULTS["routing"])
    page.domains.setPlainText("example.com")
    box.click_index = 2  # Cancel
    assert pages_mod.confirm_leave(page) is False
    assert page.is_dirty()  # edits are kept for whoever stays


def test_apply_applies_then_leaves(qapp, box, monkeypatch):
    monkeypatch.setattr(xraycheck, "check_rules", lambda rules, asset_dir=None: None)
    page = RoutingPage(DEFAULTS["routing"])
    page.domains.setPlainText("example.com")
    box.click_index = 0  # Apply
    assert pages_mod.confirm_leave(page) is True
    assert page.result_routing()["bypass_domains"] == ["example.com"]
    assert not page.is_dirty()


def test_a_refused_apply_keeps_you_on_the_page(qapp, box, monkeypatch):
    monkeypatch.setattr(xraycheck, "check_rules", lambda rules, asset_dir=None: "bad rule")
    page = RoutingPage(DEFAULTS["routing"])
    page.domains.setPlainText("example.com")
    box.click_index = 0  # Apply
    assert pages_mod.confirm_leave(page) is False
    assert page.is_dirty()
    assert page.status_label.text() == "Simple: bad rule"
