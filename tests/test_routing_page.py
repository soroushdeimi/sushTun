"""RoutingPage (embeddable): validation failures refuse inline on the page's
status label and never touch the stored routing. The dialog is the same page
behind a thin wrapper, so that behaviour is covered here once for both entry
points.
"""
from __future__ import annotations

import os
import time

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from xrayui.core import xraycheck  # noqa: E402
from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.ui.routing_page import RoutingPage, _ltr, _match_summary  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pump(condition, timeout=5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def test_invalid_rule_set_check_refuses_inline_and_leaves_settings_unchanged(qapp, monkeypatch):
    calls = []
    # Simple mode is always validated first; refuse only the rule-set call so
    # the failure is attributed to the set, not to Simple mode.
    monkeypatch.setattr(xraycheck, "check_rules",
                        lambda rules, asset_dir=None: calls.append(rules) or
                        (None if len(calls) == 1 else "bad rule"))
    page = RoutingPage(DEFAULTS["routing"])
    page._add_set("global")

    original_routing = page.result_routing()
    assert original_routing.get("sets") in (None, [])  # nothing saved yet

    page.apply()
    _pump(lambda: not page._busy)
    assert page.status_label.text() == "'Global': bad rule"
    assert page.is_dirty()
    # _routing is only replaced by the validated candidate on success.
    assert page.result_routing() is original_routing


def test_bad_simple_mode_rule_refuses_inline_and_leaves_settings_unchanged(qapp, monkeypatch):
    def fake_check(rules, asset_dir=None):
        for r in rules:
            if "domain:gogle.com" in (r.get("domain") or []):
                return 'code not found in geosite.dat: "GOGLE.COM"'
        return None

    monkeypatch.setattr(xraycheck, "check_rules", fake_check)
    page = RoutingPage(DEFAULTS["routing"])
    page.domains.setPlainText("gogle.com")
    original_routing = page.result_routing()

    page.apply()
    _pump(lambda: not page._busy)
    assert page.status_label.text() == 'Simple: code not found in geosite.dat: "GOGLE.COM"'
    assert page.result_routing() is original_routing


def test_match_summary_isolates_latin_port_numbers():
    # A bare Latin number inside RTL text must be wrapped as a unit so it
    # does not get mirrored when displayed in a Persian UI.
    summary = _match_summary({"port": 443, "network": "tcp"})
    assert "\u2066443\u2069" in summary
    assert "443" in summary.replace("\u2066", "").replace("\u2069", "")
    assert _match_summary({"port": 443}) == f"port {_ltr('443')}"


def test_dirty_revert_and_applied_signal(qapp, monkeypatch):
    monkeypatch.setattr(xraycheck, "check_rules", lambda rules, asset_dir=None: None)
    page = RoutingPage(DEFAULTS["routing"])
    assert not page.is_dirty()
    assert not page.btn_apply.isEnabled()

    captured = []
    page.applied.connect(lambda cfg: captured.append(cfg))
    page.domains.setPlainText("example.com")
    assert page.is_dirty()
    assert page.btn_apply.isEnabled()
    assert page.result_routing()["bypass_domains"] == []  # not applied yet

    page.apply()
    _pump(lambda: not page._busy)

    assert len(captured) == 1
    assert page.result_routing()["bypass_domains"] == ["example.com"]
    assert not page.is_dirty()
    assert not page.btn_apply.isEnabled()

    page.domains.setPlainText("other.com")
    assert page.is_dirty()
    page.revert()
    assert not page.is_dirty()
    assert page.result_routing()["bypass_domains"] == ["example.com"]
    assert page.domains.toPlainText() == "example.com"


def test_rule_move_buttons_have_tooltip_and_accessible_name(qapp):
    page = RoutingPage(DEFAULTS["routing"])
    page._add_set("empty")
    move = {b for b in page.findChildren(QToolButton) if b.toolTip()}
    tips = {b.toolTip() for b in move}
    assert tips == {"Move rule up", "Move rule down"}
    for b in move:
        assert b.accessibleName() == b.toolTip()


def test_enter_in_the_domains_editor_inserts_a_newline_not_an_apply(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(xraycheck, "check_rules", lambda rules, asset_dir=None: calls.append(rules))
    page = RoutingPage(DEFAULTS["routing"])
    page.domains.setFocus()
    QTest.keyClick(page.domains, Qt.Key_Return)
    assert not calls  # Return is a new paragraph, never a save
    assert "\n" in page.domains.toPlainText()
